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


def bundled_assets_dir() -> Path:
    """Assets shipped with the app (inside the PyInstaller bundle or the package)."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root) / "packfilter" / "assets"
    return Path(__file__).resolve().parent / "assets"
