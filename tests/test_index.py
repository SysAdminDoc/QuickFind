"""Tests for core.index — .quickfindignore pattern matching."""

import sys
import os
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from core.index import FileIndex


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
