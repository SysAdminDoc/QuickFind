"""Tests for report-grade result export in CSV, JSON, and HTML formats."""

import json

from core.result_export import (
    ExportMetadata,
    ExportableResult,
    export_csv,
    export_html,
    export_json,
)


def _sample_results() -> list[ExportableResult]:
    return [
        ExportableResult(
            name="report.pdf",
            path="C:\\docs\\report.pdf",
            parent_path="C:\\docs",
            kind="PDF file",
            extension=".pdf",
            size_bytes=102400,
            size_display="100.0 KB",
            date_modified="2026-06-15 10:30",
        ),
        ExportableResult(
            name="notes.txt",
            path="C:\\docs\\notes.txt",
            parent_path="C:\\docs",
            kind="TXT file",
            extension=".txt",
            size_bytes=256,
            size_display="256 B",
            date_modified="2026-07-01 08:00",
            content_snippet="quarterly budget review",
        ),
    ]


def _sample_metadata() -> ExportMetadata:
    return ExportMetadata(
        query="*.pdf",
        result_count=2,
        export_format="csv",
        app_version="0.8.52",
    )


def test_csv_export_includes_header_and_rows():
    csv_text = export_csv(_sample_results())
    lines = csv_text.strip().split("\n")
    assert lines[0].startswith("Name,")
    assert len(lines) == 3
    assert "report.pdf" in lines[1]
    assert "notes.txt" in lines[2]


def test_csv_export_escapes_commas_in_paths():
    results = [ExportableResult(
        name="data,file.csv",
        path="C:\\path,with,commas\\data,file.csv",
        parent_path="C:\\path,with,commas",
        kind="CSV file",
        extension=".csv",
    )]
    csv_text = export_csv(results)
    assert '"data,file.csv"' in csv_text or "data,file.csv" in csv_text


def test_json_export_includes_metadata_and_results():
    results = _sample_results()
    meta = _sample_metadata()
    json_text = export_json(results, meta)
    data = json.loads(json_text)
    assert data["count"] == 2
    assert data["query"] == "*.pdf"
    assert data["app_version"] == "0.8.52"
    assert data["results"][0]["name"] == "report.pdf"
    assert data["results"][0]["size_bytes"] == 102400


def test_json_export_includes_snippet_only_when_present():
    results = _sample_results()
    json_text = export_json(results)
    data = json.loads(json_text)
    assert "content_snippet" not in data["results"][0]
    assert data["results"][1]["content_snippet"] == "quarterly budget review"


def test_html_export_escapes_special_characters():
    results = [ExportableResult(
        name="<script>alert(1)</script>.txt",
        path="C:\\xss\\<script>.txt",
        parent_path="C:\\xss",
        kind="TXT file",
        extension=".txt",
    )]
    html_text = export_html(results)
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text


def test_html_export_includes_query_metadata():
    results = _sample_results()
    meta = _sample_metadata()
    html_text = export_html(results, meta)
    assert "*.pdf" in html_text
    assert "2 results" in html_text
    assert "QuickFind Results" in html_text


def test_html_export_includes_snippet_column_when_present():
    results = _sample_results()
    html_text = export_html(results)
    assert "Snippet" in html_text
    assert "quarterly budget review" in html_text


def test_html_export_omits_snippet_column_when_absent():
    results = [ExportableResult(
        name="a.txt",
        path="C:\\a.txt",
        parent_path="C:\\",
        kind="TXT file",
        extension=".txt",
    )]
    html_text = export_html(results)
    assert "Snippet" not in html_text


def test_csv_export_handles_empty_results():
    csv_text = export_csv([])
    lines = csv_text.strip().split("\n")
    assert len(lines) == 1
    assert "Name" in lines[0]
