"""End-to-end tests against the real anime_dbrating model and real NSFW sample covers.

Needs network on first run (model + the imgutils sample images). Skipped offline.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from packfilter.engine import Engine, items_from_packs
from packfilter.model import RatingModel, ensure_model
from packfilter.policy import Settings
from packfilter.store import sha256_file

CACHE = Path(__file__).resolve().parents[1] / ".pytest_cache" / "samples"


@pytest.fixture(scope="module")
def test_packs(tmp_path_factory):
    import make_test_packs
    try:
        return make_test_packs.build(tmp_path_factory.mktemp("packs"), CACHE)
    except OSError as exc:  # no network
        pytest.skip(f"sample images unavailable: {exc}")


@pytest.fixture
def model_ready():
    try:
        ensure_model()
    except Exception as exc:
        pytest.skip(f"model unavailable: {exc}")


def test_matches_reference_imgutils(model_ready, test_packs):
    # Run imgutils in a clean interpreter: PySide6 (imported by the GUI tests) installs an
    # import hook that breaks the ``six`` package imgutils depends on.
    files = sorted(str(f) for f in CACHE.glob("*/*.jpg"))
    code = ("import json, sys\n"
            "from imgutils.validate import anime_dbrating_score\n"
            "print(json.dumps([anime_dbrating_score(f) for f in sys.argv[1:]]))")
    proc = subprocess.run([sys.executable, "-c", code, *files], capture_output=True, text=True)
    if proc.returncode != 0 and "ModuleNotFoundError" in proc.stderr:
        pytest.skip("imgutils not installed (pip install -e .[reference])")
    assert proc.returncode == 0, proc.stderr
    refs = json.loads(proc.stdout.strip().splitlines()[-1])
    model = RatingModel()
    for f, ref in zip(files, refs):
        ours = model.predict(f)
        assert all(abs(ours[k] - ref[k]) < 1e-4 for k in ref), f


def test_sample_ratings_match_ground_truth(model_ready, test_packs):
    model = RatingModel()
    for rating in ("general", "sensitive", "questionable", "explicit"):
        for f in sorted((CACHE / rating).glob("*.jpg")):
            scores = model.predict(f)
            assert max(scores, key=scores.get) == rating, (f, scores)


def test_censors_lewd_packs_end_to_end(model_ready, test_packs):
    engine = Engine()
    songs = test_packs["songs"]
    items = items_from_packs(engine.collect([songs]))
    engine.classify(items, Settings().model)
    by_rel = {it.path.relative_to(songs).as_posix(): it for it in items}
    assert by_rel["Mixed Bag Pack/Broken Image/bn.png"].error

    s = Settings()  # balanced
    flagged = {k for k, it in by_rel.items() if it.will_censor(s)}
    # Nothing in the clean pack, every explicit jacket/background, hidden extras too.
    assert not any(k.startswith("Clean Anime Pack/") for k in flagged)
    for i in range(1, 5):
        assert f"Lewd Covers Pack/Explicit {i}/jacket.png" in flagged
        assert f"Lewd Covers Pack/Questionable {i}/bg.jpg" in flagged or i == 2
        assert f"Lewd Covers Pack/Sensitive {i}/jacket.png" not in flagged
    for k in ("Mixed Bag Pack/Explicit BG Change/bgchange1.png", "Mixed Bag Pack/No Tags Song/notags-bg.jpg",
              "Mixed Bag Pack/日本語の曲/背景.jpg", "Mixed Bag Pack/Gif Banner/bn.gif",
              "Lewd Covers Pack/Lewd Covers Pack.png", "osu! Beatmaps/123 Artist - Lewd Map/lewd bg.jpg"):
        assert k in flagged, k
    assert "Mixed Bag Pack/Explicit BG Change/bg.jpg" not in flagged

    strict = Settings()
    strict.apply_preset("strict")
    explicit_only = Settings()
    explicit_only.apply_preset("explicit")
    n_strict = sum(it.will_censor(strict) for it in items)
    n_explicit = sum(it.will_censor(explicit_only) for it in items)
    assert n_strict > len(flagged) > n_explicit > 0

    originals = {it.path: sha256_file(it.path) for it in items if not it.error}
    res = engine.apply(items, s)
    assert res.censored == len(flagged) and not res.errors

    # Censored covers should no longer look lewd to the model.
    model = RatingModel()
    for k in flagged:
        scores = model.predict(songs / k)
        assert scores["questionable"] + scores["explicit"] < 0.5, (k, scores)

    rescanned = items_from_packs(engine.collect([songs]))
    engine.classify(rescanned, s.model)
    assert sum(it.censored for it in rescanned) == len(flagged)
    engine.restore(rescanned)
    assert {p: sha256_file(p) for p in originals} == originals


def test_exported_zips_contain_no_lewd_covers(model_ready, test_packs, tmp_path):
    import zipfile
    engine = Engine()
    zip_dir = tmp_path / "unzipped-input"
    from packfilter.engine import extract_zip
    inputs = [test_packs["songs"], extract_zip(test_packs["zip"], zip_dir)]
    items = items_from_packs(engine.collect(inputs))
    engine.classify(items, Settings().model)
    before = {it.path: sha256_file(it.path) for it in items if not it.error}

    out = tmp_path / "Downloads"
    res = engine.export_zips(items, Settings(), out)
    names = sorted(z.name for z in res.output_roots)
    assert names == ["Lewd Covers Pack (filtered).zip", "Mixed Bag Pack (filtered).zip",
                     "Zipped Lewd Pack (filtered).zip", "osu! Beatmaps (filtered).zip"]
    assert {p: sha256_file(p) for p in before} == before

    extracted = tmp_path / "extracted"
    for z in res.output_roots:
        with zipfile.ZipFile(z) as zf:
            zf.extractall(extracted)
    rescanned = items_from_packs(Engine().collect([extracted]))
    Engine().classify(rescanned, Settings().model)
    assert len(rescanned) > 40
    assert not [it.path for it in rescanned if it.will_censor(Settings())]
