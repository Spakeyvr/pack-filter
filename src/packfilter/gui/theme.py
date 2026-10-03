"""Colors and the Qt stylesheet.

Deliberately plain: neutral greys, the operating system's own accent colour and
font, and no hard-coded font sizes, so the UI scales with the user's display
and text-size settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

FALLBACK_ACCENT = "#2f6fdf"
_system_accent: Optional[str] = None


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    panel: str
    field: str
    border: str
    text: str
    text_dim: str
    accent: str
    accent_text: str
    danger: str
    ok: str
    warn: str
    muted: str


LIGHT = Theme(False, bg="#f2f2f2", panel="#ffffff", field="#ffffff", border="#d0d0d0", text="#1e1e1e",
              text_dim="#666666", accent=FALLBACK_ACCENT, accent_text="#ffffff", danger="#c42b3c",
              ok="#2d7d34", warn="#a86400", muted="#9a9a9a")
DARK = Theme(True, bg="#1e1e1e", panel="#262626", field="#2e2e2e", border="#3c3c3c", text="#e4e4e4",
             text_dim="#9c9c9c", accent=FALLBACK_ACCENT, accent_text="#ffffff", danger="#ef5d6a",
             ok="#62b868", warn="#e0a13f", muted="#7a7a7a")


def capture_system_accent() -> None:
    """Remember the OS accent colour before our own palette replaces the platform one."""
    global _system_accent
    pal = QGuiApplication.palette()
    role = getattr(QPalette, "Accent", QPalette.Highlight)
    c = pal.color(role)
    _system_accent = c.name() if c.isValid() else None


def system_is_dark() -> bool:
    forced = os.environ.get("PACKFILTER_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme") and hints.colorScheme() != Qt.ColorScheme.Unknown:
        return hints.colorScheme() == Qt.ColorScheme.Dark
    return QGuiApplication.palette().color(QPalette.Window).lightness() < 128


def _readable_on(color: QColor) -> str:
    r, g, b = color.redF(), color.greenF(), color.blueF()
    return "#000000" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.6 else "#ffffff"


def current() -> Theme:
    base = DARK if system_is_dark() else LIGHT
    accent = QColor(_system_accent or FALLBACK_ACCENT)
    return replace(base, accent=accent.name(), accent_text=_readable_on(accent))


def palette(t: Theme) -> QPalette:
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t.bg))
    p.setColor(QPalette.WindowText, c(t.text))
    p.setColor(QPalette.Base, c(t.field))
    p.setColor(QPalette.AlternateBase, c(t.bg))
    p.setColor(QPalette.Text, c(t.text))
    p.setColor(QPalette.Button, c(t.field))
    p.setColor(QPalette.ButtonText, c(t.text))
    p.setColor(QPalette.Highlight, c(t.accent))
    p.setColor(QPalette.HighlightedText, c(t.accent_text))
    p.setColor(QPalette.ToolTipBase, c(t.panel))
    p.setColor(QPalette.ToolTipText, c(t.text))
    p.setColor(QPalette.PlaceholderText, c(t.text_dim))
    p.setColor(QPalette.Link, c(t.accent))
    # Fusion draws bevels, groove and frames from these.
    for role, col in ((QPalette.Light, t.panel), (QPalette.Midlight, t.field), (QPalette.Mid, t.border),
                      (QPalette.Dark, t.border), (QPalette.Shadow, t.border)):
        p.setColor(role, c(col))
    if hasattr(QPalette, "Accent"):
        p.setColor(QPalette.Accent, c(t.accent))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t.muted))
    return p


def stylesheet(t: Theme) -> str:
    # No font sizes here on purpose: everything follows the system font.
    return f"""
    QToolTip {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}

    #Panel {{ background: {t.panel}; border: 1px solid {t.border}; border-radius: 6px; }}
    #SettingsScroll {{ background: transparent; border: none; }}
    #SettingsScroll > QWidget > QWidget {{ background: transparent; }}
    #Section {{ font-weight: 600; }}
    #Hint {{ color: {t.text_dim}; }}

    QPushButton {{ background: {t.field}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 5px; padding: 4px 12px; }}
    QPushButton:hover {{ border-color: {t.text_dim}; }}
    QPushButton:pressed {{ background: {t.bg}; }}
    QPushButton:disabled {{ color: {t.muted}; border-color: {t.border}; }}
    QPushButton:checked {{ background: {t.bg}; border-color: {t.text_dim}; font-weight: 600; }}
    QPushButton#Primary {{ background: {t.accent}; color: {t.accent_text}; border: 1px solid {t.accent}; }}
    QPushButton#Primary:hover {{ border-color: {t.text}; }}
    QPushButton#Primary:disabled {{ background: {t.field}; color: {t.muted}; border-color: {t.border}; }}
    QPushButton#Link {{ background: transparent; border: none; color: {t.accent}; padding: 2px 2px; }}
    QPushButton#Link:hover {{ text-decoration: underline; }}

    QToolButton {{ background: {t.field}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 5px; padding: 4px 12px; }}
    QToolButton:hover {{ border-color: {t.text_dim}; }}
    QToolButton::menu-indicator {{ image: none; }}

    QLineEdit, QComboBox {{ background: {t.field}; border: 1px solid {t.border}; border-radius: 5px;
        padding: 3px 6px; color: {t.text}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QComboBox QAbstractItemView {{ background: {t.panel}; border: 1px solid {t.border}; }}

    QListView, QListWidget {{ background: transparent; border: none; outline: 0; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 4px; margin: 0 4px; }}
    QListWidget::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QListWidget::item:hover:!selected {{ background: {t.bg}; }}

    QTabBar::tab {{ background: transparent; color: {t.text_dim}; padding: 6px 10px; border: none;
        border-bottom: 2px solid transparent; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    QTabBar::tab:hover {{ color: {t.text}; }}

    QProgressBar {{ background: {t.field}; border: 1px solid {t.border}; border-radius: 3px;
        text-align: center; color: transparent; max-height: 8px; }}
    QProgressBar::chunk {{ background: {t.accent}; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.field}; border: 1px solid {t.text_dim}; width: 14px;
        margin: -6px 0; border-radius: 7px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 24px; margin: 1px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 24px; margin: 1px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    QStatusBar {{ background: {t.bg}; border-top: 1px solid {t.border}; }}
    QStatusBar QLabel {{ color: {t.text_dim}; }}
    QSplitter::handle {{ background: transparent; }}
    #DropZone {{ border: 1px dashed {t.text_dim}; border-radius: 6px; background: {t.panel}; }}
    #DropZone[hover="true"] {{ border: 2px solid {t.accent}; }}
    """
