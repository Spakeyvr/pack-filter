"""Right-hand panel: what to censor, which images, how, and where to save."""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from ..censor import censor_image
from ..model import MODELS
from ..policy import CENSOR_STYLE_TITLES, CENSOR_STYLES, LEVEL_TITLES, PRESETS, Settings
from ..scanner import CATEGORIES, CATEGORY_TITLES
from .tasks import pil_to_qimage


def section(title: str) -> QLabel:
    lbl = QLabel(title.upper())
    lbl.setObjectName("SectionTitle")
    return lbl


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


class PresetCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, title: str, description: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("PresetCard")
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(2)
        self.radio = QRadioButton(title)
        self.radio.setStyleSheet("font-weight: 600;")
        self.radio.toggled.connect(lambda on: on and self.clicked.emit(self.key))
        lay.addWidget(self.radio)
        if description:
            d = hint(description)
            d.setContentsMargins(26, 0, 0, 0)
            lay.addWidget(d)

    def mousePressEvent(self, e):
        self.radio.setChecked(True)
        super().mousePressEvent(e)

    def set_selected(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)


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
        self.setObjectName("SettingsPanel")
        self.setMinimumWidth(320)
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
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        title = QLabel("Censor settings")
        title.setObjectName("PanelTitle")
        lay.addWidget(title)

        # --- What to censor --------------------------------------------------
        lay.addWidget(section("What to censor"))
        self.cards: dict[str, PresetCard] = {}
        group = QButtonGroup(self)
        for p in PRESETS:
            card = PresetCard(p.key, p.title + ("  (recommended)" if p.key == "balanced" else ""), p.description)
            group.addButton(card.radio)
            card.clicked.connect(self._preset_clicked)
            self.cards[p.key] = card
            lay.addWidget(card)
        custom = PresetCard("custom", "Custom", "Fine-tune with the controls below.")
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
        lay.addSpacing(6)
        lay.addWidget(section("Which images"))
        self.cat_boxes: dict[str, QCheckBox] = {}
        for c in CATEGORIES:
            cb = QCheckBox(CATEGORY_TITLES[c])
            cb.toggled.connect(self._categories_changed)
            self.cat_boxes[c] = cb
            lay.addWidget(cb)

        # --- How to censor -------------------------------------------------------
        lay.addSpacing(6)
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
        self.strength.setRange(0, 100)
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
        self.label_box = QCheckBox('Add a "CENSORED" label')
        self.label_box.toggled.connect(self._style_changed)
        lay.addWidget(self.label_box)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(110)
        lay.addWidget(self.preview)
        self.preview_caption = hint("Preview")
        self.preview_caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.preview_caption)

        # --- Where to save -------------------------------------------------------
        lay.addSpacing(6)
        lay.addWidget(section("Where to save"))
        self.inplace = QRadioButton("Edit the packs directly")
        self.copy = QRadioButton("Save censored copies to another folder")
        og = QButtonGroup(self)
        og.addButton(self.inplace)
        og.addButton(self.copy)
        lay.addWidget(self.inplace)
        lay.addWidget(hint("Originals are backed up, so you can undo with \"Restore originals\" at any time."))
        lay.addWidget(self.copy)
        self.dest_row = QWidget()
        dr = QHBoxLayout(self.dest_row)
        dr.setContentsMargins(0, 0, 0, 0)
        self.dest = QLineEdit()
        self.dest.setPlaceholderText("Choose an output folder")
        self.dest.setReadOnly(True)
        dr.addWidget(self.dest, 1)
        b = QPushButton("Browse...")
        b.clicked.connect(self._pick_dest)
        dr.addWidget(b)
        lay.addWidget(self.dest_row)
        self.inplace.toggled.connect(self._output_changed)

        # --- Detection model -----------------------------------------------------
        lay.addSpacing(6)
        lay.addWidget(section("Detection"))
        self.model_box = QComboBox()
        for info in MODELS.values():
            self.model_box.addItem(f"{info.title} ({info.approx_mb} MB)", info.name)
            self.model_box.setItemData(self.model_box.count() - 1, info.description, Qt.ToolTipRole)
        self.model_box.currentIndexChanged.connect(self._model_changed)
        lay.addWidget(self.model_box)
        lay.addWidget(hint("\"Accurate\" is slower and downloads a bigger model the first time."))
        self.show_previews = QCheckBox("Show uncensored thumbnails")
        self.show_previews.toggled.connect(self._previews_changed)
        lay.addWidget(self.show_previews)
        lay.addWidget(hint("Off by default: anything that might be lewd is blurred in the list."))
        lay.addStretch(1)

        self.load_from_settings()

    # ------------------------------------------------------------------ sync --
    def load_from_settings(self) -> None:
        s = self.settings
        self._loading = True
        try:
            self.cards.get(s.preset, self.cards["custom"]).radio.setChecked(True)
            for key, card in self.cards.items():
                card.set_selected(key == s.preset)
            self.level.setCurrentIndex(max(0, self.level.findData(s.min_level)))
            self.strictness.setValue(s.strictness)
            for c, cb in self.cat_boxes.items():
                cb.setChecked(c in s.categories)
            self.style_box.setCurrentIndex(max(0, self.style_box.findData(s.style)))
            self.strength.setValue(s.style_strength)
            self.label_box.setChecked(s.add_label)
            self.image_path.setText(s.replacement_image)
            (self.copy if s.output_mode == "copy" else self.inplace).setChecked(True)
            self.dest.setText(s.copy_destination)
            self.model_box.setCurrentIndex(max(0, self.model_box.findData(s.model)))
            self.show_previews.setChecked(s.show_previews)
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
        self.dest_row.setEnabled(self.settings.output_mode == "copy")
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
        for key, card in self.cards.items():
            card.set_selected(key == self.settings.preset)
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
        self.settings.add_label = self.label_box.isChecked()
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
        self.settings.output_mode = "inplace" if self.inplace.isChecked() else "copy"
        if self.settings.output_mode == "copy" and not self.settings.copy_destination:
            self._pick_dest()
        self._update_visibility()
        self.changed.emit("output")

    def _pick_dest(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Save censored packs to")
        if path:
            self.settings.copy_destination = path
            self.dest.setText(path)
            self.changed.emit("output")

    def _model_changed(self) -> None:
        if self._loading:
            return
        self.settings.model = self.model_box.currentData()
        self.changed.emit("model")

    def _previews_changed(self, on: bool) -> None:
        if self._loading:
            return
        self.settings.show_previews = on
        self.changed.emit("preview")
