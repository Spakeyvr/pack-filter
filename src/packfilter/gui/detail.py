"""Panel under the grid describing the selected image(s), with manual override buttons."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ..engine import Item
from ..model import LABELS
from ..policy import Settings
from ..scanner import CATEGORY_TITLES
from . import theme
from .results import RATING_NAMES, item_state, should_hide_preview


def fixed(button: QPushButton) -> QPushButton:
    """Never squeeze a button below the size its label needs."""
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return button


class Preview(QWidget):
    """Thumbnail that keeps a 16:9 box sized from the font, so it scales with the UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: Optional[QPixmap] = None
        self._text = ""
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        h = QFontMetrics(self.font()).height() * 7
        return QSize(round(h * 16 / 9), h)

    def set_pixmap(self, pm: Optional[QPixmap], text: str = "") -> None:
        self._pix, self._text = pm, text
        self.update()

    def paintEvent(self, e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.fillPath(path, QColor(t.bg))
        p.setClipPath(path)
        if self._pix is not None:
            s = self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        if self._text:
            p.setPen(QColor(255, 255, 255, 230) if self._pix else QColor(t.text_dim))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._text)
        p.setClipping(False)
        p.setPen(QColor(t.border))
        p.drawPath(path)


class DetailPanel(QFrame):
    override = Signal(object)   # None / True / False for the selected items
    restore = Signal()

    def __init__(self, thumbs, settings_fn, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.thumbs = thumbs
        self.settings_fn = settings_fn
        self.items: list[Item] = []
        self.revealed = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(4)
        self.preview = Preview()
        left.addWidget(self.preview)
        self.reveal_btn = fixed(QPushButton("Show original"))
        self.reveal_btn.setObjectName("Link")
        self.reveal_btn.clicked.connect(self._toggle_reveal)
        left.addWidget(self.reveal_btn, 0, Qt.AlignHCenter)
        left.addStretch(1)
        lay.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("Section")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("Hint")
        self.sub.setWordWrap(True)
        right.addWidget(self.sub)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        self.verdict.setTextFormat(Qt.RichText)
        right.addWidget(self.verdict)
        self.scores = QLabel()
        self.scores.setObjectName("Hint")
        self.scores.setWordWrap(True)
        right.addWidget(self.scores)
        right.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.auto_btn = fixed(QPushButton("Auto"))
        self.auto_btn.setToolTip("Let the detector decide")
        self.force_btn = fixed(QPushButton("Censor"))
        self.force_btn.setToolTip("Always censor")
        self.keep_btn = fixed(QPushButton("Keep"))
        self.keep_btn.setToolTip("Never censor")
        group = QButtonGroup(self)
        for b, val in ((self.auto_btn, None), (self.force_btn, True), (self.keep_btn, False)):
            b.setCheckable(True)
            group.addButton(b)
            b.clicked.connect(lambda _=False, v=val: self.override.emit(v))
            btns.addWidget(b)
        self.restore_btn = fixed(QPushButton("Restore original"))
        self.restore_btn.clicked.connect(self.restore.emit)
        btns.addWidget(self.restore_btn)
        btns.addStretch(1)
        self.folder_btn = fixed(QPushButton("Open folder"))
        self.folder_btn.setObjectName("Link")
        self.folder_btn.clicked.connect(self._open_folder)
        btns.addWidget(self.folder_btn)
        right.addLayout(btns)

        # Wrapped labels would otherwise let this column shrink until text overlaps. Giving the
        # labels (not the column) a minimum keeps the button row's own minimum in charge too.
        min_text = QFontMetrics(self.font()).averageCharWidth() * 30
        for lbl in (self.title, self.sub, self.verdict, self.scores):
            lbl.setMinimumWidth(min_text)
        lay.addLayout(right, 1)
        self.set_items([])

    def _toggle_reveal(self) -> None:
        self.revealed = not self.revealed
        self.refresh()

    def _open_folder(self) -> None:
        if len(self.items) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.items[0].path.parent)))

    def set_items(self, items: list[Item]) -> None:
        if [id(i) for i in items] != [id(i) for i in self.items]:
            self.revealed = False
        self.items = items
        self.refresh()

    def refresh(self) -> None:
        t = theme.current()
        s: Settings = self.settings_fn()
        items = self.items
        for w in (self.auto_btn, self.force_btn, self.keep_btn):
            w.setEnabled(bool(items) and any(not i.censored for i in items))
        self.restore_btn.setVisible(any(i.censored for i in items))
        self.folder_btn.setVisible(len(items) == 1)
        self.reveal_btn.setVisible(False)
        self.scores.setVisible(False)

        if not items:
            self.title.setText("Nothing selected")
            self.sub.setText("Click a cover to see how it was rated. Select several to change them all at once.")
            self.verdict.setText("")
            self.preview.set_pixmap(None, "")
            for b in (self.auto_btn, self.force_btn, self.keep_btn):
                b.setChecked(False)
            return

        overrides = {i.override for i in items}
        self.auto_btn.setChecked(overrides == {None})
        self.force_btn.setChecked(overrides == {True})
        self.keep_btn.setChecked(overrides == {False})

        if len(items) > 1:
            n = sum(i.will_censor(s) for i in items)
            self.title.setText(f"{len(items)} images selected")
            self.sub.setText(f"{n} will be censored. The buttons below apply to all of them.")
            self.verdict.setText("")
            self.preview.set_pixmap(None, f"{len(items)} images")
            return

        it = items[0]
        self.title.setText(it.song)
        cats = ", ".join(CATEGORY_TITLES[c].rstrip("s") for c in sorted(it.categories))
        self.sub.setText(f"{it.pack}  ·  {cats}  ·  {it.path.name}")
        self.folder_btn.setToolTip(str(it.path))

        label, color_key = item_state(it, s)
        color = getattr(t, color_key)
        if it.error:
            why = f"This file couldn't be read ({it.error}). It will be left as it is."
        elif it.censored:
            why = "This image was censored earlier. The original is backed up."
        elif it.scores is None:
            why = "Still being checked..."
        elif it.override is not None:
            why = "Set manually."
        elif not it.categories & set(s.categories):
            why = "This kind of image is switched off under \"Which images\"."
        else:
            score = s.lewd_score(it.scores)
            level = {"sensitive": "Suggestive", "questionable": "Sexual", "explicit": "Explicit"}[s.min_level]
            side = "at or above" if score >= s.threshold else "below"
            why = (f"Lewdness {score * 100:.0f}% is {side} the {s.threshold * 100:.0f}% limit "
                   f"(counting {level} and up).")
        self.verdict.setText(f"<span style='color:{color}; font-weight:600'>{label}.</span> {why}")

        if it.scores:
            self.scores.setVisible(True)
            self.scores.setText("   ".join(f"{RATING_NAMES[k]} {it.scores.get(k, 0) * 100:.0f}%" for k in LABELS))

        pix = self.thumbs.get(it) if it.sha and not it.error else None
        if pix is None:
            self.preview.set_pixmap(None, "Unreadable image" if it.error else "Loading...")
            return
        hide = should_hide_preview(it, s)
        self.reveal_btn.setVisible(hide or self.revealed)
        self.reveal_btn.setText("Hide again" if self.revealed else "Show original")
        if hide and not self.revealed:
            self.preview.set_pixmap(pix[1], "Preview hidden")
        else:
            self.preview.set_pixmap(pix[0])
