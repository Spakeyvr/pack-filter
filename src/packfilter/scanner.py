"""Find song packs, songs and the images they use.

Works with Etterna/StepMania (.sm/.ssc/.dwi), and has light support for other
rhythm games (osu!, Quaver, K-Shoot, BMS). Anything we can't parse still gets
every image in its folder scanned, so unknown formats are covered too.
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tga"}
CHART_EXTS = {".sm", ".ssc", ".dwi", ".sma", ".osu", ".qua", ".ksh", ".bms", ".bme", ".bml", ".pms"}

# Ignore our own stuff and OS junk.
SKIP_DIRS = {"__macosx", ".git", ".packfilter"}

CATEGORIES = ("jacket", "banner", "background", "cdtitle", "pack", "other")
CATEGORY_TITLES = {
    "jacket": "Jackets / covers",
    "banner": "Song banners",
    "background": "Backgrounds",
    "cdtitle": "CD titles",
    "pack": "Pack banners",
    "other": "Other images",
}

_SM_TAGS = {
    "BANNER": "banner",
    "BACKGROUND": "background",
    "JACKET": "jacket",
    "CDIMAGE": "jacket",
    "DISCIMAGE": "jacket",
    "CDTITLE": "cdtitle",
}
_SM_TAG_RE = re.compile(r"#([A-Z0-9]+)\s*:([^;]*);?", re.IGNORECASE)


@dataclass
class ImageEntry:
    path: Path
    pack: str
    song: str
    categories: set[str] = field(default_factory=set)

    @property
    def primary_category(self) -> str:
        for c in CATEGORIES:
            if c in self.categories:
                return c
        return "other"


@dataclass
class Pack:
    name: str
    root: Path
    song_count: int = 0
    images: list[ImageEntry] = field(default_factory=list)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp932", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _resolve(song_dir: Path, name: str) -> Optional[Path]:
    """Resolve a filename from a chart file, case-insensitively like the games do."""
    name = name.strip().strip('"').replace("\\", "/")
    if not name:
        return None
    # Look each segment up in the real directory listing, so a tag written as
    # "BN.PNG" maps to the actual "bn.png" on every OS (and on case-sensitive
    # Linux filesystems it is found at all).
    current = song_dir
    for part in Path(name).parts:
        if part in ("..", "."):
            current = current / part
            continue
        try:
            entries = list(current.iterdir())
        except OSError:
            return None
        want = _norm(part)
        match = next((p for p in entries if p.name == part), None) or \
            next((p for p in entries if _norm(p.name) == want), None)
        if match is None:
            return None
        current = match
    return current if current.is_file() else None


def _guess_category(path: Path) -> str:
    stem = path.stem.lower()
    if re.search(r"(^|[^a-z])(jacket|jk|cover|cd)([^a-z]|$)", stem) or stem.endswith("-jacket"):
        return "jacket"
    if "cdtitle" in stem:
        return "cdtitle"
    if re.search(r"(^|[^a-z])(bn|banner)([^a-z]|$)", stem) or stem.endswith("bn"):
        return "banner"
    if re.search(r"(^|[^a-z])(bg|background)([^a-z]|$)", stem) or stem.endswith("bg"):
        return "background"
    return "other"


def _parse_stepmania(chart: Path, song_dir: Path) -> tuple[Optional[str], dict[Path, set[str]]]:
    text = _read_text(chart)
    refs: dict[Path, set[str]] = {}
    title = None
    for match in _SM_TAG_RE.finditer(text):
        tag, value = match.group(1).upper(), match.group(2)
        if tag == "TITLE" and title is None and value.strip():
            title = value.strip()
        elif tag in _SM_TAGS:
            p = _resolve(song_dir, value)
            if p is not None and p.suffix.lower() in IMAGE_EXTS:
                refs.setdefault(p, set()).add(_SM_TAGS[tag])
        elif tag.startswith("BGCHANGES") or tag in ("FGCHANGES", "BGCHANGES2"):
            for change in value.split(","):
                parts = change.split("=")
                if len(parts) >= 2:
                    p = _resolve(song_dir, parts[1])
                    if p is not None and p.suffix.lower() in IMAGE_EXTS:
                        refs.setdefault(p, set()).add("background")
    return title, refs


def _parse_osu(chart: Path, song_dir: Path) -> tuple[Optional[str], dict[Path, set[str]]]:
    text = _read_text(chart)
    refs: dict[Path, set[str]] = {}
    title = None
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section == "[Metadata]" and line.startswith("Title:") and title is None:
            title = line[6:].strip()
        elif section == "[Events]" and line[:2] in ("0,", "Ba"):
            fields = [f.strip() for f in line.split(",")]
            if len(fields) >= 3:
                p = _resolve(song_dir, fields[2])
                if p is not None and p.suffix.lower() in IMAGE_EXTS:
                    refs.setdefault(p, set()).add("background")
    return title, refs


def _parse_keyvalue(chart: Path, song_dir: Path, sep: str, keys: dict[str, str],
                    title_key: str) -> tuple[Optional[str], dict[Path, set[str]]]:
    """Quaver (.qua, YAML-ish ``Key: value``) and K-Shoot (.ksh, ``key=value``)."""
    text = _read_text(chart)
    refs: dict[Path, set[str]] = {}
    title = None
    for line in text.splitlines():
        if sep not in line:
            continue
        key, value = line.split(sep, 1)
        key = key.strip()
        if key == title_key and title is None:
            title = value.strip().strip("'\"")
        elif key in keys:
            p = _resolve(song_dir, value.strip().strip("'\""))
            if p is not None and p.suffix.lower() in IMAGE_EXTS:
                refs.setdefault(p, set()).add(keys[key])
    return title, refs


def _parse_bms(chart: Path, song_dir: Path) -> tuple[Optional[str], dict[Path, set[str]]]:
    text = _read_text(chart)
    refs: dict[Path, set[str]] = {}
    title = None
    keys = {"#BANNER": "banner", "#STAGEFILE": "jacket", "#BACKBMP": "background"}
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        key = parts[0].upper()
        if key == "#TITLE" and title is None:
            title = parts[1].strip()
        elif key in keys:
            p = _resolve(song_dir, parts[1])
            if p is not None and p.suffix.lower() in IMAGE_EXTS:
                refs.setdefault(p, set()).add(keys[key])
    return title, refs


def parse_chart(chart: Path, song_dir: Path) -> tuple[Optional[str], dict[Path, set[str]]]:
    ext = chart.suffix.lower()
    try:
        if ext in (".sm", ".ssc", ".dwi", ".sma"):
            return _parse_stepmania(chart, song_dir)
        if ext == ".osu":
            return _parse_osu(chart, song_dir)
        if ext == ".qua":
            return _parse_keyvalue(chart, song_dir, ":", {"BackgroundFile": "background",
                                                          "BannerFile": "banner"}, "Title")
        if ext == ".ksh":
            return _parse_keyvalue(chart, song_dir, "=", {"jacket": "jacket", "bg": "background"}, "title")
        if ext in (".bms", ".bme", ".bml", ".pms"):
            return _parse_bms(chart, song_dir)
    except OSError:
        pass
    return None, {}


def _walk_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith("._")]
        for f in filenames:
            if not f.startswith("._"):
                yield Path(dirpath) / f


def find_song_dirs(root: Path) -> list[Path]:
    """Every directory that directly contains a chart file."""
    songs = set()
    for f in _walk_files(root):
        if f.suffix.lower() in CHART_EXTS:
            songs.add(f.parent)
    return sorted(songs)


def _is_image(p: Path) -> bool:
    return p.suffix.lower() in IMAGE_EXTS


def scan_song(song_dir: Path, pack_name: str) -> list[ImageEntry]:
    refs: dict[Path, set[str]] = {}
    title = None
    try:
        charts = sorted(p for p in song_dir.iterdir() if p.is_file() and p.suffix.lower() in CHART_EXTS)
    except OSError:
        return []
    # .ssc is preferred by Etterna over .sm, so parse it first for the title.
    charts.sort(key=lambda p: (p.suffix.lower() != ".ssc", p.name))
    for chart in charts:
        t, r = parse_chart(chart, song_dir)
        title = title or t
        for path, cats in r.items():
            refs.setdefault(path, set()).update(cats)
    song_name = title or song_dir.name
    # Every image in the song folder is collected; unreferenced ones get a category
    # guessed from the filename (this is how the game finds them when tags are empty).
    for f in _walk_files(song_dir):
        if _is_image(f) and f not in refs:
            refs[f] = {_guess_category(f)}
    return [ImageEntry(path=p, pack=pack_name, song=song_name, categories=c) for p, c in sorted(refs.items())]


def scan_path(root: Path) -> list[Pack]:
    """Turn a user-supplied folder into one or more packs.

    ``root`` may be a Songs folder (many packs), a single pack, a single song,
    or any folder of images from a game we don't know about.
    """
    root = root.resolve()
    song_dirs = find_song_dirs(root)
    if not song_dirs:
        pack = Pack(name=root.name, root=root)
        pack.images = [ImageEntry(p, root.name, p.parent.name, {_guess_category(p)})
                       for p in sorted(_walk_files(root)) if _is_image(p)]
        return [pack] if pack.images else []

    # Group songs by pack. A pack is the folder directly above a song folder,
    # unless the user handed us a single song.
    groups: dict[Path, list[Path]] = {}
    for song in song_dirs:
        pack_root = root if song == root else song.parent
        groups.setdefault(pack_root, []).append(song)

    packs = []
    for pack_root, songs in sorted(groups.items()):
        pack = Pack(name=pack_root.name, root=pack_root, song_count=len(songs))
        seen: dict[Path, ImageEntry] = {}
        for song in songs:
            for entry in scan_song(song, pack.name):
                if entry.path in seen:
                    seen[entry.path].categories.update(entry.categories)
                else:
                    seen[entry.path] = entry
        if pack_root != root or root not in songs:
            # Images sitting directly in the pack folder are the pack's banner.
            try:
                for f in sorted(pack_root.iterdir()):
                    if f.is_file() and _is_image(f) and f not in seen and not f.name.startswith("._"):
                        seen[f] = ImageEntry(f, pack.name, "(pack banner)", {"pack"})
            except OSError:
                pass
        pack.images = list(seen.values())
        packs.append(pack)
    return packs
