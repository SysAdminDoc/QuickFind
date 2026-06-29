"""Tests for preview pane helpers."""

from gui.preview_pane import _matched_context_line_numbers


def test_matched_context_line_numbers_detects_preview_match_markers():
    content = "\n".join([
        "  2: before",
        "> 5: needle",
        "  6: after",
        "...",
        "> 20: needle again",
    ])

    assert _matched_context_line_numbers(content) == [1, 4]


def test_matched_context_line_numbers_ignores_plain_blockquote_text():
    content = "\n".join([
        ">quoted text from a normal preview",
        "  1: no match",
    ])

    assert _matched_context_line_numbers(content) == []
