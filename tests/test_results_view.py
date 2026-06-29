"""Tests for result view helpers."""

from collections import OrderedDict

from PyQt6.QtCore import Qt

import gui.results_view as results_view
from core.index import FileEntry
from core.ntfs import FILE_ATTRIBUTE_EA, FILE_ATTRIBUTE_REPARSE_POINT
from gui.results_view import (
    COLUMN_NAME, FileIconCache, PathColumnModel, ResultsTableModel,
    ThumbnailListView,
    format_attributes, format_reparse_tag, path_segments,
)


class FakeIconProvider:
    class IconType:
        Folder = "folder"
        File = "file"

    def icon(self, value):
        return f"icon:{value}"


def _entry(name: str, frn: int = 1) -> FileEntry:
    return FileEntry(frn=frn, parent_frn=5, name=name, drive="C")


class TempIndex:
    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        return f"{drive}:\\"


def _reset_icon_cache(monkeypatch, limit: int):
    monkeypatch.setattr(results_view, "MAX_FILE_ICON_CACHE_SIZE", limit)
    FileIconCache._provider = FakeIconProvider()
    FileIconCache._cache = OrderedDict()


def test_file_icon_cache_is_bounded(monkeypatch):
    _reset_icon_cache(monkeypatch, 3)

    for i, ext in enumerate(["a", "b", "c", "d", "e"], start=1):
        FileIconCache.get(_entry(f"file.{ext}", i))

    assert len(FileIconCache._cache) == 3
    assert list(FileIconCache._cache.keys()) == ["c", "d", "e"]


def test_file_icon_cache_refreshes_recently_used_key(monkeypatch):
    _reset_icon_cache(monkeypatch, 3)

    for i, ext in enumerate(["a", "b", "c"], start=1):
        FileIconCache.get(_entry(f"file.{ext}", i))
    FileIconCache.get(_entry("again.a", 10))
    FileIconCache.get(_entry("file.d", 11))

    assert list(FileIconCache._cache.keys()) == ["c", "a", "d"]


def test_result_tooltip_includes_content_snippet():
    entry = _entry("report.txt")
    entry._path = "C:\\docs\\report.txt"
    entry.content_snippet = "alpha needle omega"
    model = ResultsTableModel(TempIndex())
    model.set_results([entry])

    tooltip = model.data(model.index(0, COLUMN_NAME), Qt.ItemDataRole.ToolTipRole)

    assert tooltip == "C:\\docs\\report.txt\n\nContent match:\nalpha needle omega"


def test_attribute_formatter_surfaces_reparse_and_ea_flags():
    attrs = FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_EA

    assert format_attributes(attrs) == "LEA"


def test_reparse_tag_formatter_names_common_tags():
    assert format_reparse_tag(0xA000000C) == "SYMLINK (0xA000000C)"
    assert format_reparse_tag(0x12345678) == "0x12345678"


def test_result_tooltip_includes_reparse_and_ea_metadata():
    entry = _entry("link")
    entry._path = "C:\\docs\\link"
    entry.reparse_tag = 0xA000000C
    entry.has_extended_attributes = True
    model = ResultsTableModel(TempIndex())
    model.set_results([entry])

    tooltip = model.data(model.index(0, COLUMN_NAME), Qt.ItemDataRole.ToolTipRole)

    assert "C:\\docs\\link" in tooltip
    assert "Reparse tag: SYMLINK (0xA000000C)" in tooltip
    assert "Extended attributes: present" in tooltip


def test_path_segments_split_drive_and_unc_paths():
    assert path_segments(r"C:\Users\me\report.txt") == [
        "C:",
        "Users",
        "me",
        "report.txt",
    ]
    assert path_segments(r"\\server\share\folder\file.txt") == [
        r"\\server\share",
        "folder",
        "file.txt",
    ]


def test_path_column_model_exposes_segments():
    entry = _entry("report.txt")
    entry._path = r"C:\Users\me\report.txt"
    model = PathColumnModel(TempIndex())
    model.set_results([entry])

    assert model.columnCount() == 4
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Root"
    assert model.data(model.index(0, 0)) == "C:"
    assert model.data(model.index(0, 3)) == "report.txt"


def test_thumbnail_selected_entries_returns_unique_rows():
    entry = _entry("report.txt")
    model = ResultsTableModel(TempIndex())
    model.set_results([entry])

    class FakeThumbnailView:
        def model(self):
            return model

        def selectedIndexes(self):
            return [model.index(0, 0), model.index(0, 1)]

    assert ThumbnailListView.selected_entries(FakeThumbnailView()) == [entry]
