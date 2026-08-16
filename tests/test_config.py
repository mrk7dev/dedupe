from app import config


def test_read_text_returns_stripped_contents(tmp_path):
    f = tmp_path / "value.txt"
    f.write_text("  abc123  \n")
    assert config._read_text(f) == "abc123"


def test_read_text_returns_none_for_missing_path(tmp_path):
    assert config._read_text(tmp_path / "does-not-exist") is None


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


def test_version_info_degrades_gracefully_outside_docker():
    # /app/GIT_SHA etc. only exist inside the built Docker image (baked in by
    # the Dockerfile) — locally these should fall back cleanly, not raise.
    assert config.GIT_COMMIT == "unknown"
    assert config.GIT_DIRTY is False
    assert config.BUILT_AT is None
    assert config.APP_VERSION  # non-empty, from importlib.metadata or "unknown"
