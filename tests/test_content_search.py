"""Tests for content extraction, caching, and content: search."""

import sys
import types

import pytest

from core import cache
import core.content as content
from core.content import adapter_diagnostics, extract_text, matched_line_context
from core.content.adapters import PdfAdapter
from core.content.indexer import ContentIndexJob, ContentIndexSettings
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


def test_source_code_extension_extracts_as_text(tmp_path):
    path = tmp_path / "component.tsx"
    path.write_text("export const needle = 'component';", encoding="utf-8")

    extracted = extract_text(str(path))

    assert extracted is not None
    assert extracted.extractor == "text"
    assert "needle" in extracted.text


def test_eml_adapter_extracts_headers_and_plain_body(tmp_path):
    path = tmp_path / "message.eml"
    path.write_text(
        "From: sender@example.com\n"
        "To: receiver@example.com\n"
        "Subject: Needle Update\n"
        "Date: Mon, 29 Jun 2026 12:00:00 -0400\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n\n"
        "The body contains needle text.\n",
        encoding="utf-8",
    )

    extracted = extract_text(str(path))

    assert extracted is not None
    assert extracted.extractor == "eml"
    assert "Subject: Needle Update" in extracted.text
    assert "body contains needle" in extracted.text


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
    stats = cache.get_content_cache_stats()
    assert stats["count"] == 1
    assert stats["text_bytes"] == len("alpha needle omega")


def test_content_cache_hits_return_ranked_snippets(temp_cache):
    long_text = f"{'prefix ' * 40}needle{' suffix ' * 40}"
    cache.upsert_content_cache(
        path="C:\\docs\\late.txt",
        size=12,
        modified_ms=100,
        extractor="text",
        text=long_text,
    )
    cache.upsert_content_cache(
        path="C:\\docs\\dense.txt",
        size=12,
        modified_ms=100,
        extractor="text",
        text="needle alpha needle beta needle",
    )

    hits = cache.search_content_cache_hits("needle")

    assert [hit.path for hit in hits] == ["C:\\docs\\dense.txt", "C:\\docs\\late.txt"]
    assert hits[0].rank > hits[1].rank
    assert hits[1].snippet.startswith("...")
    assert hits[1].snippet.endswith("...")
    assert "needle" in hits[1].snippet
    assert hits[1].snippet != long_text
    assert cache.search_content_cache("needle") == ["C:\\docs\\dense.txt", "C:\\docs\\late.txt"]


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


def test_search_engine_content_search_ranks_cached_hits(temp_cache, monkeypatch, tmp_path):
    dense = tmp_path / "dense.txt"
    sparse = tmp_path / "sparse.txt"
    dense.write_text("needle alpha needle beta needle", encoding="utf-8")
    sparse.write_text(f"{'prefix ' * 40}needle", encoding="utf-8")
    entries = [_file_entry(dense, 1), _file_entry(sparse, 2)]
    for entry in entries:
        path = entry.get_path(None)
        text = dense.read_text(encoding="utf-8")
        if entry.name == "sparse.txt":
            text = sparse.read_text(encoding="utf-8")
        cache.upsert_content_cache(
            path=path,
            size=entry.size,
            modified_ms=int(os_path_mtime(path) * 1000),
            extractor="text",
            text=text,
        )

    def fail_extract(_path):
        raise AssertionError("fresh cache hit should not be extracted")

    monkeypatch.setattr(content, "extract_text", fail_extract)

    results = SearchEngine(TempIndex(entries)).search("content:needle")

    assert [entry.name for entry in results] == ["dense.txt", "sparse.txt"]
    assert all(entry.content_snippet for entry in results)
    assert results[0].content_rank > results[1].content_rank


def test_matched_line_context_keeps_three_line_window():
    text = "\n".join(f"line {i}" for i in range(1, 10))

    context = matched_line_context(text, "line 5", context_lines=3)

    assert "  2: line 2" in context
    assert "> 5: line 5" in context
    assert "  8: line 8" in context
    assert "line 1" not in context
    assert "line 9" not in context


def test_adapter_diagnostics_reports_text_adapter():
    diagnostics = adapter_diagnostics()

    text_adapter = next(item for item in diagnostics if item.name == "text")
    assert text_adapter.available is True
    assert "txt" in text_adapter.extensions
    eml_adapter = next(item for item in diagnostics if item.name == "eml")
    assert eml_adapter.available is True
    assert "eml" in eml_adapter.extensions


def test_content_index_job_honors_roots_extensions_and_cache(temp_cache, tmp_path):
    root = tmp_path / "docs"
    other = tmp_path / "other"
    root.mkdir()
    other.mkdir()
    match = root / "match.txt"
    ignored_ext = root / "ignored.md"
    ignored_root = other / "outside.txt"
    match.write_text("alpha needle omega", encoding="utf-8")
    ignored_ext.write_text("needle", encoding="utf-8")
    ignored_root.write_text("needle", encoding="utf-8")
    entries = [_file_entry(path, idx) for idx, path in enumerate([match, ignored_ext, ignored_root], start=1)]

    settings = ContentIndexSettings(
        roots=(str(root),),
        extensions=frozenset({"txt"}),
        max_cache_bytes=10_000,
    )
    stats = ContentIndexJob(settings).run(entries, lambda entry: entry.get_path(None))

    assert stats.indexed == 1
    assert stats.skipped == 2
    assert cache.search_content_cache("needle") == [str(match)]


def test_content_index_job_enforces_cache_quota(temp_cache, tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("alpha needle omega", encoding="utf-8")
    entry = _file_entry(path)
    settings = ContentIndexSettings(max_cache_bytes=5)

    stats = ContentIndexJob(settings).run([entry], lambda entry: entry.get_path(None))

    assert stats.indexed == 0
    assert stats.quota_skipped == 1
    assert cache.search_content_cache("needle") == []


def test_content_index_job_records_adapter_failures(temp_cache, tmp_path, monkeypatch):
    path = tmp_path / "broken.txt"
    path.write_text("needle", encoding="utf-8")
    entry = _file_entry(path)
    monkeypatch.setattr("core.content.indexer.extract_text", lambda *_args, **_kwargs: None)

    stats = ContentIndexJob(ContentIndexSettings()).run([entry], lambda entry: entry.get_path(None))

    assert stats.failed == 1
    assert stats.adapter_failures["text"] == 1


def os_path_mtime(path: str) -> float:
    import os
    return os.stat(path).st_mtime
