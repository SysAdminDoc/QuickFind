"""Tests for opt-in archive member search."""

import zipfile

import py7zr

from core.index import FileEntry
from core.search import SearchEngine, SearchOptions, SortField, SortOrder


class TempIndex:
    def __init__(self, entries):
        self.all_entries = entries

    def get_entry(self, drive: str, frn: int):
        return None

    def resolve_path(self, drive: str, frn: int) -> str:
        for entry in self.all_entries:
            if entry.drive == drive and entry.frn == frn:
                return entry._path
        return f"{drive}:\\"

    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        return f"{drive}:\\"


def _archive_entry(path, frn: int = 1) -> FileEntry:
    entry = FileEntry(
        frn=frn,
        parent_frn=5,
        name=path.name,
        drive="C",
        size=path.stat().st_size,
    )
    entry._path = str(path)
    entry._stat_loaded = True
    return entry


def test_archive_search_returns_zip_members(tmp_path):
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("docs/report.txt", "hello")
        zf.writestr("images/logo.png", b"png")

    index = TempIndex([_archive_entry(archive)])
    results = SearchEngine(index).search("archive:report")

    assert [entry.name for entry in results] == ["report.txt"]
    assert results[0].get_path(index).endswith("bundle.zip\\docs\\report.txt")
    assert results[0].size == 5
    assert results[0]._stat_loaded is True


def test_archive_search_returns_7z_members(tmp_path):
    source = tmp_path / "server.log"
    source.write_text("started", encoding="utf-8")
    archive = tmp_path / "logs.7z"
    with py7zr.SevenZipFile(archive, "w") as zf:
        zf.write(source, "nested/server.log")

    index = TempIndex([_archive_entry(archive)])
    results = SearchEngine(index).search("archive:server")

    assert [entry.name for entry in results] == ["server.log"]
    assert results[0].get_path(index).endswith("logs.7z\\nested\\server.log")


def test_archive_search_respects_inner_extension_filter(tmp_path):
    archive = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("docs/readme.txt", "docs")
        zf.writestr("logs/readme.log", "logs")

    index = TempIndex([_archive_entry(archive)])
    results = SearchEngine(index).search("archive:readme ext:log")

    assert [entry.get_path(index) for entry in results] == [
        f"{archive}\\logs\\readme.log"
    ]


def test_archive_search_respects_max_results(tmp_path):
    archive = tmp_path / "many.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("one.txt", "one")
        zf.writestr("two.txt", "two")
        zf.writestr("three.txt", "three")

    options = SearchOptions(
        max_results=2,
        sort_by=SortField.NAME,
        sort_order=SortOrder.ASCENDING,
    )
    index = TempIndex([_archive_entry(archive)])
    results = SearchEngine(index).search("archive: ext:txt", base_options=options)

    assert len(results) == 2


def test_archive_search_skips_corrupt_archives(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a zip")

    index = TempIndex([_archive_entry(archive)])

    assert SearchEngine(index).search("archive:") == []
