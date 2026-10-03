"""Image censoring effects and safe in-place file replacement."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageColor, ImageFilter, ImageOps

from .policy import MIN_STRENGTH, Settings
from .store import Store, sha256_bytes, sha256_file

_EXT_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".bmp": "BMP", ".gif": "GIF",
                ".webp": "WEBP", ".tga": "TGA"}


def _base(img: Image.Image) -> Image.Image:
    if getattr(img, "is_animated", False):
        img.seek(0)
    has_alpha = img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info
    return img.convert("RGBA" if has_alpha else "RGB")


def _blur(img: Image.Image, strength: int) -> Image.Image:
    w, h = img.size
    # Shrink hard first so no detail survives, then smooth it back out.
    target = max(4, round(28 - 22 * strength / 100))  # pixels along the long edge
    scale = target / max(w, h)
    small = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BOX)
    out = small.resize((w, h), Image.BICUBIC)
    return out.filter(ImageFilter.GaussianBlur(radius=max(w, h) / (target * 1.5)))


def _pixelate(img: Image.Image, strength: int) -> Image.Image:
    w, h = img.size
    blocks = max(4, int(32 - 26 * strength / 100))  # blocks along the long edge
    scale = blocks / max(w, h)
    small = img.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.BOX)
    return small.resize((w, h), Image.NEAREST)


def _solid(img: Image.Image, color: str) -> Image.Image:
    try:
        rgb = ImageColor.getrgb(color)[:3]
    except ValueError:
        rgb = (16, 16, 20)
    fill = Image.new("RGB", img.size, rgb)
    if img.mode == "RGBA":
        fill.putalpha(img.getchannel("A"))
    return fill


def _replacement(img: Image.Image, replacement: str) -> Image.Image:
    try:
        rep = _base(Image.open(replacement))
    except (OSError, ValueError):
        return _solid(img, "#101014")
    out = ImageOps.fit(rep.convert(img.mode), img.size, Image.LANCZOS)
    return out


def censor_image(img: Image.Image, settings: Settings) -> Image.Image:
    img = _base(img)
    style = settings.style
    strength = max(MIN_STRENGTH, min(100, settings.style_strength))
    if style == "pixelate":
        out = _pixelate(img, strength)
    elif style == "solid":
        out = _solid(img, settings.solid_color)
    elif style == "image" and settings.replacement_image:
        out = _replacement(img, settings.replacement_image)
    else:
        out = _blur(img, strength)
    if img.mode == "RGBA" and out.mode == "RGBA" and style in ("blur", "pixelate"):
        out.putalpha(img.getchannel("A"))  # keep transparent CD titles transparent
    return out


def encode_like(img: Image.Image, fmt: Optional[str], path: Path) -> bytes:
    fmt = fmt or _EXT_FORMATS.get(path.suffix.lower(), "PNG")
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=92)
    elif fmt == "GIF":
        # 256 colours turn a smooth blur into contour bands, which the model reads as edges.
        # A faint grain breaks the bands up (dithering alone doesn't).
        rgb = img.convert("RGB")
        rgb = Image.blend(rgb, Image.effect_noise(rgb.size, 40).convert("RGB"), 0.12)
        rgb.quantize(256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(buf, "GIF")
    elif fmt == "BMP":
        img.convert("RGB").save(buf, "BMP")
    elif fmt in ("PNG", "WEBP", "TGA"):
        img.save(buf, fmt)
    else:
        img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def censor_bytes(data: bytes, path: Path, settings: Settings) -> bytes:
    """Censored version of an image file's bytes, in the same format as the original."""
    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        out = censor_image(img, settings)
    return encode_like(out, fmt, path)


def censor_file(path: Path, settings: Settings, store: Store) -> Optional[str]:
    """Censor one image file in place, backing up the original first.

    Returns the new file's SHA-256, or None if the file was already censored by us.
    """
    data = path.read_bytes()
    original_sha = sha256_bytes(data)
    if store.lookup_censored(original_sha):
        return None
    store.save_backup(original_sha, path.suffix, data)
    encoded = censor_bytes(data, path, settings)
    tmp = path.with_name(path.name + ".pftmp")
    tmp.write_bytes(encoded)
    os.replace(tmp, path)
    new_sha = sha256_bytes(encoded)
    store.record_censored(new_sha, original_sha, path.suffix, path)
    return new_sha


def is_censored(path: Path, store: Store) -> bool:
    return store.lookup_censored(sha256_file(path)) is not None
