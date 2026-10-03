# PyInstaller spec - build with `python packaging/build.py` (it downloads the model first).
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"
ASSETS = SRC / "packfilter" / "assets"
APP = "Pack Filter"

datas = [(str(ASSETS), "packfilter/assets")]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    datas=datas,
    hiddenimports=["packfilter.cli", "packfilter.gui.app", "packfilter.gui.main_window"],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "cv2", "imgutils", "torch", "IPython",
              "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtOpenGL",
              "PySide6.QtSvg", "PySide6.QtDBus"],
    noarchive=False,
)
# Qt plugins we never use drag in QtQuick/QtQml/QtPdf (~25 MB). Drop them and their libraries.
_UNUSED = ("QtQuick", "QtQml", "QtPdf", "QtVirtualKeyboard", "Qt6Quick", "Qt6Qml", "Qt6Pdf",
           "Qt6VirtualKeyboard", "libqtvirtualkeyboardplugin", "libqpdf", "qpdf.dll", "qtvirtualkeyboardplugin",
           "libqtuiotouchplugin", "qtuiotouchplugin")
a.binaries = [b for b in a.binaries if not any(u in b[0] for u in _UNUSED)]
a.datas = [d for d in a.datas if not any(u in d[0] for u in _UNUSED)]

pyz = PYZ(a.pure)

icon = str(ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns"))
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="PackFilter" if sys.platform != "darwin" else APP,
    console=False,
    icon=icon if sys.platform != "linux" else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PackFilter", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP}.app",
        icon=icon,
        bundle_identifier="io.github.packfilter",
        info_plist={
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
