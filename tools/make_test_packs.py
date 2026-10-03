"""Build realistic Etterna/StepMania (and osu!) test packs with known-rating covers.

The cover art comes from the sample images the anime_dbrating authors publish in
the imgutils docs (4 general, 4 sensitive, 4 questionable, 4 explicit - NSFW).
They are downloaded on demand and never committed to this repo.

    python tools/make_test_packs.py OUT_DIR
"""

from __future__ import annotations

import argparse
import shutil
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

from PIL import Image, ImageOps

SAMPLES = {
    "general": [1, 2, 3, 4],
    "sensitive": [5, 6, 7, 8],
    "questionable": [9, 10, 11, 12],
    "explicit": [13, 14, 15, 16],
}
BASE_URL = "https://raw.githubusercontent.com/deepghs/imgutils/main/docs/source/api_doc/validate/dbrating"


def _ssl() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def fetch_samples(cache: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for rating, ids in SAMPLES.items():
        for n in ids:
            dest = cache / rating / f"{n}.jpg"
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with urllib.request.urlopen(f"{BASE_URL}/{rating}/{n}.jpg", timeout=60, context=_ssl()) as r:
                    dest.write_bytes(r.read())
            out.setdefault(rating, []).append(dest)
    return out


SM_TEMPLATE = """#TITLE:{title};
#SUBTITLE:;
#ARTIST:Test Artist;
#BANNER:{banner};
#BACKGROUND:{background};
#JACKET:{jacket};
#CDTITLE:{cdtitle};
#MUSIC:song.ogg;
#OFFSET:0.000;
#BPMS:0.000=180.000;
#BGCHANGES:{bgchanges};
#NOTES:
     dance-single:
     Test:
     Hard:
     12:
     0,0,0,0,0:
1000
0100
0010
0001
;
"""

SSC_TEMPLATE = """#VERSION:0.83;
#TITLE:{title};
#ARTIST:Test Artist;
#BANNER:{banner};
#BACKGROUND:{background};
#JACKET:{jacket};
#MUSIC:song.ogg;
#OFFSET:0.000;
#BPMS:0.000=180.000;
#NOTEDATA:;
#STEPSTYPE:dance-single;
#DIFFICULTY:Hard;
#METER:12;
#NOTES:
1000
0100
0010
0001
;
"""


def banner(img: Image.Image) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (418, 164), Image.LANCZOS, centering=(0.5, 0.3))


def jacket(img: Image.Image) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (512, 512), Image.LANCZOS, centering=(0.5, 0.3))


def background(img: Image.Image) -> Image.Image:
    return ImageOps.fit(img.convert("RGB"), (1280, 720), Image.LANCZOS, centering=(0.5, 0.3))


def song(dir_: Path, title: str, src: Path | None, *, ssc: bool = False, bn="bn.png", bg="bg.jpg",
         jk="jacket.png", cdtitle: Path | None = None, tag_case_mismatch=False, bgchange: Path | None = None):
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / "song.ogg").write_bytes(b"OggS-fake-audio")
    fields = {"title": title, "banner": "", "background": "", "jacket": "", "cdtitle": "", "bgchanges": ""}
    if src is not None:
        img = Image.open(src)
        if bn:
            banner(img).save(dir_ / bn)
            fields["banner"] = bn.upper() if tag_case_mismatch else bn
        if bg:
            background(img).save(dir_ / bg, quality=90)
            fields["background"] = bg
        if jk:
            jacket(img).save(dir_ / jk)
            fields["jacket"] = jk
    if cdtitle is not None:
        shutil.copy(cdtitle, dir_ / "cdtitle.png")
        fields["cdtitle"] = "cdtitle.png"
    if bgchange is not None:
        background(Image.open(bgchange)).save(dir_ / "bgchange1.png")
        fields["bgchanges"] = "8.000=bgchange1.png=1.000=0=0=1=====,\n99999=-nosongbg-=1.000=0=0=0"
    template = SSC_TEMPLATE if ssc else SM_TEMPLATE
    (dir_ / f"{dir_.name}.{'ssc' if ssc else 'sm'}").write_text(template.format(**fields), encoding="utf-8")


def build(out: Path, cache: Path) -> dict[str, Path]:
    s = fetch_samples(cache)
    out.mkdir(parents=True, exist_ok=True)
    songs_dir = out / "Songs"
    if songs_dir.exists():
        shutil.rmtree(songs_dir)

    # A transparent CD title, to check alpha survives censoring.
    cd = Image.new("RGBA", (128, 40), (0, 0, 0, 0))
    cd.paste(ImageOps.fit(Image.open(s["general"][0]).convert("RGB"), (40, 40)), (0, 0))
    cd_path = cache / "cdtitle.png"
    cd.save(cd_path)

    # Pack 1: all clean covers - nothing should be censored.
    p = songs_dir / "Clean Anime Pack"
    for i, src in enumerate(s["general"]):
        song(p / f"Clean Song {i + 1}", f"Clean Song {i + 1}", src, ssc=(i % 2 == 1), cdtitle=cd_path)
    banner(Image.open(s["general"][1])).save(p / "Clean Anime Pack.png")

    # Pack 2: lewd pack - sensitive, questionable and explicit covers in every slot.
    p = songs_dir / "Lewd Covers Pack"
    for rating in ("sensitive", "questionable", "explicit"):
        for i, src in enumerate(s[rating]):
            song(p / f"{rating.title()} {i + 1}", f"{rating.title()} Song {i + 1}", src,
                 ssc=(i % 2 == 0), tag_case_mismatch=(i == 1))
    banner(Image.open(s["explicit"][0])).save(p / "Lewd Covers Pack.png")

    # Pack 3: mostly clean pack with a few lewd surprises in odd places.
    p = songs_dir / "Mixed Bag Pack"
    song(p / "Normal Song", "Normal Song", s["general"][2], jk=None)
    song(p / "Explicit BG Change", "Explicit BG Change", s["general"][3], bgchange=s["explicit"][2])
    song(p / "No Tags Song", "No Tags Song", None)  # images only discoverable by filename
    banner(Image.open(s["questionable"][1])).save(p / "No Tags Song" / "notags-bn.png")
    background(Image.open(s["explicit"][1])).save(p / "No Tags Song" / "notags-bg.jpg")
    jp = p / "日本語の曲"
    song(jp, "日本語の曲", s["questionable"][3], bn="バナー.png", bg="背景.jpg", jk=None)
    gif = p / "Gif Banner"
    song(gif, "Gif Banner", None)
    banner(Image.open(s["explicit"][3])).convert("P", palette=Image.ADAPTIVE).save(gif / "bn.gif")
    (gif / "Gif Banner.sm").write_text(SM_TEMPLATE.format(title="Gif Banner", banner="bn.gif", background="",
                                                          jacket="", cdtitle="", bgchanges=""), encoding="utf-8")
    broken = p / "Broken Image"
    song(broken, "Broken Image", None)
    (broken / "bn.png").write_bytes(b"\x89PNG\r\n\x1a\nthis is not really a png")

    # Pack 4: an osu! beatmap folder (another similar game).
    osu = songs_dir / "osu! Beatmaps" / "123 Artist - Lewd Map"
    osu.mkdir(parents=True)
    background(Image.open(s["explicit"][0])).save(osu / "lewd bg.jpg")
    (osu / "Artist - Lewd Map (Mapper) [Hard].osu").write_text(
        "osu file format v14\n\n[Metadata]\nTitle:Lewd Map\nArtist:Artist\n\n[Events]\n"
        '//Background and Video events\n0,0,"lewd bg.jpg",0,0\n', encoding="utf-8")

    # A downloaded-style zip of a lewd pack, to test zip import.
    zsrc = out / "zip-src" / "Zipped Lewd Pack"
    if zsrc.parent.exists():
        shutil.rmtree(zsrc.parent)
    song(zsrc / "Zipped Explicit", "Zipped Explicit", s["explicit"][1])
    song(zsrc / "Zipped Clean", "Zipped Clean", s["general"][0])
    zpath = out / "Zipped Lewd Pack.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(zsrc.rglob("*")):
            zf.write(f, f.relative_to(zsrc.parent).as_posix())
    shutil.rmtree(zsrc.parent)
    return {"songs": songs_dir, "zip": zpath}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--cache", type=Path, default=None, help="where to keep downloaded sample images")
    args = ap.parse_args()
    res = build(args.out, args.cache or args.out / ".samples")
    print(f"Songs folder: {res['songs']}\nZip pack:     {res['zip']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
