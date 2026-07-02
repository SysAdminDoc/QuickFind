"""Tests for launcher popup query parsing, calculator, and preview text."""

import pytest

from gui.launcher_popup import (
    LauncherQuery,
    evaluate_arithmetic,
    parse_launcher_query,
    _preview_text,
)


def test_plain_text_is_a_search():
    q = parse_launcher_query("report")
    assert q.mode == "search"
    assert q.query == "report"


def test_slot_alias_stays_a_search_for_engine_expansion():
    q = parse_launcher_query("@logs error")
    assert q.mode == "search"
    assert q.query == "@logs error"


def test_content_scope_prefix():
    q = parse_launcher_query(">budget review")
    assert q.mode == "content"
    assert q.query == "content:budget review"


def test_content_prefix_empty_is_noop():
    q = parse_launcher_query(">")
    assert q.mode == "content"
    assert q.query == ""


def test_calculator_prefix_integer_and_float():
    assert parse_launcher_query("=2+3*4").calc_result == "14"
    assert parse_launcher_query("=10/4").calc_result == "2.5"
    assert parse_launcher_query("=2**10").calc_result == "1024"


def test_calculator_invalid_expression_is_blank():
    assert parse_launcher_query("=oops(").calc_result == ""
    assert parse_launcher_query("=").mode == "calc"
    assert parse_launcher_query("=").calc_result == ""


def test_arithmetic_rejects_names_and_calls():
    for expr in ["__import__('os')", "open('x')", "a+1", "1;2"]:
        with pytest.raises(Exception):
            evaluate_arithmetic(expr)


class _FakeEntry:
    def __init__(self, is_dir=False, size=2048, stat_loaded=True):
        self.is_dir = is_dir
        self.size = size
        self._stat_loaded = stat_loaded
        from datetime import datetime
        self.date_modified = datetime(2026, 6, 15, 10, 30)

    def ensure_stat(self, index):
        pass

    def get_path(self, index):
        return r"C:\docs\report.pdf"


def test_preview_text_for_file():
    text = _preview_text(_FakeEntry(), r"C:\docs\report.pdf", None)
    assert r"C:\docs\report.pdf" in text
    assert "File" in text
    assert "2 KB" in text
    assert "2026-06-15" in text


def test_preview_text_for_folder_omits_size():
    text = _preview_text(_FakeEntry(is_dir=True), r"C:\docs", None)
    assert "Folder" in text
    assert "KB" not in text


def test_preview_text_none_entry_returns_path():
    assert _preview_text(None, r"C:\x", None) == r"C:\x"
