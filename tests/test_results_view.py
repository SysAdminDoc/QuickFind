"""Tests for result view helpers."""

from collections import OrderedDict

from PyQt6.QtCore import Qt

import gui.results_view as results_view
from core.index import FileEntry
from gui.results_view import COLUMN_NAME, FileIconCache, ResultsTableModel


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
