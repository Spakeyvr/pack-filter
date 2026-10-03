"""Draw the app icon (PNG for the window, .ico for Windows, .icns for macOS)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Background: rounded square with a vertical violet gradient.
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bottom = (140, 110, 255), (82, 46, 214)
    for y in range(S):
        t = y / S
        gd.line([(0, y), (S, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((60, 60, S - 60, S - 60), radius=210, fill=255)
    img.paste(grad, (0, 0), mask)

    # A "cover" card whose picture is pixelated, i.e. censored.
    d = ImageDraw.Draw(img)
    card = (215, 250, S - 215, S - 250)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((card[0], card[1] + 24, card[2], card[3] + 24), 60, fill=(20, 0, 60, 110))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))
    d.rounded_rectangle(card, radius=60, fill=(255, 255, 255, 255))
    inner = (card[0] + 48, card[1] + 48, card[2] - 48, card[3] - 48)
    cols, rows = 4, 3
    w = (inner[2] - inner[0]) / cols
    h = (inner[3] - inner[1]) / rows
    palette = [(255, 196, 120), (255, 150, 170), (190, 160, 255), (130, 200, 255), (255, 220, 160),
               (230, 140, 200), (160, 140, 250), (255, 180, 140), (200, 170, 255), (150, 210, 240),
               (255, 160, 190), (240, 200, 255)]
    for r in range(rows):
        for c in range(cols):
            box = (inner[0] + c * w, inner[1] + r * h, inner[0] + (c + 1) * w, inner[1] + (r + 1) * h)
            d.rectangle(box, fill=palette[r * cols + c])
    # Round the mosaic's corners by re-masking it.
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).rounded_rectangle(inner, radius=28, fill=255)
    white = Image.new("RGBA", (S, S), (255, 255, 255, 255))
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).rectangle(inner, fill=255)
    ring = Image.composite(Image.new("L", (S, S), 0), ring, m)
    img.paste(white, (0, 0), ring)
    # "No" bar across the card.
    d.line([(card[0] + 20, card[3] - 20), (card[2] - 20, card[1] + 20)], fill=(82, 46, 214, 255), width=64)
    return img


def main() -> None:
    img = draw()
    assets = ROOT / "src" / "packfilter" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    img.resize((512, 512), Image.LANCZOS).save(assets / "icon.png")
    pk = ROOT / "packaging"
    pk.mkdir(exist_ok=True)
    img.save(pk / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(pk / "icon.icns")
    img.resize((256, 256), Image.LANCZOS).save(pk / "icon-256.png")


if __name__ == "__main__":
    main()
