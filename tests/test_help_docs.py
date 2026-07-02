"""Tests for bundled offline help content."""

from gui.help_docs import build_offline_help_html


def test_offline_help_includes_core_search_modifiers():
    html = build_offline_help_html("QuickFind vTest")

    assert "QuickFind vTest Offline Help" in html
    assert "content:text" in html
    assert "archive:report" in html
    assert "dupe:hash" in html
    assert "Index Diagnostics" in html


def test_offline_help_is_self_contained():
    html = build_offline_help_html()

    assert "http://" not in html
    assert "https://" not in html
    assert "does not require network access" in html


def test_offline_help_uses_active_theme_colors():
    from gui.theme import MOCHA, set_active_theme, active_theme_name
    original = active_theme_name()
    try:
        set_active_theme("latte")
        html = build_offline_help_html()
        assert "#bcc0cc" in html
        assert "#45475a" not in html
    finally:
        set_active_theme(original)


def test_offline_help_uses_active_language_for_section_headers():
    from core.localization import set_language, active_language
    original = active_language()
    try:
        set_language("es")
        html = build_offline_help_html()
        assert "Sintaxis de búsqueda" in html  # help.search_syntax (es)
        assert "Solución de problemas" in html  # help.troubleshooting (es)
    finally:
        set_language(original)
