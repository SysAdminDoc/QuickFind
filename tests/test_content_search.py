"""Tests for content extraction, caching, and content: search."""

import sys
import types

import pytest

from core import cache
import core.content as content
import core.content.adapters as adapters_module
from core.content import adapter_diagnostics, extract_text, matched_line_context
from core.content.adapters import PdfAdapter, WindowsSearchAdapter
from core.content.sandbox import ExtractionOutcome
from core.content.indexer import ContentIndexJob, ContentIndexSettings, _path_within_roots
from core.index import FileEntry


def _norm(path):
    import os
    return os.path.normcase(os.path.abspath(path))


def test_content_scope_recursive_and_single_level_globs():
    # ** is recursive; * is one level; a bare directory is a prefix.
    assert _path_within_roots(r"C:\docs\a\b\report.pdf", (_norm(r"C:\docs\**.pdf"),))
    assert not _path_within_roots(r"C:\docs\a\b\report.pdf", (_norm(r"C:\docs\*.pdf"),))
    assert _path_within_roots(r"C:\docs\report.pdf", (_norm(r"C:\docs\*.pdf"),))
    assert _path_within_roots(r"C:\docs\a\b\x.txt", (_norm(r"C:\docs"),))
    assert not _path_within_roots(r"C:\docs\report.txt", (_norm(r"C:\docs\**.pdf"),))
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


def test_pdf_adapter_uses_optional_ocr_when_pdf_text_is_empty(monkeypatch, tmp_path):
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF")

    class EmptyPdf:
        pages = [types.SimpleNamespace(extract_text=lambda: "")]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeBitmap:
        def to_pil(self):
            return object()

    class FakePage:
        def render(self, scale=1):
            return FakeBitmap()

    class FakePdfDocument:
        def __init__(self, _path):
            self.closed = False

        def __iter__(self):
            return iter([FakePage()])

        def close(self):
            self.closed = True

    fake_pdfplumber = types.SimpleNamespace(open=lambda _: EmptyPdf())
    fake_pdfium = types.SimpleNamespace(PdfDocument=FakePdfDocument)
    fake_tesseract = types.SimpleNamespace(image_to_string=lambda _image: "ocr needle")
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)
    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)

    assert PdfAdapter().extract(str(path)) == "ocr needle"


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
    assert stats["extractors"] == [
        {"name": "text", "count": 1, "text_bytes": len("alpha needle omega")}
    ]


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
    ocr_adapter = next(item for item in diagnostics if item.name == "tesseract-ocr")
    assert "pdf" in ocr_adapter.extensions
    windows_adapter = next(item for item in diagnostics if item.name == "windows-ifilter")
    assert "doc" in windows_adapter.extensions
    assert "pdf" in windows_adapter.extensions


def test_windows_search_adapter_gracefully_disables_off_windows(monkeypatch):
    monkeypatch.setattr(adapters_module.sys, "platform", "linux")

    available, detail = WindowsSearchAdapter.availability()

    assert available is False
    assert "Windows Search" in detail
    assert adapters_module.adapter_for_path("C:\\docs\\legacy.doc") is None


def test_windows_search_adapter_extracts_indexed_content_and_properties(monkeypatch):
    monkeypatch.setattr(adapters_module.sys, "platform", "win32")
    calls = {"initialize": 0, "uninitialize": 0}

    class FakeField:
        def __init__(self, value):
            self.Value = value

    class FakeFields:
        values = {
            "System.Search.Contents": "Body needle text",
            "System.Title": "Quarterly Plan",
            "System.Subject": "Operations",
            "System.Author": ("Alice", "Bob"),
            "System.Keywords": ("search", "ifilter"),
            "System.Comment": None,
        }

        def Item(self, name):
            return FakeField(self.values.get(name))

    class FakeRecordset:
        EOF = False
        Fields = FakeFields()

        def __init__(self):
            self.closed = False

        def Close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.sql = ""
            self.closed = False

        def Open(self, connection_string):
            self.connection_string = connection_string

        def Execute(self, sql):
            self.sql = sql
            return FakeRecordset()

        def Close(self):
            self.closed = True

    connection = FakeConnection()
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = lambda: calls.__setitem__("initialize", calls["initialize"] + 1)
    pythoncom.CoUninitialize = lambda: calls.__setitem__("uninitialize", calls["uninitialize"] + 1)
    win32com = types.ModuleType("win32com")
    win32com.__path__ = []
    client = types.ModuleType("win32com.client")
    client.Dispatch = lambda name: connection
    win32com.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)

    extracted = WindowsSearchAdapter().extract("C:\\docs\\O'Hara.doc", max_chars=200)

    assert "Body needle text" in extracted
    assert "Title: Quarterly Plan" in extracted
    assert "Author: Alice, Bob" in extracted
    assert "System.Search.Contents" in connection.sql
    assert "O''Hara.doc" in connection.sql
    assert calls == {"initialize": 1, "uninitialize": 1}


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


def test_content_search_descends_into_archive_members(temp_cache, tmp_path):
    import zipfile
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("notes/report.txt", "alpha zipneedle omega")
        archive.writestr("image.bin", "binary blob, unsupported extension")
    archive_entry = _file_entry(zip_path)

    settings = ContentIndexSettings(extensions=frozenset({"txt"}), max_cache_bytes=100_000)
    stats = ContentIndexJob(settings).run([archive_entry], lambda e: e.get_path(None))
    # Only the .txt member is content-supported.
    assert stats.indexed == 1

    engine = SearchEngine(TempIndex([archive_entry]))
    results = engine.search("content:zipneedle")
    names = [e.name for e in results]
    assert "report.txt" in names
    member = next(e for e in results if e.name == "report.txt")
    assert member.get_path(None).endswith("bundle.zip\\notes\\report.txt")


def test_archive_member_content_dropped_when_archive_changes(temp_cache, tmp_path):
    import os
    import zipfile
    zip_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.txt", "alpha zipneedle omega")
    archive_entry = _file_entry(zip_path)
    ContentIndexJob(ContentIndexSettings(extensions=frozenset({"txt"}))).run(
        [archive_entry], lambda e: e.get_path(None)
    )
    # Mutate the archive so its size/mtime no longer match the cached freshness.
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a.txt", "completely different content here now")
    future = zip_path.stat().st_mtime + 100
    os.utime(zip_path, (future, future))

    results = SearchEngine(TempIndex([archive_entry])).search("content:zipneedle")
    assert [e for e in results if e.name == "a.txt"] == []


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
    monkeypatch.setattr(
        "core.content.indexer.extract_text_with_diagnostics",
        lambda *_args, **_kwargs: ExtractionOutcome(None, "text", "parser failed"),
    )

    stats = ContentIndexJob(ContentIndexSettings()).run([entry], lambda entry: entry.get_path(None))

    assert stats.failed == 1
    assert stats.adapter_failures["text"] == 1
    assert stats.last_error == "parser failed"


def test_content_index_job_records_sandbox_timeout(temp_cache, tmp_path, monkeypatch):
    path = tmp_path / "slow.txt"
    path.write_text("needle", encoding="utf-8")
    entry = _file_entry(path)
    monkeypatch.setattr(
        "core.content.indexer.extract_text_with_diagnostics",
        lambda *_args, **_kwargs: ExtractionOutcome(
            None,
            "text",
            "Worker timed out after 0.01s",
            timed_out=True,
        ),
    )

    stats = ContentIndexJob(ContentIndexSettings()).run([entry], lambda entry: entry.get_path(None))

    assert stats.failed == 1
    assert stats.adapter_failures["text:timeout"] == 1
    assert "timed out" in stats.last_error


def os_path_mtime(path: str) -> float:
    import os
    return os.stat(path).st_mtime
