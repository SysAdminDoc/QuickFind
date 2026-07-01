"""Tests for duplicate review workflow: grouping, preview, and safe remediation."""

import os
from unittest.mock import MagicMock

from core.duplicate_review import (
    DuplicateGroup,
    KeepRule,
    RemediationResult,
    group_by_name,
    group_by_size,
    preview_remediation,
    safe_recycle,
)
from core.index import FileEntry, FileIndex


def _entry(name, frn=1, size=100, drive="C", is_dir=False, path=None):
    from core.ntfs import FILE_ATTRIBUTE_DIRECTORY
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else 0
    entry = FileEntry(frn, 5, name, drive, attrs, size=size)
    entry._path = path or f"{drive}:\\test\\{name}"
    return entry


def _index():
    index = MagicMock(spec=FileIndex)
    index.resolve_parent_path.return_value = "C:\\test"
    return index


def test_group_by_name_finds_duplicates():
    entries = [
        _entry("report.pdf", frn=1, path="C:\\a\\report.pdf"),
        _entry("report.pdf", frn=2, path="C:\\b\\report.pdf"),
        _entry("unique.txt", frn=3),
    ]
    groups = group_by_name(entries, _index())
    assert len(groups) == 1
    assert groups[0].key == "report.pdf"
    assert groups[0].count == 2


def test_group_by_name_excludes_folders():
    entries = [
        _entry("docs", frn=1, is_dir=True),
        _entry("docs", frn=2, is_dir=True),
    ]
    groups = group_by_name(entries, _index())
    assert groups == []


def test_group_by_name_case_insensitive():
    entries = [
        _entry("Report.PDF", frn=1),
        _entry("report.pdf", frn=2),
    ]
    groups = group_by_name(entries, _index())
    assert len(groups) == 1
    assert groups[0].count == 2


def test_group_by_size():
    entries = [
        _entry("a.txt", frn=1, size=1024),
        _entry("b.txt", frn=2, size=1024),
        _entry("c.txt", frn=3, size=2048),
    ]
    groups = group_by_size(entries, _index())
    assert len(groups) == 1
    assert groups[0].key == "1024"
    assert groups[0].count == 2


def test_duplicate_group_recoverable_size():
    entries = [
        _entry("a.txt", frn=1, size=1000),
        _entry("b.txt", frn=2, size=1000),
        _entry("c.txt", frn=3, size=1000),
    ]
    groups = group_by_name(entries, _index())
    assert groups == []
    groups = group_by_size(entries, _index())
    assert len(groups) == 1
    assert groups[0].recoverable_size == 2000


def test_preview_keeps_shortest_path():
    entries = [
        _entry("a.txt", frn=1, path="C:\\short\\a.txt"),
        _entry("a.txt", frn=2, path="C:\\very\\long\\nested\\path\\a.txt"),
    ]
    group = DuplicateGroup(key="a.txt", entries=tuple(entries), total_size=200)
    index = _index()
    preview = preview_remediation(group, KeepRule(), index)
    assert preview.keep._path == "C:\\short\\a.txt"
    assert len(preview.delete_candidates) == 1


def test_preview_prefers_root():
    entries = [
        _entry("a.txt", frn=1, path="C:\\other\\a.txt"),
        _entry("a.txt", frn=2, path="D:\\preferred\\a.txt"),
    ]
    group = DuplicateGroup(key="a.txt", entries=tuple(entries), total_size=200)
    index = _index()
    rule = KeepRule(prefer_root="D:\\preferred")
    preview = preview_remediation(group, rule, index)
    assert preview.keep._path == "D:\\preferred\\a.txt"


def test_safe_recycle_with_mock_recycler(tmp_path):
    file_a = tmp_path / "a.txt"
    file_b = tmp_path / "b.txt"
    file_a.write_text("data", encoding="utf-8")
    file_b.write_text("data", encoding="utf-8")

    recycled_files = []

    def mock_recycle(path):
        recycled_files.append(path)
        os.remove(path)
        return True

    result = safe_recycle([str(file_a), str(file_b)], recycle_fn=mock_recycle)
    assert len(result.recycled) == 2
    assert not result.failed


def test_safe_recycle_skips_missing_files():
    result = safe_recycle(["C:\\nonexistent_file_xyz.txt"], recycle_fn=lambda p: True)
    assert len(result.skipped) == 1


def test_safe_recycle_records_failures():
    def failing_recycle(path):
        raise PermissionError("Access denied")

    result = safe_recycle(["C:\\test.txt"], recycle_fn=failing_recycle)
    assert result.skipped == ["C:\\test.txt"]


def test_safe_recycle_existing_file_fails(tmp_path):
    file_a = tmp_path / "a.txt"
    file_a.write_text("data", encoding="utf-8")

    result = safe_recycle([str(file_a)], recycle_fn=lambda p: False)
    assert len(result.failed) == 1
    assert "returned False" in result.failed[0][1]
