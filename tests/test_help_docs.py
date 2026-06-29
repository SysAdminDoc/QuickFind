"""Tests for bundled offline help content."""

from gui.help_docs import build_offline_help_html


def test_offline_help_includes_core_search_modifiers():
    html = build_offline_help_html("QuickFind vTest")

    assert "QuickFind vTest Offline Help" in html
    assert "content:text" in html
    assert "archive:report" in html
    assert "duplicate:hash" in html
    assert "Index Diagnostics" in html


def test_offline_help_is_self_contained():
    html = build_offline_help_html()

    assert "http://" not in html
    assert "https://" not in html
    assert "does not require network access" in html
