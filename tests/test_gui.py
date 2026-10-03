"""Drive the real main window offscreen with a fake model."""

import os
import time
import zipfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from packfilter.gui.main_window import MainWindow  # noqa: E402

from conftest import make_image, write_sm  # noqa: E402
from test_engine import CLEAN, LEWD, FakeModel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def wait_idle(app, win, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if not win._busy() and not win._queue:
            for _ in range(5):
                app.processEvents()
            return
        time.sleep(0.02)
    raise TimeoutError("window stayed busy")


def test_scan_and_download_through_window(qapp, tmp_path, monkeypatch):
    QMB = QtWidgets.QMessageBox
    monkeypatch.setattr(QMB, "question", staticmethod(lambda *a, **k: QMB.Yes))
    monkeypatch.setattr(QMB, "exec", lambda self: 0)
    root = tmp_path / "Songs" / "Pack"
    for i in range(3):
        write_sm(root / f"Lewd {i}", banner="bn.png")
        make_image(root / f"Lewd {i}" / "bn.png", LEWD)
        write_sm(root / f"Clean {i}", banner="bn.png")
        make_image(root / f"Clean {i}" / "bn.png", CLEAN)

    win = MainWindow()
    win.engine.model = lambda *a, **k: FakeModel()
    win.show()
    win.add_paths([tmp_path / "Songs"])
    wait_idle(qapp, win)
    assert len(win.items) == 6
    assert win.apply_btn.text() == "Download 1 filtered pack" and win.apply_btn.isEnabled()
    assert sum(it.will_censor(win.settings) for it in win.items) == 3

    # Overriding a clean image adds it; filters and counts follow.
    win.tabs.setCurrentIndex(2)  # "Not censored"
    win.view.setCurrentIndex(win.model.index(0))
    win.set_override(True)
    assert sum(it.will_censor(win.settings) for it in win.items) == 4

    out = tmp_path / "Downloads"
    out.mkdir()
    win.settings.output_dir = str(out)
    win._update_counts()
    win.download()
    wait_idle(qapp, win)
    assert [z.name for z in out.iterdir()] == ["Pack (filtered).zip"]
    with zipfile.ZipFile(out / "Pack (filtered).zip") as zf:
        changed = [n for n in zf.namelist() if n.endswith("bn.png")
                   and zf.read(n) != (tmp_path / "Songs" / n).read_bytes()]
    assert len(changed) == 4  # 3 lewd + 1 manual override
    assert sum(it.censored for it in win.items) == 0  # source packs untouched
    win.close()


def test_zip_input_is_unpacked_to_temp_and_cleaned(qapp, tmp_path, monkeypatch):
    QMB = QtWidgets.QMessageBox
    monkeypatch.setattr(QMB, "exec", lambda self: 0)
    zpath = tmp_path / "Downloaded Pack.zip"
    src = tmp_path / "src" / "Downloaded Pack"
    write_sm(src / "Song", banner="bn.png")
    make_image(src / "Song" / "bn.png", LEWD)
    with zipfile.ZipFile(zpath, "w") as zf:
        for f in src.rglob("*"):
            zf.write(f, f.relative_to(src.parent).as_posix())
    win = MainWindow()
    win.engine.model = lambda *a, **k: FakeModel()
    win.settings.output_dir = str(tmp_path)
    win.add_zips([zpath])
    wait_idle(qapp, win)
    assert [it.pack for it in win.items] == ["Downloaded Pack"]
    win.download()
    wait_idle(qapp, win)
    assert (tmp_path / "Downloaded Pack (filtered).zip").exists()
    temp = win._temp_dirs[0]
    assert temp.exists()
    win.close()
    assert not temp.exists()
