"""Tests for workspace root search filtering."""

from core.workspaces import (
    filter_entries_by_workspace,
    parse_workspace_roots,
    path_matches_workspace,
    workspace_roots_text,
)


class DummyEntry:
    def __init__(self, path: str):
        self._path = path

    def get_path(self, _index):
        return self._path


def test_parse_workspace_roots_normalizes_and_deduplicates():
    roots = parse_workspace_roots(r" C:\Src\ ; c:\src ; D:\Docs ")

    assert roots == [r"C:\Src", r"D:\Docs"]
    assert workspace_roots_text(roots) == r"C:\Src;D:\Docs"


def test_path_matches_workspace_uses_root_boundaries():
    assert path_matches_workspace(r"C:\Src\Project\main.py", [r"c:\src"])
    assert path_matches_workspace(r"C:\Src", [r"c:\src"])
    assert path_matches_workspace(r"C:\Windows\notepad.exe", [r"C:\\"])
    assert not path_matches_workspace(r"C:\Src2\main.py", [r"c:\src"])


def test_filter_entries_by_workspace_keeps_any_matching_root():
    entries = [
        DummyEntry(r"C:\Src\a.py"),
        DummyEntry(r"D:\Docs\b.txt"),
        DummyEntry(r"E:\Other\c.txt"),
    ]

    filtered = filter_entries_by_workspace(entries, None, [r"C:\Src", r"D:\Docs"])

    assert [entry.get_path(None) for entry in filtered] == [
        r"C:\Src\a.py",
        r"D:\Docs\b.txt",
    ]
