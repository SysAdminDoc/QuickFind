"""Tests for Everything CSV import hardening."""

import json

import pytest

import core.everything_import as importer


def _redirect_config(monkeypatch, tmp_path):
    monkeypatch.setattr(importer, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(importer, "FILTERS_FILE", tmp_path / "filters.json")
    monkeypatch.setattr(importer, "BOOKMARKS_FILE", tmp_path / "bookmarks.json")


def test_filters_csv_rejects_rows_with_extra_columns(tmp_path):
    csv_path = tmp_path / "Filters.csv"
    csv_path.write_text(
        "Name,Search\n"
        "Docs,ext:pdf,unexpected\n",
        encoding="utf-8",
    )

    with pytest.raises(importer.EverythingImportError, match="too many columns"):
        importer.import_everything_filters(str(csv_path))


def test_bookmarks_csv_rejects_missing_required_headers(tmp_path):
    csv_path = tmp_path / "Bookmarks.csv"
    csv_path.write_text("Name\nDocs\n", encoding="utf-8")

    with pytest.raises(importer.EverythingImportError, match="missing required columns"):
        importer.import_everything_bookmarks(str(csv_path))


def test_filter_import_normalizes_and_merges_atomically(monkeypatch, tmp_path):
    _redirect_config(monkeypatch, tmp_path)
    importer.FILTERS_FILE.write_text(json.dumps([{"name": "Logs", "extensions": ["log"]}]), encoding="utf-8")

    count = importer.save_imported_filters([
        {"name": "Docs", "extensions": [".PDF", "pdf"], "macro": "ext:pdf"},
        {"name": "Logs", "extensions": ["txt"]},
    ])

    data = json.loads(importer.FILTERS_FILE.read_text(encoding="utf-8"))
    assert count == 2
    assert data == [
        {
            "name": "Logs",
            "extensions": ["log"],
            "min_size": 0,
            "max_size": 0,
            "files_only": False,
            "folders_only": False,
            "macro": "",
            "exclude_paths": [],
        },
        {
            "name": "Docs",
            "extensions": ["pdf"],
            "min_size": 0,
            "max_size": 0,
            "files_only": False,
            "folders_only": False,
            "macro": "ext:pdf",
            "exclude_paths": [],
        },
    ]
    assert not importer.FILTERS_FILE.with_name("filters.json.tmp").exists()


def test_invalid_existing_filter_json_is_not_replaced(monkeypatch, tmp_path):
    _redirect_config(monkeypatch, tmp_path)
    original = "{not json"
    importer.FILTERS_FILE.write_text(original, encoding="utf-8")

    with pytest.raises(importer.EverythingImportError, match="not valid JSON"):
        importer.save_imported_filters([{"name": "Docs", "extensions": ["pdf"]}])

    assert importer.FILTERS_FILE.read_text(encoding="utf-8") == original


def test_invalid_incoming_bookmark_is_not_written(monkeypatch, tmp_path):
    _redirect_config(monkeypatch, tmp_path)
    original = json.dumps([{"name": "Keep", "query": "*.log"}])
    importer.BOOKMARKS_FILE.write_text(original, encoding="utf-8")

    with pytest.raises(importer.EverythingImportError, match="invalid sort_column"):
        importer.save_imported_bookmarks([{"name": "Bad", "query": "*.py", "sort_column": "wrong"}])

    assert importer.BOOKMARKS_FILE.read_text(encoding="utf-8") == original


def test_valid_bookmark_csv_imports_normalized_records(tmp_path):
    csv_path = tmp_path / "Bookmarks.csv"
    csv_path.write_text(
        "Name,Case,Regex,Search,Sort,Descending,Macro\n"
        "Source,1,0,ext:py,Path,1,\n",
        encoding="utf-8",
    )

    bookmarks = importer.import_everything_bookmarks(str(csv_path))

    assert bookmarks == [
        {
            "name": "Source",
            "query": "ext:py",
            "slot": "",
            "filter_name": "Everything",
            "sort_column": 1,
            "sort_ascending": False,
            "match_case": True,
            "use_regex": False,
            "folder": "",
            "created": bookmarks[0]["created"],
        }
    ]
    assert bookmarks[0]["created"]
