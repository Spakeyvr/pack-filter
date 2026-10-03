"""The thumbnail grid: list model, card delegate and thumbnail cache."""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPixmap
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
    MIN_W, TEXT_H, GAP = 210, 50, 10

    def __init__(self, cache: ThumbCache, settings_fn: Callable[[], Settings], parent=None):
        super().__init__(parent)
        self.cache = cache
        self.settings_fn = settings_fn
        self.card_w = self.MIN_W
        self.thumb_h = round(self.MIN_W * 0.5625)

    def cell_size(self) -> QSize:
        return QSize(self.card_w + self.GAP, self.thumb_h + self.TEXT_H + self.GAP)

    def sizeHint(self, option, index):
        return self.cell_size()

    def paint(self, p: QPainter, option: QStyleOptionViewItem, index):
        item: Item = index.data(ItemRole)
        t = theme.current()
        s = self.settings_fn()
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = option.rect.adjusted(self.GAP // 2, self.GAP // 2, -self.GAP // 2, -self.GAP // 2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        card = QPainterPath()
        card.addRoundedRect(QRectF(r), 10, 10)
        p.fillPath(card, QColor(t.surface))
        border = QColor(t.accent) if selected else QColor(t.border if not hovered else t.text_dim)
        p.setPen(border)
        if selected:
            pen = p.pen()
            pen.setWidthF(2.5)
            p.setPen(pen)
        p.drawPath(card)

        # Thumbnail area
        thumb_rect = QRect(r.left() + 1, r.top() + 1, r.width() - 2, self.thumb_h)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(thumb_rect), 9, 9)
        p.save()
        p.setClipPath(clip)
        p.fillRect(thumb_rect, QColor(t.surface_alt))
        pix = self.cache.get(item) if (item.scores is not None or item.censored) and not item.error else None
        if pix is not None:
            hide = should_hide_preview(item, s)
            pm = pix[1] if hide else pix[0]
            scaled = pm.scaled(thumb_rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = thumb_rect.left() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.top() + (thumb_rect.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
            if hide and not item.censored:
                p.setPen(QColor(255, 255, 255, 220))
                p.setFont(scaled_font(option.font, 0.9))
                p.drawText(thumb_rect, Qt.AlignCenter, "Preview hidden")
        else:
            p.setPen(QColor(t.text_dim))
            p.drawText(thumb_rect, Qt.AlignCenter, "Unreadable image" if item.error else "Checking...")
        p.restore()

        # Status chip
        label, color_key = item_state(item, s)
        chip_color = QColor(getattr(t, color_key))
        f = scaled_font(option.font, 0.82, bold=True)
        p.setFont(f)
        fm = QFontMetrics(f)
        chip = QRect(thumb_rect.left() + 8, thumb_rect.top() + 8, fm.horizontalAdvance(label) + 16, fm.height() + 6)
        path = QPainterPath()
        path.addRoundedRect(QRectF(chip), chip.height() / 2, chip.height() / 2)
        p.fillPath(path, chip_color)
        p.setPen(QColor("#ffffff"))
        p.drawText(chip, Qt.AlignCenter, label)

        # Rating chip
        if item.scores:
            top = max(item.scores, key=item.scores.get)
            text = f"{RATING_NAMES[top]} {item.scores[top] * 100:.0f}%"
            rchip = QRect(0, 0, fm.horizontalAdvance(text) + 14, fm.height() + 6)
            rchip.moveBottomRight(thumb_rect.bottomRight() - QRect(0, 0, 8, 8).bottomRight())
            path = QPainterPath()
            path.addRoundedRect(QRectF(rchip), 6, 6)
            p.fillPath(path, QColor(0, 0, 0, 150))
            p.setPen(QColor("#ffffff"))
            p.drawText(rchip, Qt.AlignCenter, text)

        # Text
        text_rect = QRect(r.left() + 10, thumb_rect.bottom() + 6, r.width() - 20, self.TEXT_H - 10)
        f = scaled_font(option.font, 1.0, bold=True)
        p.setFont(f)
        p.setPen(QColor(t.text))
        fm = QFontMetrics(f)
        p.drawText(text_rect.left(), text_rect.top() + fm.ascent(),
                   fm.elidedText(item.song, Qt.ElideRight, text_rect.width()))
        f2 = scaled_font(option.font, 0.88)
        p.setFont(f2)
        p.setPen(QColor(t.text_dim))
        fm2 = QFontMetrics(f2)
        cat = CATEGORY_TITLES.get(next(iter(sorted(item.categories)), "other"), "Image").rstrip("s")
        if len(item.categories) > 1:
            cat = " + ".join(CATEGORY_TITLES[c].split(" ")[0].rstrip("s") for c in sorted(item.categories))
        sub = f"{cat}  ·  {item.path.name}"
        p.drawText(text_rect.left(), text_rect.top() + fm.height() + fm2.ascent() + 2,
                   fm2.elidedText(sub, Qt.ElideMiddle, text_rect.width()))
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
        """Stretch cards so each row fills the full width."""
        d = self.itemDelegate()
        if not isinstance(d, CardDelegate):
            return
        avail = self.width() - self.style().pixelMetric(QStyle.PM_ScrollBarExtent) - 4
        cols = max(1, avail // (d.MIN_W + d.GAP))
        cell = avail // cols
        d.card_w = cell - d.GAP
        d.thumb_h = round(d.card_w * 0.5625)
        if self.gridSize() != d.cell_size():
            self.setGridSize(d.cell_size())
