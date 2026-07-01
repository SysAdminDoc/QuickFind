"""Tests for opt-in archive member search."""

import os
import time
import zipfile

import py7zr
import pytest

import core.archives as archives_mod
import core.cache as cache_mod
from core.worker_isolation import WorkerOutcome
from core.index import FileEntry
from core.search import SearchEngine, SearchOptions, SortField, SortOrder


@pytest.fixture(autouse=True)
def isolated_archive_cache(monkeypatch, tmp_path):
    cache_mod._close_connection()
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cache_mod, "CONFIG_DIR", cache_dir)
    monkeypatch.setattr(cache_mod, "DB_FILE", cache_dir / "index.db")
    monkeypatch.setattr(cache_mod, "OLD_CACHE_FILE", cache_dir / "index_cache.bin")
    yield
    cache_mod._close_connection()


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


def test_archive_search_reuses_cached_members_when_unchanged(tmp_path, monkeypatch):
    archive = tmp_path / "cached.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("docs/report.txt", "hello")

    index = TempIndex([_archive_entry(archive)])
    assert [entry.name for entry in SearchEngine(index).search("archive:report")] == ["report.txt"]

    def fail_if_reopened(_archive_path):
        raise AssertionError("archive should be served from cache")

    monkeypatch.setattr(archives_mod, "_iter_zip_members", fail_if_reopened)

    results = SearchEngine(index).search("archive:report")

    assert [entry.name for entry in results] == ["report.txt"]


def test_archive_search_invalidates_cache_when_archive_changes(tmp_path):
    archive = tmp_path / "changing.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("old.txt", "old")

    index = TempIndex([_archive_entry(archive)])
    assert [entry.name for entry in SearchEngine(index).search("archive:old")] == ["old.txt"]

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("new.txt", "new content")
    future = time.time() + 5
    os.utime(archive, (future, future))

    results = SearchEngine(index).search("archive:new")

    assert [entry.name for entry in results] == ["new.txt"]
    assert SearchEngine(index).search("archive:old") == []


def test_archive_reader_reports_sandbox_timeout(monkeypatch):
    monkeypatch.setattr(
        archives_mod,
        "run_in_worker",
        lambda *_args, **_kwargs: WorkerOutcome(
            ok=False,
            error="Worker timed out after 0.01s",
            timed_out=True,
        ),
    )

    outcome = archives_mod.read_archive_members_sandboxed(
        "bundle.zip",
        "zip",
        timeout_seconds=0.01,
    )

    assert outcome.members == []
    assert outcome.timed_out is True
    assert "timed out" in outcome.error
