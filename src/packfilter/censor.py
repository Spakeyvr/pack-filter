"""Image censoring effects and safe in-place file replacement."""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps

from .policy import Settings
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
    target = max(4, int(48 - 40 * strength / 100))
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


def _label(img: Image.Image) -> Image.Image:
    w, h = img.size
    if min(w, h) < 40:
        return img
    size = max(10, min(int(h * 0.16), int(w * 0.09)))
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # Pillow without FreeType
        font = ImageFont.load_default()
    text = "CENSORED"
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    tw, th = right - left, bottom - top
    pad_x, pad_y = size * 0.6, size * 0.35
    x0, y0 = (w - tw) / 2 - pad_x, (h - th) / 2 - pad_y
    draw.rounded_rectangle((x0, y0, x0 + tw + 2 * pad_x, y0 + th + 2 * pad_y),
                           radius=size * 0.4, fill=(0, 0, 0, 150))
    draw.text(((w - tw) / 2 - left, (h - th) / 2 - top), text, font=font, fill=(255, 255, 255, 235))
    base = img.convert("RGBA")
    base.alpha_composite(overlay)
    return base if img.mode == "RGBA" else base.convert("RGB")


def censor_image(img: Image.Image, settings: Settings) -> Image.Image:
    img = _base(img)
    style = settings.style
    if style == "pixelate":
        out = _pixelate(img, settings.style_strength)
    elif style == "solid":
        out = _solid(img, settings.solid_color)
    elif style == "image" and settings.replacement_image:
        out = _replacement(img, settings.replacement_image)
    else:
        out = _blur(img, settings.style_strength)
    if img.mode == "RGBA" and out.mode == "RGBA" and style in ("blur", "pixelate"):
        out.putalpha(img.getchannel("A"))  # keep transparent CD titles transparent
    if settings.add_label:
        out = _label(out)
    return out


def encode_like(img: Image.Image, fmt: Optional[str], path: Path) -> bytes:
    fmt = fmt or _EXT_FORMATS.get(path.suffix.lower(), "PNG")
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=92)
    elif fmt == "GIF":
        img.convert("RGB").convert("P", palette=Image.ADAPTIVE).save(buf, "GIF")
    elif fmt == "BMP":
        img.convert("RGB").save(buf, "BMP")
    elif fmt in ("PNG", "WEBP", "TGA"):
        img.save(buf, fmt)
    else:
        img.convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def censor_file(path: Path, settings: Settings, store: Store) -> Optional[str]:
    """Censor one image file in place, backing up the original first.

    Returns the new file's SHA-256, or None if the file was already censored by us.
    """
    data = path.read_bytes()
    original_sha = sha256_bytes(data)
    if store.lookup_censored(original_sha):
        return None
    store.save_backup(original_sha, path.suffix, data)
    with Image.open(io.BytesIO(data)) as img:
        fmt = img.format
        out = censor_image(img, settings)
    encoded = encode_like(out, fmt, path)
    tmp = path.with_name(path.name + ".pftmp")
    tmp.write_bytes(encoded)
    os.replace(tmp, path)
    new_sha = sha256_bytes(encoded)
    store.record_censored(new_sha, original_sha, path.suffix, path)
    return new_sha


def is_censored(path: Path, store: Store) -> bool:
    return store.lookup_censored(sha256_file(path)) is not None
