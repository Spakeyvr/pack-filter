"""The thumbnail grid: list model, card delegate and thumbnail cache."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ..engine import Item
from ..policy import Settings
from ..scanner import CATEGORY_TITLES
from . import theme
from .tasks import ThumbnailLoader

RATING_NAMES = {"general": "Safe", "sensitive": "Suggestive", "questionable": "Sexual", "explicit": "Explicit"}
ItemRole = Qt.UserRole + 1


def item_state(item: Item, settings: Settings) -> tuple[str, str]:
    """(label, color-key) shown on a card."""
    if item.error:
        return "Unreadable", "muted"
    if item.censored:
        return "Censored", "accent"
    if item.scores is None:
        return "Checking...", "muted"
    if item.will_censor(settings):
        return ("Censor (manual)" if item.override else "Will censor"), "danger"
    if item.override is False:
        return "Kept (manual)", "ok"
    return "OK", "ok"


def should_hide_preview(item: Item, settings: Settings) -> bool:
    """Blur thumbnails of anything that might be lewd, even if it won't be censored."""
    if settings.show_previews or item.censored:
        return False
    if item.scores is None:
        return True
    lewd = item.scores.get("questionable", 0) + item.scores.get("explicit", 0)
    return item.will_censor(settings) or lewd >= 0.35


def scaled_font(base: QFont, factor: float = 1.0, bold: bool = False) -> QFont:
    """Scale a font whether it was sized in points or (via the stylesheet) in pixels."""
    f = QFont(base)
    if f.pointSizeF() > 0:
        f.setPointSizeF(max(7.0, f.pointSizeF() * factor))
    elif f.pixelSize() > 0:
        f.setPixelSize(max(9, round(f.pixelSize() * factor)))
    f.setBold(bold)
    return f


class ResultsModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[Item] = []
        self._rows: dict[int, int] = {}

    def set_items(self, items: list[Item]) -> None:
        self.beginResetModel()
        self._items = items
        self._rows = {id(it): i for i, it in enumerate(items)}
        self.endResetModel()

    def items(self) -> list[Item]:
        return self._items

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == ItemRole:
            return item
        if role == Qt.DisplayRole:
            return item.song
        if role == Qt.ToolTipRole:
            return str(item.path)
        return None

    def refresh(self, items: Optional[list[Item]] = None) -> None:
        if not self._items:
            return
        if items is None:
            self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1))
            return
        for it in items:
            row = self._rows.get(id(it))
            if row is not None:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx)


class ThumbCache:
    """Thumbnails keyed by (path, sha) so a censored file gets a fresh thumbnail."""

    def __init__(self, loader: ThumbnailLoader, on_ready: Callable[[], None]):
        self.loader = loader
        self._thumbs: dict[tuple, tuple[QPixmap, QPixmap]] = {}
        self._images: dict[tuple, tuple[QImage, QImage]] = {}
        self._failed: set = set()
        loader.ready.connect(self._ready)
        loader.failed.connect(self._failed.add)
        self._on_ready = on_ready

    @staticmethod
    def key(item: Item) -> tuple:
        return (str(item.path), item.sha)

    def _ready(self, key, thumb: QImage, blurred: QImage) -> None:
        self._images[key] = (thumb, blurred)
        self._on_ready()

    def get(self, item: Item) -> Optional[tuple[QPixmap, QPixmap]]:
        key = self.key(item)
        if key in self._thumbs:
            return self._thumbs[key]
        if key in self._images:
            thumb, blurred = self._images.pop(key)
            self._thumbs[key] = (QPixmap.fromImage(thumb), QPixmap.fromImage(blurred))
            return self._thumbs[key]
        if key not in self._failed and item.sha:
            self.loader.request(key, str(item.path))
        return None


class CardDelegate(QStyledItemDelegate):
    """A thumbnail with three lines of text under it. All sizes derive from the font."""

    GAP = 8

    def __init__(self, cache: ThumbCache, settings_fn: Callable[[], Settings], parent=None):
        super().__init__(parent)
        self.cache = cache
        self.settings_fn = settings_fn
        self.card_w = self.min_width(QFont())
        self.thumb_h = round(self.card_w * 0.5625)
        self.text_h = 0

    @staticmethod
    def min_width(font: QFont) -> int:
        return QFontMetrics(font).averageCharWidth() * 26

    def text_height(self, font: QFont) -> int:
        bold = QFontMetrics(scaled_font(font, 1.0, bold=True))
        small = QFontMetrics(scaled_font(font, 0.92))
        return 8 + bold.height() + 2 * small.height() + 4 + 8

    def cell_size(self) -> QSize:
        return QSize(self.card_w + self.GAP, self.thumb_h + self.text_h + self.GAP)

    def sizeHint(self, option, index):
        return self.cell_size()

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index):
        item: Item = index.data(ItemRole)
        t = theme.current()
        s = self.settings_fn()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(option.rect.adjusted(self.GAP // 2, self.GAP // 2, -self.GAP // 2, -self.GAP // 2))
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        card = QPainterPath()
        card.addRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        p.fillPath(card, QColor(t.panel))

        # Thumbnail
        thumb = QRectF(r.left(), r.top(), r.width(), self.thumb_h)
        clip = QPainterPath()
        clip.addRoundedRect(thumb.adjusted(0.5, 0.5, -0.5, 0), 4, 4)
        p.save()
        p.setClipPath(clip)
        p.fillRect(thumb, QColor(t.bg))
        pix = self.cache.get(item) if (item.scores is not None or item.censored) and not item.error else None
        if pix is not None:
            hide = should_hide_preview(item, s)
            pm = pix[1] if hide else pix[0]
            target = thumb.toRect()
            scaled = pm.scaled(target.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            p.drawPixmap(target.left() + (target.width() - scaled.width()) // 2,
                         target.top() + (target.height() - scaled.height()) // 2, scaled)
            if hide and not item.censored:
                p.setPen(QColor(255, 255, 255, 210))
                p.setFont(scaled_font(option.font, 0.92))
                p.drawText(thumb, Qt.AlignCenter, "Preview hidden")
        else:
            p.setPen(QColor(t.text_dim))
            p.drawText(thumb, Qt.AlignCenter, "Unreadable" if item.error else "Checking...")
        p.restore()

        # Text: title / status / details
        pad = 8
        x = r.left() + pad
        width = int(r.width() - 2 * pad)
        y = thumb.bottom() + 8
        bold = scaled_font(option.font, 1.0, bold=True)
        small = scaled_font(option.font, 0.92)
        fb, fs = QFontMetrics(bold), QFontMetrics(small)
        p.setFont(bold)
        p.setPen(QColor(t.text))
        p.drawText(int(x), int(y + fb.ascent()), fb.elidedText(item.song, Qt.ElideRight, width))
        y += fb.height() + 2

        label, color_key = item_state(item, s)
        color = QColor(getattr(t, color_key) if color_key != "ok" else t.text_dim)
        dot = fs.height() * 0.42
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(x, y + (fs.height() - dot) / 2, dot, dot))
        p.setFont(small)
        p.setPen(color)
        status = label
        if item.scores:
            top = max(item.scores, key=item.scores.get)
            status += f"  ·  {RATING_NAMES[top]} {item.scores[top] * 100:.0f}%"
        p.drawText(int(x + dot + 6), int(y + fs.ascent()), fs.elidedText(status, Qt.ElideRight, int(width - dot - 6)))
        y += fs.height() + 2

        cats = sorted(item.categories)
        cat = (CATEGORY_TITLES.get(cats[0], "Image").rstrip("s") if len(cats) == 1
               else " + ".join(CATEGORY_TITLES[c].split(" ")[0].rstrip("s") for c in cats))
        p.setPen(QColor(t.text_dim))
        p.drawText(int(x), int(y + fs.ascent()), fs.elidedText(f"{cat}  ·  {item.path.name}", Qt.ElideMiddle, width))

        p.setBrush(Qt.NoBrush)
        pen = QPen(QColor(t.accent if selected else (t.text_dim if hovered else t.border)))
        pen.setWidthF(2.0 if selected else 1.0)
        p.setPen(pen)
        p.drawPath(card)
        p.restore()


class ResultsView(QListView):
    activatedItems = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QListView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(200)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    def relayout(self) -> None:
        """Stretch cards so each row fills the full width; sizes follow the font."""
        d = self.itemDelegate()
        if not isinstance(d, CardDelegate):
            return
        d.text_h = d.text_height(self.font())
        min_w = d.min_width(self.font())
        avail = self.viewport().width() - 2
        if self.verticalScrollBar().isHidden():
            avail -= self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        cols = max(1, avail // (min_w + d.GAP))
        d.card_w = max(min_w, avail // cols - d.GAP)
        d.thumb_h = round(d.card_w * 0.5625)
        if self.gridSize() != d.cell_size():
            self.setGridSize(d.cell_size())

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.FontChange:
            self.relayout()
