"""Tests for core.file_list — EFU parsing, FILETIME conversion."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import pytest
from core.file_list import _parse_efu_date, efu_source_key, load_efu, _FILETIME_EPOCH_DIFF


class TestParseEfuDate:
    def test_empty(self):
        assert _parse_efu_date("") is None
        assert _parse_efu_date(None) is None

    def test_zero(self):
        assert _parse_efu_date("0") is None

    def test_negative(self):
        assert _parse_efu_date("-1") is None

    def test_valid_filetime(self):
        ft = 132514560000000000  # ~2021-01-01 UTC
        result = _parse_efu_date(str(ft))
        assert result is not None
        assert result.year == 2020 or result.year == 2021

    def test_invalid_string(self):
        assert _parse_efu_date("notanumber") is None


class TestLoadEfu:
    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.efu', delete=False, encoding='utf-8') as f:
            f.write("")
            f.flush()
            entries = load_efu(f.name)
        os.unlink(f.name)
        assert entries == []

    def test_header_only(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.efu', delete=False, encoding='utf-8') as f:
            f.write("Filename,Size,Date Modified,Date Created,Attributes\n")
            f.flush()
            entries = load_efu(f.name)
        os.unlink(f.name)
        assert entries == []

    def test_single_entry(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.efu', delete=False, encoding='utf-8') as f:
            f.write("Filename,Size,Date Modified,Date Created,Attributes\n")
            f.write("C:\\test\\file.txt,1024,132514560000000000,132514560000000000,32\n")
            f.flush()
            entries = load_efu(f.name)
        os.unlink(f.name)
        assert len(entries) == 1
        assert entries[0].name == "file.txt"
        assert entries[0].size == 1024
        assert entries[0].drive == "C"
        assert entries[0]._stat_loaded is True
        assert entries[0]._path == "C:\\test\\file.txt"

    def test_nonexistent_file(self):
        entries = load_efu("/nonexistent/path.efu")
        assert entries == []

    def test_efu_source_key_is_stable(self, tmp_path):
        efu = tmp_path / "list.efu"
        efu.write_text("Filename,Size,Date Modified,Date Created,Attributes\n")

        assert efu_source_key(str(efu)) == efu_source_key(str(efu))
        assert efu_source_key(str(efu)).startswith("EFU:")


class TestFiletimeEpochDiff:
    def test_constant(self):
        assert _FILETIME_EPOCH_DIFF == 116444736000000000
