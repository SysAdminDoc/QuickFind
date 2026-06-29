"""Tests for bookmark persistence helpers."""

import json

import gui.bookmarks as bookmarks


def test_bookmark_manager_builds_query_slot_map(monkeypatch, tmp_path):
    monkeypatch.setattr(bookmarks, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bookmarks, "BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    bookmarks.BOOKMARKS_FILE.write_text(
        json.dumps([
            {"name": "Logs", "query": "ext:log"},
            {"name": "Recent Python", "slot": "recent-py", "query": "ext:py dm:today"},
        ]),
        encoding="utf-8",
    )

    manager = bookmarks.BookmarkManager()

    assert manager.query_slots()["logs"] == "ext:log"
    assert manager.query_slots()["recent-py"] == "ext:py dm:today"


def test_bookmark_loads_workspace_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(bookmarks, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(bookmarks, "BOOKMARKS_FILE", tmp_path / "bookmarks.json")
    bookmarks.BOOKMARKS_FILE.write_text(
        json.dumps([
            {
                "name": "Repos",
                "query": "*.py",
                "workspace_roots": [r"C:\Users\--\repos", r" c:\users\--\repos\ "],
            },
        ]),
        encoding="utf-8",
    )

    manager = bookmarks.BookmarkManager()

    assert manager.bookmarks[0].workspace_roots == [r"C:\Users\--\repos"]


def test_bookmark_tooltip_includes_workspace_roots():
    bookmark = bookmarks.Bookmark(
        name="Docs",
        query="ext:pdf",
        workspace_roots=[r"C:\Docs", r"D:\Archive"],
    )

    tooltip = bookmarks._bookmark_tooltip(bookmark)

    assert "Search: ext:pdf" in tooltip
    assert r"Workspace: C:\Docs;D:\Archive" in tooltip
