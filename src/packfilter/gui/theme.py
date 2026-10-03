"""Colors and the Qt stylesheet. Follows the OS light/dark setting."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


@dataclass(frozen=True)
class Theme:
    dark: bool
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_dim: str
    accent: str
    accent_text: str
    danger: str
    ok: str
    warn: str
    muted: str


LIGHT = Theme(False, bg="#f4f4f7", surface="#ffffff", surface_alt="#ececf2", border="#d9d9e3",
              text="#1c1c24", text_dim="#6b6b7b", accent="#6d4aff", accent_text="#ffffff",
              danger="#d93f4c", ok="#24935f", warn="#c27c0e", muted="#8a8a99")
DARK = Theme(True, bg="#141418", surface="#1d1d23", surface_alt="#26262e", border="#33333d",
             text="#ececf1", text_dim="#9a9aab", accent="#8c72ff", accent_text="#ffffff",
             danger="#f2555a", ok="#3dbb7f", warn="#e6a23c", muted="#77778a")


def system_is_dark() -> bool:
    forced = os.environ.get("PACKFILTER_THEME", "").lower()
    if forced in ("dark", "light"):
        return forced == "dark"
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):
        return hints.colorScheme() == Qt.ColorScheme.Dark
    return QGuiApplication.palette().color(QPalette.Window).lightness() < 128


def current() -> Theme:
    return DARK if system_is_dark() else LIGHT


def palette(t: Theme) -> QPalette:
    p = QPalette()
    c = QColor
    p.setColor(QPalette.Window, c(t.bg))
    p.setColor(QPalette.WindowText, c(t.text))
    p.setColor(QPalette.Base, c(t.surface))
    p.setColor(QPalette.AlternateBase, c(t.surface_alt))
    p.setColor(QPalette.Text, c(t.text))
    p.setColor(QPalette.Button, c(t.surface))
    p.setColor(QPalette.ButtonText, c(t.text))
    p.setColor(QPalette.Highlight, c(t.accent))
    p.setColor(QPalette.HighlightedText, c(t.accent_text))
    p.setColor(QPalette.ToolTipBase, c(t.surface))
    p.setColor(QPalette.ToolTipText, c(t.text))
    p.setColor(QPalette.PlaceholderText, c(t.text_dim))
    p.setColor(QPalette.Link, c(t.accent))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t.muted))
    return p


def stylesheet(t: Theme) -> str:
    return f"""
    QWidget {{ font-size: 13px; }}
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}

    #Sidebar, #SettingsPanel, #DetailPanel {{ background: {t.surface}; border: 1px solid {t.border};
        border-radius: 10px; }}
    #SettingsScroll {{ background: transparent; border: none; }}
    #SettingsScroll > QWidget > QWidget {{ background: transparent; }}
    #SectionTitle {{ font-size: 11px; font-weight: 700; color: {t.text_dim}; letter-spacing: 1px; }}
    #PanelTitle {{ font-size: 15px; font-weight: 700; }}
    #Hint {{ color: {t.text_dim}; font-size: 12px; }}
    #Big {{ font-size: 20px; font-weight: 700; }}

    QPushButton {{ background: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 7px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {t.accent}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled {{ color: {t.muted}; background: {t.surface}; border-color: {t.surface_alt}; }}
    QPushButton:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QPushButton#Primary {{ background: {t.accent}; color: {t.accent_text}; border: none; font-weight: 600;
        padding: 8px 16px; }}
    QPushButton#Primary:hover {{ background: {QColorLighter(t.accent)}; }}
    QPushButton#Primary:disabled {{ background: {t.surface_alt}; color: {t.muted}; }}
    QPushButton#Danger {{ color: {t.danger}; }}
    QPushButton#Flat {{ background: transparent; border: none; color: {t.accent}; padding: 2px 4px; }}
    QPushButton#Flat:hover {{ text-decoration: underline; }}

    QToolButton {{ background: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border};
        border-radius: 7px; padding: 6px 12px; }}
    QToolButton:hover {{ border-color: {t.accent}; }}
    QToolButton::menu-indicator {{ image: none; }}

    #PresetCard {{ background: {t.surface_alt}; border: 1px solid {t.border}; border-radius: 8px; }}
    #PresetCard[selected="true"] {{ border: 2px solid {t.accent}; }}
    #PresetCard QLabel {{ background: transparent; }}

    QLineEdit, QComboBox, QSpinBox {{ background: {t.surface_alt}; border: 1px solid {t.border};
        border-radius: 6px; padding: 5px 8px; color: {t.text}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {t.accent}; }}
    QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border};
        selection-background-color: {t.accent}; }}

    QListView, QListWidget {{ background: transparent; border: none; outline: 0; }}
    QListWidget::item {{ padding: 8px; border-radius: 6px; margin: 1px 4px; }}
    QListWidget::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QListWidget::item:hover:!selected {{ background: {t.surface_alt}; }}

    QTabBar::tab {{ background: transparent; color: {t.text_dim}; padding: 7px 12px; border: none;
        border-bottom: 2px solid transparent; font-weight: 600; }}
    QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; }}
    QTabBar::tab:hover {{ color: {t.text}; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.surface}; border: 2px solid {t.accent}; width: 14px;
        height: 14px; margin: -7px 0; border-radius: 9px; }}

    QProgressBar {{ background: {t.surface_alt}; border: none; border-radius: 4px; height: 8px;
        text-align: center; color: transparent; }}
    QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 30px; }}

    QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; }}
    QStatusBar QLabel {{ color: {t.text_dim}; }}
    QSplitter::handle {{ background: transparent; }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    #DropZone {{ border: 2px dashed {t.border}; border-radius: 14px; background: {t.surface}; }}
    #DropZone[hover="true"] {{ border-color: {t.accent}; }}
    """


def QColorLighter(hex_: str) -> str:
    return QColor(hex_).lighter(112).name()
