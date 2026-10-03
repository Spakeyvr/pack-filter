"""Build a standalone app for the current OS.

    python packaging/build.py

Output goes to dist/: a .dmg + .zip on macOS, a .zip on Windows, a .tar.gz on Linux.
The default rating model is bundled so the app works offline from the first run.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from packfilter import __version__  # noqa: E402
from packfilter.model import DEFAULT_MODEL, ensure_model  # noqa: E402


def bundle_model() -> None:
    src = ensure_model(DEFAULT_MODEL, lambda d, t: print(f"\rmodel {d / max(t, 1):.0%}", end=""))
    dest = ROOT / "src" / "packfilter" / "assets" / "models" / DEFAULT_MODEL
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("model.onnx", "meta.json"):
        if src.resolve() != dest.resolve():
            shutil.copy2(src / name, dest / name)
    print(f"\nbundled model -> {dest}")


def make_dmg(src: Path, dmg: Path, attempts: int = 5) -> None:
    """hdiutil intermittently fails with "Resource busy" on CI Macs; retry with a pause."""
    for i in range(1, attempts + 1):
        try:
            subprocess.check_call(["hdiutil", "create", "-volname", "Pack Filter", "-srcfolder", str(src),
                                   "-ov", "-format", "UDZO", str(dmg)])
            return
        except subprocess.CalledProcessError:
            if i == attempts:
                raise
            print(f"hdiutil failed (attempt {i}/{attempts}), retrying...")
            time.sleep(5 * i)


def arch() -> str:
    m = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64"}.get(m, m)


def main() -> int:
    bundle_model()
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                           "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"),
                           str(ROOT / "packaging" / "packfilter.spec")])
    dist = ROOT / "dist"
    if sys.platform == "darwin":
        name = f"PackFilter-{__version__}-macos-{arch()}"
        app = dist / "Pack Filter.app"
        shutil.rmtree(dist / "PackFilter", ignore_errors=True)  # the .app is what we ship
        zip_base = dist / name
        subprocess.check_call(["ditto", "-c", "-k", "--keepParent", str(app), f"{zip_base}.zip"])
        dmg = dist / f"{name}.dmg"
        dmg.unlink(missing_ok=True)
        staging = dist / "dmg"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        subprocess.check_call(["ditto", str(app), str(staging / app.name)])
        (staging / "Applications").symlink_to("/Applications")
        make_dmg(staging, dmg)
        shutil.rmtree(staging)
        print(f"built {dmg} and {zip_base}.zip")
    elif sys.platform == "win32":
        name = f"PackFilter-{__version__}-windows-{arch()}"
        shutil.make_archive(str(dist / name), "zip", dist, "PackFilter")
        print(f"built {dist / name}.zip")
    else:
        name = f"PackFilter-{__version__}-linux-{arch()}"
        shutil.copy2(ROOT / "packaging" / "linux" / "install.sh", dist / "PackFilter" / "install.sh")
        shutil.copy2(ROOT / "packaging" / "icon-256.png", dist / "PackFilter" / "packfilter.png")
        with tarfile.open(dist / f"{name}.tar.gz", "w:gz") as tf:
            tf.add(dist / "PackFilter", arcname="PackFilter")
        print(f"built {dist / name}.tar.gz")
    return 0


if __name__ == "__main__":
    sys.exit(main())
