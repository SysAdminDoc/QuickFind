"""Tests for selectable theme packs."""

from gui.theme import (
    MOCHA,
    active_theme_name,
    available_themes,
    build_stylesheet,
    is_dark_theme,
    set_active_theme,
)


def test_theme_pack_switch_rebuilds_active_palette_and_stylesheet():
    original = active_theme_name()
    try:
        assert set_active_theme("latte") == "latte"

        assert MOCHA["base"] == "#eff1f5"
        assert "#eff1f5" in build_stylesheet()
    finally:
        set_active_theme(original)


def test_unknown_theme_falls_back_to_mocha():
    original = active_theme_name()
    try:
        assert set_active_theme("missing") == "mocha"
        assert MOCHA["base"] == "#1e1e2e"
    finally:
        set_active_theme(original)


def test_available_themes_include_dark_and_light_packs():
    themes = dict(available_themes())

    assert themes["mocha"] == "Catppuccin Mocha"
    assert themes["latte"] == "Catppuccin Latte"


def test_is_dark_theme_reflects_active_theme():
    original = active_theme_name()
    try:
        set_active_theme("mocha")
        assert is_dark_theme() is True
        set_active_theme("macchiato")
        assert is_dark_theme() is True
        set_active_theme("latte")
        assert is_dark_theme() is False
    finally:
        set_active_theme(original)
