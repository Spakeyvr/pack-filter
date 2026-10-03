"""Per-user data locations, following each platform's conventions."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    override = os.environ.get("PACKFILTER_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "PackFilter"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "PackFilter"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "packfilter"
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    override = os.environ.get("PACKFILTER_MODELS_DIR")
    base = Path(override) if override else data_dir() / "models"
    base.mkdir(parents=True, exist_ok=True)
    return base


def downloads_dir() -> Path:
    """The user's Downloads folder (falls back to home)."""
    home = Path.home()
    if sys.platform.startswith("linux"):
        try:
            import subprocess
            out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2)
            p = Path(out.stdout.strip())
            if out.returncode == 0 and p.is_dir() and p != home:
                return p
        except (OSError, subprocess.SubprocessError):
            pass
    d = home / "Downloads"
    return d if d.is_dir() else home


def work_dir() -> Path:
    """Scratch space for unpacking downloaded .zip packs before filtering them."""
    d = data_dir() / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_assets_dir() -> Path:
    """Assets shipped with the app (inside the PyInstaller bundle or the package)."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "packfilter" / "assets"
    return Path(__file__).resolve().parent / "assets"
