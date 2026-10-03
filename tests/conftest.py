import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep backups/settings/score cache out of the real user profile.

    Models are shared through a session-wide directory so they download only once.
    """
    monkeypatch.setenv("PACKFILTER_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PACKFILTER_MODELS_DIR", str(ROOT / ".pytest_cache" / "models"))
    yield


def make_image(path: Path, color=(200, 50, 50), size=(64, 32), mode="RGB", fmt=None):
    """A tinted noise image: dominated by ``color`` but with detail, like real art."""
    path.parent.mkdir(parents=True, exist_ok=True)
    noise = Image.effect_noise(size, 60).convert("RGB")
    img = Image.blend(Image.new("RGB", size, color), noise, 0.25).convert(mode)
    img.save(path, fmt)
    return path


def write_sm(song_dir: Path, name: str = None, ext: str = "sm", **tags):
    song_dir.mkdir(parents=True, exist_ok=True)
    body = "".join(f"#{k.upper()}:{v};\n" for k, v in tags.items())
    (song_dir / f"{name or song_dir.name}.{ext}").write_text(body + "#NOTES:\n0000\n;\n", encoding="utf-8")
