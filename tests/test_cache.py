"""Tests for core.cache — datetime conversion helpers, FTS detection."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime
import core.cache as cache_mod
from core.cache import _dt_to_ms, _ms_to_dt, _has_fts5, _has_trigram, DB_VERSION
from core.sqlite_compat import (
    MIN_SAFE_FTS5_SQLITE_VERSION,
    fts5_gate_status,
    is_fts5_sqlite_version_safe,
    sqlite_version_tuple,
)


class TestDtToMs:
    def test_none(self):
        assert _dt_to_ms(None) == 0

    def test_known_datetime(self):
        dt = datetime(2024, 1, 1, 0, 0, 0)
        ms = _dt_to_ms(dt)
        assert ms > 0
        assert ms == int(dt.timestamp() * 1000)

    def test_roundtrip(self):
        dt = datetime(2024, 6, 15, 12, 30, 45)
        ms = _dt_to_ms(dt)
        result = _ms_to_dt(ms)
        assert result is not None
        assert abs((result - dt).total_seconds()) < 1

    def test_epoch(self):
        dt = datetime(1970, 1, 1, 0, 0, 0)
        ms = _dt_to_ms(dt)
        assert ms == 0 or ms < 0  # epoch or negative depending on timezone


class TestMsToDt:
    def test_zero(self):
        assert _ms_to_dt(0) is None

    def test_negative(self):
        assert _ms_to_dt(-1) is None

    def test_valid(self):
        ms = 1718438400000  # ~2024-06-15
        result = _ms_to_dt(ms)
        assert result is not None
        assert result.year == 2024


class TestFTSDetection:
    def test_fts5_available(self):
        result = _has_fts5()
        assert isinstance(result, bool)

    def test_trigram_check(self):
        result = _has_trigram()
        assert isinstance(result, bool)

    def test_sqlite_version_tuple_parses_three_parts(self):
        assert sqlite_version_tuple("3.53.2") == (3, 53, 2)
        assert sqlite_version_tuple("3.53") == (3, 53, 0)

    def test_fts5_version_gate_blocks_old_sqlite_without_probe(self):
        def fail_connect(_path):
            raise AssertionError("old SQLite should be blocked before probing FTS5")

        assert _has_fts5("3.53.1", connect=fail_connect) is False
        assert _has_trigram("3.53.1", connect=fail_connect) is False

    def test_fts5_version_gate_allows_patched_sqlite_versions(self):
        assert is_fts5_sqlite_version_safe("3.53.2") is True
        assert is_fts5_sqlite_version_safe("3.54.0") is True
        assert is_fts5_sqlite_version_safe("3.53.1") is False

    def test_fts5_gate_status_names_minimum_version(self):
        status = fts5_gate_status("3.53.1")
        minimum = ".".join(str(part) for part in MIN_SAFE_FTS5_SQLITE_VERSION)

        assert "FTS5 disabled" in status
        assert minimum in status


class TestDBVersion:
    def test_version_is_int(self):
        assert isinstance(DB_VERSION, int)
        assert DB_VERSION >= 1


class TestCacheDiagnostics:
    def test_cache_diagnostics_reports_missing_database(self, monkeypatch, tmp_path):
        cache_mod._close_connection()
        monkeypatch.setattr(cache_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "DB_FILE", tmp_path / "index.db")
        monkeypatch.setattr(cache_mod, "OLD_CACHE_FILE", tmp_path / "index_cache.bin")

        diagnostics = cache_mod.cache_diagnostics()

        assert diagnostics["db_exists"] is False
        assert diagnostics["entry_count"] == 0
        assert diagnostics["integrity_ok"] is None

    def test_cache_diagnostics_reports_meta_drives_and_content(self, monkeypatch, tmp_path):
        cache_mod._close_connection()
        monkeypatch.setattr(cache_mod, "CONFIG_DIR", tmp_path)
        monkeypatch.setattr(cache_mod, "DB_FILE", tmp_path / "index.db")
        monkeypatch.setattr(cache_mod, "OLD_CACHE_FILE", tmp_path / "index_cache.bin")

        conn = cache_mod._get_connection()
        cache_mod._init_schema(conn)
        conn.execute(
            "INSERT INTO drives (letter, flags, journal_id, next_usn) VALUES (?, ?, ?, ?)",
            ("C", 0, 12, 34),
        )
        conn.execute(
            "INSERT INTO entries (frn, drive, parent_frn, name) VALUES (?, ?, ?, ?)",
            (10, "C", 5, "file.txt"),
        )
        conn.execute(
            "INSERT INTO content_cache (path, size, modified_ms, extractor, text, indexed_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("C:\\file.txt", 4, 1000, "text", "body", 2000),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("last_saved", "2026-06-28T12:00:00"),
        )
        conn.commit()

        diagnostics = cache_mod.cache_diagnostics()
        cache_mod._close_connection()

        assert diagnostics["db_exists"] is True
        assert diagnostics["integrity_ok"] is True
        assert diagnostics["entry_count"] == 1
        assert diagnostics["last_saved"] == "2026-06-28T12:00:00"
        assert diagnostics["drives"][0]["next_usn"] == 34
        assert diagnostics["content"]["count"] == 1
