"""Decide which images get censored, based on the model's scores and user settings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional

from .model import DEFAULT_MODEL, LABELS
from .scanner import CATEGORIES

LEVEL_TITLES = {
    "sensitive": "Suggestive and up",
    "questionable": "Sexual and up",
    "explicit": "Explicit (hentai) only",
}


@dataclass(frozen=True)
class Preset:
    key: str
    title: str
    description: str
    min_level: str
    strictness: int


PRESETS = (
    Preset("strict", "Strict",
           "Also hides suggestive covers: swimsuits, underwear, revealing outfits, lewd poses.",
           "sensitive", 50),
    Preset("balanced", "Balanced",
           "Hides clearly sexualized covers (partial nudity, sexual focus) and anything explicit.",
           "questionable", 50),
    Preset("explicit", "Explicit only",
           "Only hides outright pornographic / hentai covers.",
           "explicit", 50),
)
PRESETS_BY_KEY = {p.key: p for p in PRESETS}
CENSOR_STYLES = ("blur", "pixelate", "solid", "image")
CENSOR_STYLE_TITLES = {"blur": "Heavy blur", "pixelate": "Pixelate", "solid": "Solid color",
                       "image": "Replace with my image"}


def strictness_to_threshold(strictness: int) -> float:
    """0..100 slider -> score threshold. 50 = 0.5; higher strictness censors more.

    The model is trained with label smoothing, so its probabilities live roughly in
    0.05..0.85; this mapping keeps the slider useful across that whole range.
    """
    s = max(0, min(100, strictness)) / 100.0
    return round(0.85 - 0.7 * s, 4)


@dataclass
class Settings:
    preset: str = "balanced"           # strict / balanced / explicit / custom
    min_level: str = "questionable"    # lowest rating that counts as "lewd"
    strictness: int = 50               # 0..100
    categories: list[str] = field(default_factory=lambda: list(CATEGORIES))
    style: str = "blur"
    style_strength: int = 70           # 0..100
    solid_color: str = "#101014"
    replacement_image: str = ""
    add_label: bool = True
    output_dir: str = ""               # where filtered .zip packs go; "" = Downloads
    export_unchanged: bool = False     # also export packs that had nothing to censor
    model: str = DEFAULT_MODEL
    show_previews: bool = False        # show un-blurred thumbnails of flagged images

    def apply_preset(self, key: str) -> None:
        preset = PRESETS_BY_KEY.get(key)
        self.preset = key
        if preset:
            self.min_level = preset.min_level
            self.strictness = preset.strictness

    def output_path(self) -> Path:
        from .paths import downloads_dir
        p = Path(self.output_dir).expanduser() if self.output_dir else downloads_dir()
        return p if p.is_dir() else downloads_dir()

    @property
    def threshold(self) -> float:
        return strictness_to_threshold(self.strictness)

    def lewd_score(self, scores: dict[str, float]) -> float:
        start = LABELS.index(self.min_level)
        return sum(scores.get(label, 0.0) for label in LABELS[start:])

    def should_censor(self, scores: Optional[dict[str, float]], categories: set[str],
                      override: Optional[bool] = None) -> bool:
        if override is not None:
            return override
        if scores is None or not (categories & set(self.categories)):
            return False
        return self.lewd_score(scores) >= self.threshold

    # --- persistence -------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in raw.items() if k in known})
        if s.min_level not in LABELS[1:]:
            s.min_level = "questionable"
        if s.style not in CENSOR_STYLES:
            s.style = "blur"
        s.categories = [c for c in s.categories if c in CATEGORIES]
        return s

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def top_label(scores: dict[str, float]) -> str:
    return max(scores, key=scores.get)
