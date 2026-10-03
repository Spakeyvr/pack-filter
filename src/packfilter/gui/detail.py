"""Bottom panel describing the selected image(s), with manual override buttons."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..engine import Item
from ..model import LABELS
from ..policy import Settings
from ..scanner import CATEGORY_TITLES
from . import theme
from .results import RATING_NAMES, item_state, should_hide_preview


class ScoreBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.value = 0.0
        self.color = QColor("#888")
        self.setFixedHeight(8)
        self.setMinimumWidth(80)

    def set(self, value: float, color: str) -> None:
        self.value, self.color = value, QColor(color)
        self.update()

    def paintEvent(self, e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        bg = QPainterPath()
        bg.addRoundedRect(r, 4, 4)
        p.fillPath(bg, QColor(t.surface_alt))
        fg = QPainterPath()
        fg.addRoundedRect(QRectF(r.x(), r.y(), r.width() * max(0.0, min(1.0, self.value)), r.height()), 4, 4)
        p.fillPath(fg, self.color)


class Preview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(QSize(240, 135))
        self.setAlignment(Qt.AlignCenter)
        self._pix: Optional[QPixmap] = None

    def set_pixmap(self, pm: Optional[QPixmap], text: str = "") -> None:
        self._pix = pm
        self.setText(text)
        self.update()

    def paintEvent(self, e):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 8, 8)
        p.fillPath(path, QColor(t.surface_alt))
        p.setClipPath(path)
        if self._pix is not None:
            s = self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.width() - s.width()) // 2, (self.height() - s.height()) // 2, s)
        if self.text():
            p.setPen(QColor(255, 255, 255, 230) if self._pix else QColor(t.text_dim))
            p.drawText(self.rect(), Qt.AlignCenter, self.text())


class DetailPanel(QFrame):
    override = Signal(object)   # None / True / False for the selected items
    restore = Signal()
    reveal_toggled = Signal()

    def __init__(self, thumbs, settings_fn, parent=None):
        super().__init__(parent)
        self.setObjectName("DetailPanel")
        self.thumbs = thumbs
        self.settings_fn = settings_fn
        self.items: list[Item] = []
        self.revealed = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(16)
        left = QVBoxLayout()
        self.preview = Preview()
        left.addWidget(self.preview)
        self.reveal_btn = QPushButton("Show original")
        self.reveal_btn.setObjectName("Flat")
        self.reveal_btn.clicked.connect(self._toggle_reveal)
        left.addWidget(self.reveal_btn, 0, Qt.AlignHCenter)
        lay.addLayout(left)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("PanelTitle")
        self.title.setWordWrap(True)
        mid.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("Hint")
        self.sub.setWordWrap(True)
        mid.addWidget(self.sub)
        self.path_btn = QPushButton()
        self.path_btn.setObjectName("Flat")
        self.path_btn.setCursor(Qt.PointingHandCursor)
        self.path_btn.setStyleSheet("text-align: left;")
        self.path_btn.clicked.connect(self._open_folder)
        mid.addWidget(self.path_btn, 0, Qt.AlignLeft)
        self.verdict = QLabel()
        self.verdict.setWordWrap(True)
        mid.addWidget(self.verdict)
        mid.addStretch(1)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addWidget(QLabel("Decide:"))
        self.auto_btn = QPushButton("Auto")
        self.auto_btn.setToolTip("Let the detector decide")
        self.force_btn = QPushButton("Censor")
        self.force_btn.setToolTip("Always censor this image")
        self.keep_btn = QPushButton("Keep")
        self.keep_btn.setToolTip("Never censor this image")
        group = QButtonGroup(self)
        for b, val in ((self.auto_btn, None), (self.force_btn, True), (self.keep_btn, False)):
            b.setCheckable(True)
            group.addButton(b)
            b.clicked.connect(lambda _=False, v=val: self.override.emit(v))
            btns.addWidget(b)
        self.restore_btn = QPushButton("Restore")
        self.restore_btn.setToolTip("Put the original image back")
        self.restore_btn.clicked.connect(self.restore.emit)
        btns.addWidget(self.restore_btn)
        btns.addStretch(1)
        mid.addLayout(btns)
        lay.addLayout(mid, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        self.bars: dict[str, tuple[ScoreBar, QLabel]] = {}
        for row, label in enumerate(LABELS):
            grid.addWidget(QLabel(RATING_NAMES[label]), row, 0)
            bar = ScoreBar()
            grid.addWidget(bar, row, 1)
            pct = QLabel()
            pct.setObjectName("Hint")
            pct.setMinimumWidth(36)
            pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(pct, row, 2)
            self.bars[label] = (bar, pct)
        box = QWidget()
        box.setLayout(grid)
        box.setFixedWidth(220)
        lay.addWidget(box, 0, Qt.AlignTop)
        self.score_box = box
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
        has = bool(items)
        for w in (self.auto_btn, self.force_btn, self.keep_btn):
            w.setEnabled(has and any(not i.censored for i in items))
        self.restore_btn.setVisible(any(i.censored for i in items))
        self.score_box.setVisible(len(items) == 1 and items[0].scores is not None)
        self.path_btn.setVisible(len(items) == 1)
        self.reveal_btn.setVisible(False)

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
            n_cens = sum(i.will_censor(s) for i in items)
            self.title.setText(f"{len(items)} images selected")
            self.sub.setText(f"{n_cens} will be censored. Use the buttons to override all of them at once.")
            self.verdict.setText("")
            self.preview.set_pixmap(None, f"{len(items)} images")
            return

        it = items[0]
        self.title.setText(it.song)
        cats = ", ".join(CATEGORY_TITLES[c].rstrip("s") for c in sorted(it.categories))
        self.sub.setText(f"{it.pack}  ·  {cats}")
        self.path_btn.setText(it.path.name + "  (open folder)")
        self.path_btn.setToolTip(str(it.path))

        label, color_key = item_state(it, s)
        color = getattr(t, color_key)
        if it.error:
            why = f"This file couldn't be read ({it.error}). It will be left alone."
        elif it.censored:
            why = "This image has already been censored. The original is backed up."
        elif it.scores is None:
            why = "Still being checked..."
        elif it.override is not None:
            why = "You set this manually."
        else:
            score = s.lewd_score(it.scores)
            cats_on = bool(it.categories & set(s.categories))
            if not cats_on:
                why = "This kind of image is switched off under \"Which images\"."
            else:
                level = {"sensitive": "Suggestive", "questionable": "Sexual", "explicit": "Explicit"}[s.min_level]
                side = "at or above" if score >= s.threshold else "below"
                why = (f"Lewdness {score * 100:.0f}% is {side} your {s.threshold * 100:.0f}% limit "
                       f"(counting {level} and up).")
        self.verdict.setText(f"<b style='color:{color}'>{label}</b> &nbsp;<span style='color:{t.text_dim}'>"
                             f"{why}</span>")

        if it.scores:
            colors = {"general": t.ok, "sensitive": t.warn, "questionable": t.danger, "explicit": t.danger}
            for label_, (bar, pct) in self.bars.items():
                v = it.scores.get(label_, 0.0)
                bar.set(v, colors[label_])
                pct.setText(f"{v * 100:.0f}%")

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
