"""Engine tests with a fake model so they run offline and fast."""

import zipfile

import pytest
from PIL import Image

from packfilter.engine import Engine, extract_zip, items_from_packs
from packfilter.policy import Settings
from packfilter.store import Store, sha256_file

from conftest import make_image, write_sm

LEWD = (255, 0, 0)
CLEAN = (0, 0, 255)


class FakeModel:
    model_name = "fake"

    def predict_batch(self, arrays):
        out = []
        for a in arrays:
            red = float(a[0].mean())  # preprocessed to [-1, 1]
            lewd = red > 0.5
            out.append({"general": 0.1 if lewd else 0.8, "sensitive": 0.05,
                        "questionable": 0.05, "explicit": 0.8 if lewd else 0.05})
        return out


@pytest.fixture
def engine(tmp_path):
    e = Engine(Store(tmp_path / "store"))
    e.model = lambda *a, **k: FakeModel()
    return e


@pytest.fixture
def pack(tmp_path):
    root = tmp_path / "Songs" / "Pack"
    write_sm(root / "Lewd", banner="bn.png", background="bg.jpg")
    make_image(root / "Lewd" / "bn.png", LEWD)
    make_image(root / "Lewd" / "bg.jpg", LEWD, size=(320, 180))
    write_sm(root / "Clean", banner="bn.png")
    make_image(root / "Clean" / "bn.png", CLEAN)
    cd = root / "Lewd" / "cdtitle.png"
    img = Image.new("RGBA", (80, 40), LEWD + (255,))
    img.putpixel((0, 0), (0, 0, 0, 0))
    img.save(cd)
    write_sm(root / "Broken", banner="bn.png")
    (root / "Broken" / "bn.png").write_bytes(b"not an image")
    return root


def classify(engine, path):
    items = items_from_packs(engine.collect([path]))
    engine.classify(items, "fake")
    return {it.path.relative_to(path).as_posix(): it for it in items}


def test_inplace_apply_and_restore(engine, pack):
    before = {p: sha256_file(p) for p in pack.rglob("*.*") if p.suffix in (".png", ".jpg")}
    items = classify(engine, pack)
    assert items["Broken/bn.png"].error
    s = Settings()
    assert {k for k, it in items.items() if it.will_censor(s)} == {"Lewd/bn.png", "Lewd/bg.jpg", "Lewd/cdtitle.png"}

    res = engine.apply(list(items.values()), s)
    assert res.censored == 3 and not res.errors
    assert sha256_file(pack / "Clean" / "bn.png") == before[pack / "Clean" / "bn.png"]

    # Same size, same format, alpha kept.
    with Image.open(pack / "Lewd" / "bg.jpg") as im:
        assert im.format == "JPEG" and im.size == (320, 180)
    with Image.open(pack / "Lewd" / "cdtitle.png") as im:
        assert im.mode == "RGBA" and im.getpixel((0, 0))[3] == 0

    # A fresh scan recognises the censored files and doesn't re-censor them.
    items = classify(engine, pack)
    assert {k for k, it in items.items() if it.censored} == {"Lewd/bn.png", "Lewd/bg.jpg", "Lewd/cdtitle.png"}
    assert items["Lewd/bn.png"].scores["explicit"] == 0.8  # original's scores remembered
    assert engine.apply(list(items.values()), s).censored == 0

    res = engine.restore(list(items.values()))
    assert res.restored == 3 and not res.errors
    after = {p: sha256_file(p) for p in before}
    assert after == before


def test_overrides_and_category_filter(engine, pack):
    items = classify(engine, pack)
    s = Settings(categories=["background"])
    items["Clean/bn.png"].override = True
    items["Lewd/bg.jpg"].override = False
    res = engine.apply(list(items.values()), s)
    assert res.censored == 1
    assert engine.store.lookup_censored(sha256_file(pack / "Clean" / "bn.png"))


def test_copy_mode_leaves_source_untouched(engine, pack, tmp_path):
    before = sha256_file(pack / "Lewd" / "bn.png")
    items = classify(engine, pack)
    s = Settings(output_mode="copy", copy_destination=str(tmp_path / "out"))
    res = engine.apply(list(items.values()), s)
    assert res.censored == 3
    assert sha256_file(pack / "Lewd" / "bn.png") == before
    copied = tmp_path / "out" / "Pack" / "Lewd" / "bn.png"
    assert engine.store.lookup_censored(sha256_file(copied))
    assert (tmp_path / "out" / "Pack" / "Clean" / "bn.png").exists()
    with pytest.raises(ValueError):
        engine.apply(list(items.values()), Settings(output_mode="copy", copy_destination=str(pack.parent)))


def test_restore_after_pack_moved(engine, pack, tmp_path):
    engine.apply(list(classify(engine, pack).values()), Settings())
    moved = tmp_path / "Elsewhere"
    pack.rename(moved)
    res = engine.restore(list(classify(engine, moved).values()))
    assert res.restored == 3


def test_extract_zip_layouts(tmp_path):
    z1 = tmp_path / "one.zip"
    with zipfile.ZipFile(z1, "w") as zf:
        zf.writestr("Cool Pack/Song/song.sm", "#BANNER:bn.png;")
        zf.writestr("__MACOSX/Cool Pack/._x", "junk")
        zf.writestr("../../evil.txt", "nope")
    out = extract_zip(z1, tmp_path / "dest")
    assert out == tmp_path / "dest" / "Cool Pack"
    assert (out / "Song" / "song.sm").exists()
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "dest" / "__MACOSX").exists()

    z2 = tmp_path / "Loose Pack.zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr("Song1/a.sm", "")
        zf.writestr("Song2/b.sm", "")
    out = extract_zip(z2, tmp_path / "dest2")
    assert out == tmp_path / "dest2" / "Loose Pack" and (out / "Song2" / "b.sm").exists()
