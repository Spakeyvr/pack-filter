"""Draw the app icon (PNG for the window, .ico for Windows, .icns for macOS).

A plain, flat mark: a cover whose picture is pixelated, on a dark tile.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 1024


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((80, 80, S - 80, S - 80), radius=190, fill=(38, 38, 40, 255))

    # The "cover": a light frame with a pixelated picture inside.
    card = (230, 290, S - 230, S - 290)
    d.rounded_rectangle(card, radius=36, fill=(236, 236, 236, 255))
    inner = (card[0] + 34, card[1] + 34, card[2] - 34, card[3] - 34)
    cols, rows = 4, 3
    w = (inner[2] - inner[0]) / cols
    h = (inner[3] - inner[1]) / rows
    greys = [(118, 118, 122), (150, 150, 154), (98, 98, 102), (172, 172, 176),
             (140, 140, 144), (88, 88, 92), (160, 160, 164), (124, 124, 128),
             (178, 178, 182), (110, 110, 114), (132, 132, 136), (96, 96, 100)]
    for r in range(rows):
        for c in range(cols):
            d.rectangle((round(inner[0] + c * w), round(inner[1] + r * h),
                         round(inner[0] + (c + 1) * w) - 1, round(inner[1] + (r + 1) * h) - 1),
                        fill=greys[r * cols + c])
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
