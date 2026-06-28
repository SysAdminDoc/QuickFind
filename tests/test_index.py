"""Tests for core.index — .quickfindignore pattern matching."""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import core.index as index_mod
from core.index import FileEntry, FileIndex, NTFS_ROOT_FRN
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY


class TestIgnorePatterns:
    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            patterns = FileIndex._load_ignore_patterns(d)
            assert patterns == []

    def test_load_patterns(self):
        with tempfile.TemporaryDirectory() as d:
            ignore = os.path.join(d, '.quickfindignore')
            with open(ignore, 'w') as f:
                f.write("node_modules\n*.pyc\n# comment\n\n.git\n")
            patterns = FileIndex._load_ignore_patterns(d)
            assert patterns == ["node_modules", "*.pyc", ".git"]

    def test_matches_exact(self):
        assert FileIndex._matches_ignore("node_modules", ["node_modules"]) is True
        assert FileIndex._matches_ignore("src", ["node_modules"]) is False

    def test_matches_glob(self):
        assert FileIndex._matches_ignore("test.pyc", ["*.pyc"]) is True
        assert FileIndex._matches_ignore("test.py", ["*.pyc"]) is False

    def test_matches_case_insensitive(self):
        assert FileIndex._matches_ignore("Thumbs.db", ["thumbs.db"]) is True
        assert FileIndex._matches_ignore("DESKTOP.INI", ["desktop.ini"]) is True

    def test_matches_question_mark(self):
        assert FileIndex._matches_ignore("test1.log", ["test?.log"]) is True
        assert FileIndex._matches_ignore("test12.log", ["test?.log"]) is False

    def test_no_patterns(self):
        assert FileIndex._matches_ignore("anything", []) is False


class TestIndexMode:
    def test_full_index_resets_admin_mode(self, monkeypatch):
        index = FileIndex()
        index._admin_mode = False
        monkeypatch.setattr(index_mod, "get_all_drives", lambda: [])

        index.index_all_drives(drives=[])

        assert index.is_admin_mode is True

    def test_force_walk_reports_non_admin_mode(self, monkeypatch):
        index = FileIndex()
        monkeypatch.setattr(index_mod, "get_all_drives", lambda: [])

        index.index_all_drives(drives=[], force_walk=True)

        assert index.is_admin_mode is False

    def test_index_diagnostics_reports_drive_modes_and_usn(self):
        index = FileIndex()
        file_entry = FileEntry(10, NTFS_ROOT_FRN, "file.txt", "C")
        folder_entry = FileEntry(20, NTFS_ROOT_FRN, "Docs", "E", FILE_ATTRIBUTE_DIRECTORY)
        index._entries = {
            "C": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "C", FILE_ATTRIBUTE_DIRECTORY),
                10: file_entry,
            },
            "E": {
                NTFS_ROOT_FRN: FileEntry(NTFS_ROOT_FRN, 0, "", "E", FILE_ATTRIBUTE_DIRECTORY),
                20: folder_entry,
            },
        }
        index._all_entries = [file_entry, folder_entry]
        index._stats.total_files = 1
        index._stats.total_folders = 1
        index._volumes["C"] = type("Volume", (), {"journal_id": 7, "current_usn": 99})()
        index._walked_drives.add("E")
        index.set_external_source("EFU file list: sample.efu")

        diagnostics = index.index_diagnostics()
        drives = {row["drive"]: row for row in diagnostics["drives"]}

        assert diagnostics["source"] == "EFU file list: sample.efu"
        assert diagnostics["total_entries"] == 2
        assert drives["C"]["mode"] == "MFT + USN"
        assert drives["C"]["journal_id"] == 7
        assert drives["C"]["next_usn"] == 99
        assert drives["E"]["mode"] == "os.scandir"
        assert drives["E"]["folders"] == 1
