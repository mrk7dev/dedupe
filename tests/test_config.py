from app import config


def test_discover_browse_roots_only_existing_candidates(tmp_path):
    vol1 = tmp_path / "volume1"
    vol2 = tmp_path / "volume2"
    vol1.mkdir()
    vol2.mkdir()
    missing = tmp_path / "volume3"  # never created

    found = config.discover_browse_roots(candidates=[str(vol1), str(vol2), str(missing)])

    assert found == [vol1.resolve(), vol2.resolve()]


def test_discover_browse_roots_extra_appends_without_duplicating(tmp_path):
    vol1 = tmp_path / "volume1"
    extra_dir = tmp_path / "extra"
    vol1.mkdir()
    extra_dir.mkdir()

    found = config.discover_browse_roots(candidates=[str(vol1)], extra=f"{extra_dir}:{vol1}")

    assert found == [vol1.resolve(), extra_dir.resolve()]


def test_default_volume_candidates_shape():
    candidates = config._default_volume_candidates()
    assert "/volume1" in candidates
    assert "/volumeUSB1" in candidates
