"""GUI entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .. import APP_NAME
from ..paths import bundled_assets_dir
from . import theme


def apply_theme(app: QApplication) -> None:
    t = theme.current()
    app.setPalette(theme.palette(t))
    app.setStyleSheet(theme.stylesheet(t))


def self_test(app: QApplication) -> int:
    """Smoke test for packaged builds: window, Qt plugins and the bundled model all load."""
    import io

    from PIL import Image

    from ..censor import censor_image
    from ..model import DEFAULT_MODEL, RatingModel, find_model
    from ..policy import Settings
    from .main_window import MainWindow
    from .settings_panel import sample_art

    win = MainWindow()
    win.show()
    app.processEvents()
    model_dir = find_model(DEFAULT_MODEL)
    print("model:", model_dir)
    if model_dir is None:
        return 1
    import onnxruntime
    providers = onnxruntime.get_available_providers()
    print("onnxruntime:", onnxruntime.__version__, providers)
    if sys.platform == "win32" and "DmlExecutionProvider" not in providers:
        print("DirectML is missing from this build")
        return 1
    model = RatingModel(DEFAULT_MODEL, model_dir, use_gpu=True)
    print("device:", model.device, f"({model.gpu_note})" if model.gpu_note else "")
    scores = model.predict(sample_art())
    print("scores:", {k: round(v, 3) for k, v in scores.items()})
    buf = io.BytesIO()
    censor_image(sample_art(), Settings()).save(buf, "PNG")
    Image.open(buf).verify()
    out = os.environ.get("PACKFILTER_SELFTEST_SHOT")
    if out:
        win.grab().save(out)
    win.close()
    print("self-test ok")
    return 0


def main() -> int:
    if "--self-test" in sys.argv and not os.environ.get("QT_QPA_PLATFORM"):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PackFilter")
    app.setStyle("Fusion")
    icon = bundled_assets_dir() / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    theme.capture_system_accent()
    apply_theme(app)
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: apply_theme(app))

    if "--self-test" in sys.argv:
        return self_test(app)

    from .main_window import MainWindow
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    for arg in sys.argv[1:]:  # allow "packfilter /path/to/Songs" (and files dropped on the icon)
        from pathlib import Path
        p = Path(arg)
        if p.is_dir():
            win.add_paths([p])
        elif p.suffix.lower() == ".zip" and p.is_file():
            win.add_zips([p])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
