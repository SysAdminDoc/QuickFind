"""Tests for preview pane helpers."""

from PyQt6.QtCore import QRect, QSize

from gui.preview_pane import _matched_context_line_numbers, quick_preview_geometry


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


def test_quick_preview_geometry_stays_inside_available_screen():
    geometry = quick_preview_geometry(
        QRect(1200, 680, 80, 40),
        QRect(0, 0, 1280, 720),
        QSize(760, 520),
    )

    assert geometry.right() <= 1279
    assert geometry.bottom() <= 719
    assert geometry.width() == 760
    assert geometry.height() == 520
