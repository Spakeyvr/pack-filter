"""GUI entry point."""

from __future__ import annotations

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


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PackFilter")
    app.setStyle("Fusion")
    icon = bundled_assets_dir() / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    apply_theme(app)
    hints = app.styleHints()
    if hasattr(hints, "colorSchemeChanged"):
        hints.colorSchemeChanged.connect(lambda *_: apply_theme(app))

    from .main_window import MainWindow
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    for arg in sys.argv[1:]:  # allow "packfilter /path/to/Songs"
        from pathlib import Path
        p = Path(arg)
        if p.is_dir():
            win.add_paths([p])
        elif p.suffix.lower() == ".zip" and p.is_file():
            win.add_zips([p])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
