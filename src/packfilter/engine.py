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

from .censor import censor_file
from .model import RatingModel, ensure_model, preprocess
from .policy import Settings
from .scanner import ImageEntry, Pack, scan_path
from .store import Store, sha256_bytes

ProgressFn = Callable[[int, int, str], None]  # (done, total, message)

CHUNK = 64
BATCH = 16


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
        self._model_lock = threading.Lock()

    # --- model ---------------------------------------------------------------
    def model(self, model_name: str, progress: Optional[ProgressFn] = None,
              cancel: Optional[threading.Event] = None) -> RatingModel:
        with self._model_lock:
            if self._model is None or self._model.model_name != model_name:
                def dl(done, total):
                    if progress:
                        progress(done, total, "Downloading the rating model (one time only)...")
                path = ensure_model(model_name, dl, cancel)
                self._model = RatingModel(model_name, path)
            return self._model

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
                 cancel: Optional[threading.Event] = None) -> None:
        """Fill in sha/scores/censored for every item. Cached results are reused."""
        model = self.model(model_name, progress, cancel)
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

        workers = max(2, min(8, (os.cpu_count() or 4)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for start in range(0, total, CHUNK):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = items[start:start + CHUNK]
                arrays = list(pool.map(prepare, chunk))
                pending = [(it, arr) for it, arr in zip(chunk, arrays) if arr is not None]
                for b in range(0, len(pending), BATCH):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    batch = pending[b:b + BATCH]
                    for (it, _), scores in zip(batch, model.predict_batch([a for _, a in batch])):
                        it.scores = scores
                        self.store.put_scores(it.sha, model_name, scores)
                done += len(chunk)
                if progress:
                    progress(done, total, f"Checked {done} of {total} images")

    # --- applying ------------------------------------------------------------
    def apply(self, items: list[Item], settings: Settings, progress: Optional[ProgressFn] = None,
              cancel: Optional[threading.Event] = None) -> ApplyResult:
        result = ApplyResult()
        targets = [it for it in items if it.will_censor(settings)]
        copy_map: dict[Path, Path] = {}
        if settings.output_mode == "copy":
            dest_root = Path(settings.copy_destination).expanduser()
            if not settings.copy_destination:
                raise ValueError("Choose a folder to save the censored packs to.")
            roots = sorted({it.pack_root for it in items})
            for i, root in enumerate(roots):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                if progress:
                    progress(i, len(roots), f"Copying pack {root.name}...")
                target = dest_root / root.name
                if target.resolve() == root.resolve():
                    raise ValueError("The output folder must be different from the pack's own folder.")
                shutil.copytree(root, target, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns("__MACOSX", "._*"))
                copy_map[root] = target
                result.output_roots.append(target)

        for i, it in enumerate(targets):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            path = it.path
            if copy_map:
                path = copy_map[it.pack_root] / it.path.relative_to(it.pack_root)
            try:
                if censor_file(path, settings, self.store):
                    result.censored += 1
                    if not copy_map:
                        it.censored = True
                else:
                    result.skipped += 1
            except Exception as exc:
                result.errors.append(f"{path}: {exc}")
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
