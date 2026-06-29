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
