"""Tests for content extraction, caching, and content: search."""

import sys
import types

import pytest

from core import cache
import core.content as content
from core.content import extract_text, matched_line_context
from core.content.adapters import PdfAdapter
from core.index import FileEntry
from core.search import SearchEngine


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


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    cache._close_connection()
    monkeypatch.setattr(cache, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cache, "DB_FILE", tmp_path / "index.db")
    yield
    cache._close_connection()


def _file_entry(path, frn: int = 1) -> FileEntry:
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


def test_plain_text_adapter_extracts_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("alpha needle omega", encoding="utf-8")

    extracted = extract_text(str(path))

    assert extracted is not None
    assert extracted.extractor == "text"
    assert "needle" in extracted.text


def test_pdf_adapter_uses_pdfplumber(monkeypatch, tmp_path):
    path = tmp_path / "report.pdf"
    path.write_bytes(b"%PDF")

    class FakePdf:
        pages = [
            types.SimpleNamespace(extract_text=lambda: "first page"),
            types.SimpleNamespace(extract_text=lambda: "second needle"),
        ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_pdfplumber = types.SimpleNamespace(open=lambda _: FakePdf())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    assert PdfAdapter().extract(str(path)) == "first page\nsecond needle"


def test_content_cache_roundtrip_and_search(temp_cache):
    cache.upsert_content_cache(
        path="C:\\docs\\a.txt",
        size=12,
        modified_ms=100,
        extractor="text",
        text="alpha needle omega",
    )

    assert cache.get_content_cache("C:\\docs\\a.txt", 12, 100) == "alpha needle omega"
    assert cache.get_content_cache("C:\\docs\\a.txt", 13, 100) is None
    assert cache.search_content_cache("needle") == ["C:\\docs\\a.txt"]
    assert cache.get_content_cached_paths() == {"C:\\docs\\a.txt"}


def test_search_engine_content_search_reuses_cache(temp_cache, monkeypatch, tmp_path):
    path = tmp_path / "cached.txt"
    path.write_text("cached needle", encoding="utf-8")
    index = TempIndex([_file_entry(path)])
    engine = SearchEngine(index)

    assert [entry.name for entry in engine.search("content:needle")] == ["cached.txt"]

    def fail_extract(_path):
        raise AssertionError("cache miss")

    monkeypatch.setattr(content, "extract_text", fail_extract)

    assert [entry.name for entry in engine.search("content:needle")] == ["cached.txt"]


def test_search_engine_content_search_skips_cached_nonmatches(temp_cache, monkeypatch, tmp_path):
    matching = tmp_path / "matching.txt"
    skipped = tmp_path / "skipped.txt"
    matching.write_text("cached needle", encoding="utf-8")
    skipped.write_text("cached haystack", encoding="utf-8")
    entries = [_file_entry(matching, 1), _file_entry(skipped, 2)]
    for entry in entries:
        path = entry.get_path(None)
        cache.upsert_content_cache(
            path=path,
            size=entry.size,
            modified_ms=int(os_path_mtime(path) * 1000),
            extractor="text",
            text=matching.read_text(encoding="utf-8") if entry.name == "matching.txt" else "cached haystack",
        )

    def fail_extract(_path):
        raise AssertionError("cached nonmatch should not be extracted")

    monkeypatch.setattr(content, "extract_text", fail_extract)

    results = SearchEngine(TempIndex(entries)).search("content:needle")

    assert [entry.name for entry in results] == ["matching.txt"]


def test_matched_line_context_keeps_three_line_window():
    text = "\n".join(f"line {i}" for i in range(1, 10))

    context = matched_line_context(text, "line 5", context_lines=3)

    assert "  2: line 2" in context
    assert "> 5: line 5" in context
    assert "  8: line 8" in context
    assert "line 1" not in context
    assert "line 9" not in context


def os_path_mtime(path: str) -> float:
    import os
    return os.stat(path).st_mtime
