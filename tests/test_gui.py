"""Drive the real main window offscreen with a fake model."""

import os
import time

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


def test_scan_apply_restore_through_window(qapp, tmp_path, monkeypatch):
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
    assert win.apply_btn.text() == "Censor 3 images" and win.apply_btn.isEnabled()

    # Overriding a clean image adds it; filters and counts follow.
    win.tabs.setCurrentIndex(2)  # "Not censored"
    win.view.setCurrentIndex(win.model.index(0))
    win.set_override(True)
    assert win.apply_btn.text() == "Censor 4 images"

    win.apply()
    wait_idle(qapp, win)
    assert sum(it.censored for it in win.items) == 4
    assert win.apply_btn.text() == "Nothing to censor"
    assert win.tabs.tabText(3).endswith("4")

    win.restore_all()
    wait_idle(qapp, win)
    assert sum(it.censored for it in win.items) == 0
    win.close()
