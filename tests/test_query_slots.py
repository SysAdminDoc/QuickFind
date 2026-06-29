"""Tests for saved query slot expansion."""

import json

from core.query_slots import (
    expand_query_slots,
    load_saved_query_slots,
    normalize_query_slot_name,
    query_slots_from_bookmarks,
)


def test_normalize_query_slot_name_slugifies_bookmark_names():
    assert normalize_query_slot_name("@Recent PY") == "recent-py"
    assert normalize_query_slot_name("Logs / IIS") == "logs-iis"


def test_expand_query_slots_replaces_named_slot_tokens():
    expansion = expand_query_slots(
        "@logs error @missing",
        {"logs": "ext:log dm:today"},
    )

    assert expansion.expanded_query == "ext:log dm:today error @missing"
    assert expansion.expanded_slots == ("logs",)
    assert expansion.unresolved_slots == ("missing",)


def test_expand_query_slots_supports_nested_slots_and_breaks_cycles():
    nested = expand_query_slots("@recent", {
        "recent": "@python dm:today",
        "python": "ext:py",
    })
    cycle = expand_query_slots("@loop", {"loop": "@loop"})

    assert nested.expanded_query == "ext:py dm:today"
    assert nested.expanded_slots == ("recent", "python")
    assert cycle.expanded_query == "@loop"
    assert cycle.recursive_slots == ("loop",)


def test_query_slots_from_bookmarks_uses_explicit_slot_and_name_fallback():
    slots = query_slots_from_bookmarks([
        {"name": "Logs", "query": "ext:log"},
        {"name": "Recent Python", "slot": "recent-py", "query": "ext:py dm:today"},
    ])

    assert slots["logs"] == "ext:log"
    assert slots["recent-py"] == "ext:py dm:today"
    assert slots["recent-python"] == "ext:py dm:today"


def test_load_saved_query_slots_reads_bookmark_json(tmp_path):
    bookmarks_file = tmp_path / "bookmarks.json"
    bookmarks_file.write_text(
        json.dumps([{"name": "Docs", "query": "ext:pdf;docx"}]),
        encoding="utf-8",
    )

    assert load_saved_query_slots(bookmarks_file) == {"docs": "ext:pdf;docx"}
