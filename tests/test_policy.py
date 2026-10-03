from packfilter.policy import PRESETS_BY_KEY, Settings, strictness_to_threshold

GENERAL = {"general": 0.75, "sensitive": 0.11, "questionable": 0.07, "explicit": 0.07}
SENSITIVE = {"general": 0.06, "sensitive": 0.75, "questionable": 0.12, "explicit": 0.07}
QUESTIONABLE = {"general": 0.06, "sensitive": 0.1, "questionable": 0.73, "explicit": 0.11}
EXPLICIT = {"general": 0.06, "sensitive": 0.07, "questionable": 0.06, "explicit": 0.81}


def flagged(settings):
    return [name for name, s in (("g", GENERAL), ("s", SENSITIVE), ("q", QUESTIONABLE), ("e", EXPLICIT))
            if settings.should_censor(s, {"banner"})]


def test_presets_cover_increasing_ranges():
    s = Settings()
    s.apply_preset("strict")
    assert flagged(s) == ["s", "q", "e"]
    s.apply_preset("balanced")
    assert flagged(s) == ["q", "e"]
    s.apply_preset("explicit")
    assert flagged(s) == ["e"]


def test_strictness_slider_is_monotonic():
    values = [strictness_to_threshold(v) for v in range(0, 101, 10)]
    assert values == sorted(values, reverse=True)
    assert strictness_to_threshold(50) == 0.5
    s = Settings(min_level="questionable", strictness=100)
    assert "s" in flagged(s)  # very strict catches borderline sensitive images
    lenient = flagged(Settings(min_level="questionable", strictness=0))
    assert set(lenient) <= {"q", "e"}


def test_categories_and_overrides():
    s = Settings(categories=["jacket"])
    assert not s.should_censor(EXPLICIT, {"banner"})
    assert s.should_censor(EXPLICIT, {"banner", "jacket"})
    assert s.should_censor(GENERAL, {"banner"}, override=True)
    assert not s.should_censor(EXPLICIT, {"jacket"}, override=False)
    assert not s.should_censor(None, {"jacket"})


def test_settings_roundtrip_and_bad_values(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(style="pixelate", strictness=77, categories=["banner"])
    s.save(p)
    assert Settings.load(p) == s
    p.write_text('{"style": "nope", "min_level": "general", "categories": ["banner", "bogus"], "unknown": 1}')
    s2 = Settings.load(p)
    assert s2.style == "blur" and s2.min_level == "questionable" and s2.categories == ["banner"]
    p.write_text("not json")
    assert Settings.load(p) == Settings()


def test_all_presets_known():
    assert set(PRESETS_BY_KEY) == {"strict", "balanced", "explicit"}
