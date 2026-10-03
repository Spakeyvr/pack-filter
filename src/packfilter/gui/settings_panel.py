"""Right-hand panel: what to censor, which images, how, and where to save."""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea,
                               QSlider, QStyle, QVBoxLayout, QWidget)

from ..censor import censor_image
from ..model import MODELS
from ..policy import CENSOR_STYLE_TITLES, CENSOR_STYLES, MIN_STRENGTH, LEVEL_TITLES, PRESETS, Settings
from ..scanner import CATEGORIES, CATEGORY_TITLES
from .tasks import pil_to_qimage


def section(title: str) -> QLabel:
    lbl = QLabel(title)
    lbl.setObjectName("Section")
    return lbl


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


class PresetOption(QWidget):
    """A radio button with a short explanation underneath."""

    clicked = Signal(str)

    def __init__(self, key: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.key = key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.radio = QRadioButton(title)
        self.radio.toggled.connect(lambda on: on and self.clicked.emit(self.key))
        lay.addWidget(self.radio)
        if description:
            d = hint(description)
            indent = self.radio.style().pixelMetric(QStyle.PM_ExclusiveIndicatorWidth) + \
                self.radio.style().pixelMetric(QStyle.PM_RadioButtonLabelSpacing)
            d.setContentsMargins(indent, 0, 0, 0)
            lay.addWidget(d)


def sample_art(size=(418, 164)) -> Image.Image:
    """A generic colorful picture used to preview the censor style."""
    img = Image.new("RGB", size, "#3b2a6b")
    d = ImageDraw.Draw(img)
    w, h = size
    for i in range(h):
        d.line([(0, i), (w, i)], fill=(60 + i // 2, 40 + i // 3, 140 + i // 3))
    d.ellipse((w * 0.62, h * 0.12, w * 0.62 + h * 0.5, h * 0.62), fill="#ffd36e")
    d.polygon([(0, h), (w * 0.3, h * 0.45), (w * 0.55, h)], fill="#2c2350")
    d.polygon([(w * 0.35, h), (w * 0.7, h * 0.35), (w, h)], fill="#4b3a86")
    d.rectangle((w * 0.08, h * 0.15, w * 0.45, h * 0.32), fill="#ffffff")
    return img


class SettingsPanel(QWidget):
    changed = Signal(str)  # name of what changed: "filter", "style", "model", "preview", "output"

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._loading = True
        self._preview_source: Optional[Image.Image] = None
        self.setObjectName("Panel")
        self.setMinimumWidth(QFontMetrics(self.font()).averageCharWidth() * 36)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("SettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        # --- What to censor --------------------------------------------------
        lay.addWidget(section("What to censor"))
        self.cards: dict[str, PresetOption] = {}
        group = QButtonGroup(self)
        for p in PRESETS:
            card = PresetOption(p.key, p.title + (" (default)" if p.key == "balanced" else ""), p.description)
            group.addButton(card.radio)
            card.clicked.connect(self._preset_clicked)
            self.cards[p.key] = card
            lay.addWidget(card)
        custom = PresetOption("custom", "Custom", "Fine-tune with the controls below.")
        group.addButton(custom.radio)
        custom.clicked.connect(self._preset_clicked)
        self.cards["custom"] = custom
        lay.addWidget(custom)

        row = QHBoxLayout()
        row.addWidget(QLabel("Count as lewd:"))
        self.level = QComboBox()
        for key, text in LEVEL_TITLES.items():
            self.level.addItem(text, key)
        self.level.currentIndexChanged.connect(self._custom_changed)
        row.addWidget(self.level, 1)
        lay.addLayout(row)

        srow = QHBoxLayout()
        srow.addWidget(QLabel("Strictness:"))
        self.strict_value = QLabel()
        self.strict_value.setObjectName("Hint")
        srow.addStretch(1)
        srow.addWidget(self.strict_value)
        lay.addLayout(srow)
        self.strictness = QSlider(Qt.Horizontal)
        self.strictness.setRange(0, 100)
        self.strictness.valueChanged.connect(self._custom_changed)
        lay.addWidget(self.strictness)
        lab = QHBoxLayout()
        lab.addWidget(hint("Only obvious"))
        lab.addStretch(1)
        lab.addWidget(hint("Borderline too"))
        lay.addLayout(lab)

        # --- Which images --------------------------------------------------------
        lay.addSpacing(10)
        lay.addWidget(section("Which images"))
        self.cat_boxes: dict[str, QCheckBox] = {}
        for c in CATEGORIES:
            cb = QCheckBox(CATEGORY_TITLES[c])
            cb.toggled.connect(self._categories_changed)
            self.cat_boxes[c] = cb
            lay.addWidget(cb)

        # --- How to censor -------------------------------------------------------
        lay.addSpacing(10)
        lay.addWidget(section("How to censor"))
        self.style_box = QComboBox()
        for st in CENSOR_STYLES:
            self.style_box.addItem(CENSOR_STYLE_TITLES[st], st)
        self.style_box.currentIndexChanged.connect(self._style_changed)
        lay.addWidget(self.style_box)
        self.strength_row = QWidget()
        sr = QHBoxLayout(self.strength_row)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(QLabel("Strength"))
        self.strength = QSlider(Qt.Horizontal)
        self.strength.setRange(MIN_STRENGTH, 100)  # weaker than this leaves shapes recognisable
        self.strength.valueChanged.connect(self._style_changed)
        sr.addWidget(self.strength, 1)
        lay.addWidget(self.strength_row)
        self.color_btn = QPushButton("Pick color...")
        self.color_btn.clicked.connect(self._pick_color)
        lay.addWidget(self.color_btn)
        self.image_row = QWidget()
        ir = QHBoxLayout(self.image_row)
        ir.setContentsMargins(0, 0, 0, 0)
        self.image_path = QLineEdit()
        self.image_path.setPlaceholderText("No image chosen")
        self.image_path.setReadOnly(True)
        ir.addWidget(self.image_path, 1)
        b = QPushButton("Choose...")
        b.clicked.connect(self._pick_image)
        ir.addWidget(b)
        lay.addWidget(self.image_row)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(QFontMetrics(self.font()).height() * 6)
        lay.addWidget(self.preview)
        self.preview_caption = hint("Preview")
        self.preview_caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview_caption)

        # --- Where to save -------------------------------------------------------
        lay.addSpacing(10)
        lay.addWidget(section("Save filtered packs to"))
        self.dest_row = QWidget()
        dr = QHBoxLayout(self.dest_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.dest = QLineEdit()
        self.dest.setReadOnly(True)
        dr.addWidget(self.dest, 1)
        b = QPushButton("Change...")
        b.clicked.connect(self._pick_dest)
        dr.addWidget(b)
        lay.addWidget(self.dest_row)
        self.reset_dest = QPushButton("Use my Downloads folder")
        self.reset_dest.setObjectName("Link")
        self.reset_dest.clicked.connect(self._reset_dest)
        lay.addWidget(self.reset_dest, 0, Qt.AlignLeft)
        lay.addWidget(hint("Each filtered pack is saved as its own .zip. Your original packs are never changed."))
        self.unchanged_box = QCheckBox("Also save packs that had nothing to censor")
        self.unchanged_box.toggled.connect(self._output_changed)
        lay.addWidget(self.unchanged_box)

        # --- Detection model -----------------------------------------------------
        lay.addSpacing(10)
        lay.addWidget(section("Detection"))
        self.model_box = QComboBox()
        for info in MODELS.values():
            self.model_box.addItem(f"{info.title} ({info.approx_mb} MB)", info.name)
            self.model_box.setItemData(self.model_box.count() - 1, info.description, Qt.ToolTipRole)
        self.model_box.currentIndexChanged.connect(self._model_changed)
        lay.addWidget(self.model_box)
        lay.addWidget(hint("\"Accurate\" is slower and downloads a bigger model the first time."))
        self.gpu_box = QCheckBox("Use the GPU when it's faster")
        self.gpu_box.setToolTip("Windows: any DirectX 12 GPU (NVIDIA, AMD, Intel). The GPU is only used if it gives\n"
                                "the same results as the CPU and is actually faster; otherwise the CPU is used.")
        self.gpu_box.toggled.connect(self._gpu_changed)
        lay.addWidget(self.gpu_box)
        self.show_previews = QCheckBox("Show uncensored thumbnails")
        self.show_previews.toggled.connect(self._previews_changed)
        lay.addWidget(self.show_previews)
        lay.addWidget(hint("Off by default: anything that might be lewd is blurred in the list."))
        lay.addStretch(1)

        self.load_from_settings()
        # The scroll area never scrolls sideways, so the panel must be at least as wide as its content.
        body.adjustSize()
        bar = scroll.verticalScrollBar().sizeHint().width()
        self.setMinimumWidth(max(self.minimumWidth(), body.minimumSizeHint().width() + bar + 4))

    # ------------------------------------------------------------------ sync --
    def load_from_settings(self) -> None:
        s = self.settings
        self._loading = True
        try:
            self.cards.get(s.preset, self.cards["custom"]).radio.setChecked(True)
            self.level.setCurrentIndex(max(0, self.level.findData(s.min_level)))
            self.strictness.setValue(s.strictness)
            for c, cb in self.cat_boxes.items():
                cb.setChecked(c in s.categories)
            self.style_box.setCurrentIndex(max(0, self.style_box.findData(s.style)))
            self.strength.setValue(s.style_strength)
            self.image_path.setText(s.replacement_image)
            self.dest.setText(str(s.output_path()))
            self.reset_dest.setVisible(bool(s.output_dir))
            self.unchanged_box.setChecked(s.export_unchanged)
            self.model_box.setCurrentIndex(max(0, self.model_box.findData(s.model)))
            self.show_previews.setChecked(s.show_previews)
            self.gpu_box.setChecked(s.use_gpu)
        finally:
            self._loading = False
        self._update_visibility()
        self._update_strict_label()
        self.update_preview()

    def set_category_counts(self, counts: dict[str, int]) -> None:
        for c, cb in self.cat_boxes.items():
            n = counts.get(c, 0)
            cb.setText(f"{CATEGORY_TITLES[c]}  ({n})" if counts else CATEGORY_TITLES[c])

    def set_preview_source(self, img: Optional[Image.Image]) -> None:
        self._preview_source = img
        self.update_preview()

    def _update_visibility(self) -> None:
        st = self.settings.style
        self.strength_row.setVisible(st in ("blur", "pixelate"))
        self.color_btn.setVisible(st == "solid")
        self.image_row.setVisible(st == "image")
        self.color_btn.setStyleSheet(f"QPushButton {{ border-left: 18px solid {self.settings.solid_color}; }}")

    def _update_strict_label(self) -> None:
        self.strict_value.setText(f"{self.settings.strictness}  ·  flags at {self.settings.threshold * 100:.0f}%")

    def update_preview(self) -> None:
        src = self._preview_source or sample_art()
        src = src.copy()
        src.thumbnail((300, 160))
        out = censor_image(src, self.settings)
        pm = QPixmap.fromImage(pil_to_qimage(out))
        self.preview.setPixmap(pm)
        self.preview_caption.setText("Preview on the selected image" if self._preview_source
                                     else "Preview on a sample picture")

    # -------------------------------------------------------------- handlers --
    def _preset_clicked(self, key: str) -> None:
        if self._loading:
            return
        if key == "custom":
            self.settings.preset = "custom"
        else:
            self.settings.apply_preset(key)
        self.load_from_settings()
        self.changed.emit("filter")

    def _custom_changed(self) -> None:
        if self._loading:
            return
        self.settings.min_level = self.level.currentData()
        self.settings.strictness = self.strictness.value()
        self.settings.preset = "custom"
        for p in PRESETS:  # snap back to a preset if the values match one
            if p.min_level == self.settings.min_level and p.strictness == self.settings.strictness:
                self.settings.preset = p.key
        self._loading = True
        self.cards[self.settings.preset].radio.setChecked(True)
        self._loading = False
        self._update_strict_label()
        self.changed.emit("filter")

    def _categories_changed(self) -> None:
        if self._loading:
            return
        self.settings.categories = [c for c, cb in self.cat_boxes.items() if cb.isChecked()]
        self.changed.emit("filter")

    def _style_changed(self) -> None:
        if self._loading:
            return
        self.settings.style = self.style_box.currentData()
        self.settings.style_strength = self.strength.value()
        if self.settings.style == "image" and not self.settings.replacement_image:
            self._pick_image()
        self._update_visibility()
        self.update_preview()
        self.changed.emit("style")

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self.settings.solid_color), self, "Censor color")
        if c.isValid():
            self.settings.solid_color = c.name()
            self._update_visibility()
            self.update_preview()
            self.changed.emit("style")

    def _pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Replacement image", "",
                                              "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        if path:
            self.settings.replacement_image = path
            self.image_path.setText(path)
            self.update_preview()
            self.changed.emit("style")

    def _output_changed(self) -> None:
        if self._loading:
            return
        self.settings.export_unchanged = self.unchanged_box.isChecked()
        self.changed.emit("output")

    def _pick_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save filtered packs to", str(self.settings.output_path()))
        if path:
            self.settings.output_dir = path
            self.dest.setText(path)
            self.reset_dest.setVisible(True)
            self.changed.emit("output")

    def _reset_dest(self) -> None:
        self.settings.output_dir = ""
        self.dest.setText(str(self.settings.output_path()))
        self.reset_dest.setVisible(False)
        self.changed.emit("output")

    def _model_changed(self) -> None:
        if self._loading:
            return
        self.settings.model = self.model_box.currentData()
        self.changed.emit("model")

    def _gpu_changed(self, on: bool) -> None:
        if self._loading:
            return
        self.settings.use_gpu = on
        self.changed.emit("gpu")

    def _previews_changed(self, on: bool) -> None:
        if self._loading:
            return
        self.settings.show_previews = on
        self.changed.emit("preview")
