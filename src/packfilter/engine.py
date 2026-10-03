"""Scan -> classify -> censor/restore pipeline shared by the GUI and the CLI."""

from __future__ import annotations

import io
import os
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image

from .censor import censor_bytes, censor_file
from .model import RatingModel, ensure_model, preprocess
from .policy import Settings
from .scanner import ImageEntry, Pack, scan_path
from .store import Store, sha256_bytes

ProgressFn = Callable[[int, int, str], None]  # (done, total, message)

CHUNK = 64


class Cancelled(Exception):
    pass


@dataclass
class Item:
    path: Path
    pack: str
    pack_root: Path
    song: str
    categories: set[str]
    sha: str = ""
    scores: Optional[dict[str, float]] = None
    censored: bool = False          # the file on disk is a censored copy we made
    error: Optional[str] = None
    override: Optional[bool] = None  # user forced censor (True) / keep (False)

    def will_censor(self, settings: Settings) -> bool:
        return not self.censored and self.error is None and \
            settings.should_censor(self.scores, self.categories, self.override)


@dataclass
class ApplyResult:
    censored: int = 0
    restored: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    output_roots: list[Path] = field(default_factory=list)


def items_from_packs(packs: Iterable[Pack]) -> list[Item]:
    out = []
    for pack in packs:
        for e in pack.images:
            out.append(Item(path=e.path, pack=pack.name, pack_root=pack.root, song=e.song,
                            categories=set(e.categories)))
    return out


_STORED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ogg", ".mp3", ".opus", ".m4a", ".flac",
                ".mp4", ".avi", ".webm", ".mkv", ".zip", ".7z", ".rar"}
_JUNK = {".ds_store", "thumbs.db", "desktop.ini"}


def _walk_pack(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d != "__MACOSX" and not d.startswith("._"))
        for name in sorted(filenames):
            if name.startswith("._") or name.lower() in _JUNK or name.endswith((".pftmp", ".part")):
                continue
            yield Path(dirpath) / name


def _size(f: Path) -> int:
    try:
        return f.stat().st_size
    except OSError:
        return 0


def _compression(f: Path) -> int:
    # Images and audio are already compressed; storing them is much faster.
    return zipfile.ZIP_STORED if f.suffix.lower() in _STORED_EXTS else zipfile.ZIP_DEFLATED


def _safe_name(name: str) -> str:
    return "".join("_" if c in '<>:"/\\|?*' else c for c in name).strip() or "pack"


def _unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    stem = p.name[:-len(".zip")]
    i = 2
    while (p.with_name(f"{stem} {i}.zip")).exists():
        i += 1
    return p.with_name(f"{stem} {i}.zip")


def _decode_zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    raw = info.filename.encode("cp437", errors="replace")
    for enc in ("utf-8", "cp932"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return info.filename


def _safe_member(name: str) -> bool:
    parts = name.replace("\\", "/").split("/")
    return not (name.startswith(("/", "\\")) or ":" in parts[0] or ".." in parts or parts[0] == "__MACOSX")


def extract_zip(zip_path: Path, dest: Path, cancel: Optional[threading.Event] = None) -> Path:
    """Extract a downloaded pack. Returns the folder that now holds the pack."""
    with zipfile.ZipFile(zip_path) as zf:
        members = [(i, _decode_zip_name(i)) for i in zf.infolist()]
        members = [(i, n) for i, n in members if _safe_member(n)]
        tops = {n.replace("\\", "/").split("/", 1)[0] for _, n in members if n.strip("/")}
        single_top = len(tops) == 1 and all("/" in n.replace("\\", "/") for _, n in members)
        base = dest if single_top else dest / zip_path.stem
        base_resolved = base.resolve()
        for info, name in members:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            target = (base / name.replace("\\", "/")).resolve()
            if base_resolved not in target.parents and target != base_resolved:
                continue  # zip-slip protection
            if info.is_dir() or name.endswith(("/", "\\")):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
        return (base / next(iter(tops))) if single_top else base


class Engine:
    def __init__(self, store: Optional[Store] = None, model_name: Optional[str] = None):
        self.store = store or Store()
        self.model_name = model_name
        self._model: Optional[RatingModel] = None
        self._model_gpu = False
        self._model_lock = threading.Lock()

    # --- model ---------------------------------------------------------------
    def model(self, model_name: str, progress: Optional[ProgressFn] = None,
              cancel: Optional[threading.Event] = None, use_gpu: bool = False) -> RatingModel:
        with self._model_lock:
            m = self._model
            if m is None or m.model_name != model_name or self._model_gpu != use_gpu:
                def dl(done, total):
                    if progress:
                        progress(done, total, "Downloading the rating model (one time only)...")
                path = ensure_model(model_name, dl, cancel)
                if progress and use_gpu:
                    progress(0, 0, "Checking whether the GPU can be used...")
                self._model = RatingModel(model_name, path, use_gpu=use_gpu)
                self._model_gpu = use_gpu
            return self._model

    @property
    def device(self) -> Optional[str]:
        return self._model.device if self._model else None

    # --- scanning ------------------------------------------------------------
    @staticmethod
    def collect(paths: Iterable[Path]) -> list[Pack]:
        packs: dict[Path, Pack] = {}
        for p in paths:
            for pack in scan_path(Path(p)):
                if pack.root in packs:
                    known = {i.path for i in packs[pack.root].images}
                    packs[pack.root].images.extend(i for i in pack.images if i.path not in known)
                else:
                    packs[pack.root] = pack
        return list(packs.values())

    def classify(self, items: list[Item], model_name: str, progress: Optional[ProgressFn] = None,
                 cancel: Optional[threading.Event] = None, use_gpu: bool = False) -> None:
        """Fill in sha/scores/censored for every item. Cached results are reused."""
        model = self.model(model_name, progress, cancel, use_gpu)
        batch_size = model.batch_size
        chunk_size = max(CHUNK, batch_size * 4)
        total = len(items)
        done = 0

        def prepare(item: Item):
            try:
                data = item.path.read_bytes()
                item.sha = sha256_bytes(data)
                item.error = None
                rec = self.store.lookup_censored(item.sha)
                if rec is not None:
                    item.censored = True
                    item.scores = self.store.get_scores(rec.original_sha, model_name) or item.scores
                    return None
                item.censored = False
                cached = self.store.get_scores(item.sha, model_name)
                if cached is not None:
                    item.scores = cached
                    return None
                with Image.open(io.BytesIO(data)) as img:
                    return preprocess(img)
            except Exception as exc:  # unreadable / corrupt image
                item.error = f"{type(exc).__name__}: {exc}"
                return None

        # Decoding images is the slow part once inference runs on a GPU, so use every core.
        workers = max(2, min(16, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for start in range(0, total, chunk_size):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = items[start:start + chunk_size]
                arrays = list(pool.map(prepare, chunk))
                pending = [(it, arr) for it, arr in zip(chunk, arrays) if arr is not None]
                for b in range(0, len(pending), batch_size):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    batch = pending[b:b + batch_size]
                    for (it, _), scores in zip(batch, model.predict_batch([a for _, a in batch])):
                        it.scores = scores
                        self.store.put_scores(it.sha, model_name, scores)
                done += len(chunk)
                if progress:
                    progress(done, total, f"Checked {done} of {total} images")

    # --- exporting -----------------------------------------------------------
    def export_zips(self, items: list[Item], settings: Settings, dest: Path,
                    progress: Optional[ProgressFn] = None,
                    cancel: Optional[threading.Event] = None) -> ApplyResult:
        """Write one ``<Pack> (filtered).zip`` per pack into ``dest``.

        The source packs are never modified: flagged images are censored in memory
        while the zip is written, every other file is copied as-is.
        """
        result = ApplyResult()
        flagged: dict[Path, dict[Path, Item]] = {}
        for it in items:
            if it.will_censor(settings):
                flagged.setdefault(it.pack_root, {})[it.path] = it
        roots = sorted({it.pack_root for it in items} if settings.export_unchanged else flagged,
                       key=lambda r: r.name.lower())
        dest.mkdir(parents=True, exist_ok=True)

        for n, root in enumerate(roots, 1):
            files = [f for f in _walk_pack(root)]
            total = sum(_size(f) for f in files) or 1
            done = 0
            targets = flagged.get(root, {})
            out = _unique_path(dest / f"{_safe_name(root.name)} (filtered).zip")
            part = out.with_name(out.name + ".part")
            label = f"Packing {root.name} ({n} of {len(roots)})"
            try:
                with zipfile.ZipFile(part, "w", allowZip64=True) as zf:
                    for f in files:
                        if cancel is not None and cancel.is_set():
                            raise Cancelled()
                        arc = f"{root.name}/{f.relative_to(root).as_posix()}"
                        info = zipfile.ZipInfo.from_file(f, arc)
                        info.compress_type = _compression(f)
                        if f in targets:
                            try:
                                data = censor_bytes(f.read_bytes(), f, settings)
                            except Exception as exc:
                                # Never ship the uncensored original by accident.
                                result.errors.append(f"{f}: {exc} (left out of the zip)")
                                continue
                            info.file_size = len(data)
                            zf.writestr(info, data)
                            result.censored += 1
                        else:
                            with open(f, "rb") as src, zf.open(info, "w", force_zip64=_size(f) > 0x7FFF0000) as dst:
                                shutil.copyfileobj(src, dst, 1 << 20)
                        done += _size(f)
                        if progress:
                            progress(done, total, label)
                part.replace(out)
            except BaseException:
                part.unlink(missing_ok=True)
                raise
            result.output_roots.append(out)
        return result

    # --- editing in place (CLI) ------------------------------------------------
    def apply(self, items: list[Item], settings: Settings, progress: Optional[ProgressFn] = None,
              cancel: Optional[threading.Event] = None) -> ApplyResult:
        """Censor flagged images inside the packs themselves, backing up originals."""
        result = ApplyResult()
        targets = [it for it in items if it.will_censor(settings)]
        for i, it in enumerate(targets):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                new_sha = censor_file(it.path, settings, self.store)
                if new_sha:
                    result.censored += 1
                    it.censored, it.sha = True, new_sha
                else:
                    result.skipped += 1
            except Exception as exc:
                result.errors.append(f"{it.path}: {exc}")
            if progress:
                progress(i + 1, len(targets), f"Censored {i + 1} of {len(targets)} images")
        return result

    def restore(self, items: list[Item], progress: Optional[ProgressFn] = None,
                cancel: Optional[threading.Event] = None) -> ApplyResult:
        result = ApplyResult()
        targets = [it for it in items if it.censored]
        for i, it in enumerate(targets):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                rec = self.store.lookup_censored(it.sha)
                if self.store.restore(it.path, it.sha):
                    it.censored = False
                    it.sha = rec.original_sha if rec else ""
                    it.override = None
                    result.restored += 1
                else:
                    result.errors.append(f"{it.path}: original backup not found")
            except Exception as exc:
                result.errors.append(f"{it.path}: {exc}")
            if progress:
                progress(i + 1, len(targets), f"Restored {i + 1} of {len(targets)} images")
        return result
