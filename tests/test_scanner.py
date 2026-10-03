from packfilter.scanner import scan_path

from conftest import make_image, write_sm


def by_name(pack):
    return {(e.song, e.path.name): e.categories for e in pack.images}


def test_songs_folder_groups_packs_and_reads_tags(tmp_path):
    songs = tmp_path / "Songs"
    s1 = songs / "Pack A" / "Song 1"
    write_sm(s1, title="First Song", banner="bn.png", background="bg.jpg", jacket="jk.png", cdtitle="cd.png")
    for n in ("bn.png", "bg.jpg", "jk.png", "cd.png"):
        make_image(s1 / n)
    make_image(songs / "Pack A" / "Pack A.png")
    s2 = songs / "Pack B" / "Song 2"
    write_sm(s2, ext="ssc", title="Second", banner="banner.png")
    make_image(s2 / "banner.png")
    make_image(s2 / "random-art.png")

    packs = {p.name: p for p in scan_path(songs)}
    assert set(packs) == {"Pack A", "Pack B"}
    a = by_name(packs["Pack A"])
    assert a[("First Song", "bn.png")] == {"banner"}
    assert a[("First Song", "bg.jpg")] == {"background"}
    assert a[("First Song", "jk.png")] == {"jacket"}
    assert a[("First Song", "cd.png")] == {"cdtitle"}
    assert a[("(pack banner)", "Pack A.png")] == {"pack"}
    b = by_name(packs["Pack B"])
    assert b[("Second", "banner.png")] == {"banner"}
    assert b[("Second", "random-art.png")] == {"other"}
    assert packs["Pack A"].song_count == 1


def test_single_pack_and_single_song_inputs(tmp_path):
    pack = tmp_path / "My Pack"
    write_sm(pack / "S", banner="bn.png")
    make_image(pack / "S" / "bn.png")
    assert [p.name for p in scan_path(pack)] == ["My Pack"]
    only_song = scan_path(pack / "S")
    assert len(only_song) == 1 and [e.path.name for e in only_song[0].images] == ["bn.png"]


def test_case_mismatch_and_subfolders_are_resolved_once(tmp_path):
    song = tmp_path / "P" / "S"
    write_sm(song, banner="IMG\\BN.PNG", background="Bg.JPG")
    make_image(song / "img" / "bn.png")
    make_image(song / "bg.jpg")
    images = scan_path(tmp_path / "P")[0].images
    names = sorted((e.path.relative_to(song).as_posix(), tuple(e.categories)) for e in images)
    assert names == [("bg.jpg", ("background",)), ("img/bn.png", ("banner",))]


def test_bgchanges_and_filename_guessing(tmp_path):
    song = tmp_path / "P" / "S"
    write_sm(song, bgchanges="0.000=change.png=1.000=0=0=1,\n99999=-nosongbg-=1.000=0=0=0")
    make_image(song / "change.png")
    make_image(song / "song-bn.png")
    make_image(song / "jacket.jpg")
    cats = {e.path.name: e.categories for e in scan_path(tmp_path / "P")[0].images}
    assert cats == {"change.png": {"background"}, "song-bn.png": {"banner"}, "jacket.jpg": {"jacket"}}


def test_osu_and_unknown_game_folders(tmp_path):
    osu = tmp_path / "osu" / "123 Map"
    osu.mkdir(parents=True)
    (osu / "map [Hard].osu").write_text('[Metadata]\nTitle:Cool Map\n[Events]\n0,0,"back ground.jpg",0,0\n')
    make_image(osu / "back ground.jpg")
    pack = scan_path(tmp_path / "osu")[0]
    assert [(e.song, e.path.name, e.categories) for e in pack.images] == [("Cool Map", "back ground.jpg", {"background"})]

    other = tmp_path / "SomeOtherGame"
    make_image(other / "a" / "cover.png")
    make_image(other / "b.txt.png")
    (other / "notes.txt").write_text("x")
    packs = scan_path(other)
    assert len(packs) == 1 and len(packs[0].images) == 2


def test_ignores_macos_junk(tmp_path):
    song = tmp_path / "P" / "S"
    write_sm(song, banner="bn.png")
    make_image(song / "bn.png")
    (song / "._bn.png").write_bytes(b"junk")
    make_image(tmp_path / "P" / "__MACOSX" / "S" / "bn.png")
    images = scan_path(tmp_path / "P")[0].images
    assert [e.path.name for e in images] == ["bn.png"]
