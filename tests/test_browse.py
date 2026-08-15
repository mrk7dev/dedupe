from pathlib import Path

import pytest

from app import browse, config


@pytest.fixture
def roots(tmp_path, monkeypatch):
    volume1 = tmp_path / "volume1"
    usb1 = tmp_path / "volumeUSB1"
    (volume1 / "photos" / "2023").mkdir(parents=True)
    (volume1 / "documents").mkdir()
    (volume1 / ".hidden").mkdir()
    usb1.mkdir()

    monkeypatch.setattr(config, "BROWSE_ROOTS", [volume1, usb1])
    return {"volume1": volume1, "usb1": usb1, "tmp_path": tmp_path}


def test_list_roots_reports_kind_and_has_children(roots):
    entries = {e.path: e for e in browse.list_roots()}

    assert entries[str(roots["volume1"])].kind == "internal"
    assert entries[str(roots["volume1"])].has_children is True
    assert entries[str(roots["usb1"])].kind == "external"
    assert entries[str(roots["usb1"])].has_children is False


def test_list_children_returns_sorted_visible_dirs(roots):
    entries = browse.list_children(str(roots["volume1"]))
    names = [e.name for e in entries]

    assert names == ["documents", "photos"]  # sorted, .hidden filtered out
    photos_entry = next(e for e in entries if e.name == "photos")
    assert photos_entry.has_children is True


def test_list_children_none_returns_roots(roots):
    assert [e.path for e in browse.list_children(None)] == [e.path for e in browse.list_roots()]


def test_list_children_rejects_path_outside_browse_roots(roots):
    outside = roots["tmp_path"] / "not-mounted"
    outside.mkdir()
    with pytest.raises(PermissionError):
        browse.list_children(str(outside))


def test_list_children_rejects_non_directory(roots):
    a_file = roots["volume1"] / "documents" / "a.txt"
    a_file.write_text("hi")
    with pytest.raises(NotADirectoryError):
        browse.list_children(str(a_file))


def test_is_under_browse_roots(roots):
    assert browse.is_under_browse_roots(roots["volume1"])
    assert browse.is_under_browse_roots(roots["volume1"] / "photos" / "2023")
    assert not browse.is_under_browse_roots(Path(roots["tmp_path"]) / "elsewhere")
