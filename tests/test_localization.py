"""Tests for runtime localization helpers."""

from core.localization import (
    CATALOGS,
    active_language,
    all_keys,
    available_languages,
    generate_pseudo_catalog,
    missing_keys,
    normalize_language,
    pseudo_localize,
    set_language,
    tr,
)


def test_available_languages_include_default_and_spanish():
    assert available_languages() == (("en", "English"), ("es", "Spanish"))


def test_invalid_language_normalizes_to_english():
    assert normalize_language("missing") == "en"
    assert normalize_language(None) == "en"


def test_translation_falls_back_to_default_for_english():
    previous = active_language()
    try:
        set_language("en")
        assert tr("search.placeholder", "Search files and folders...") == "Search files and folders..."
    finally:
        set_language(previous)


def test_spanish_catalog_translates_known_keys():
    previous = active_language()
    try:
        set_language("es")
        assert tr("menu.file", "&File") == "Archivo"
        assert tr("status.select_result_preview", "Select a result to preview").startswith("Seleccione")
    finally:
        set_language(previous)


def test_spanish_covers_settings_and_help_keys():
    es = CATALOGS["es"]
    assert "settings.title" in es
    assert "settings.content" in es
    assert "settings.content.purge_all" in es
    assert "diagnostics.title" in es
    assert "diagnostics.refresh" in es
    assert "help.title" in es
    assert "help.search_syntax" in es
    assert "results.count" in es


def test_all_keys_returns_union():
    keys = all_keys()
    assert "menu.file" in keys
    assert "settings.title" in keys
    assert len(keys) > 40


def test_missing_keys_for_existing_language():
    missing = missing_keys("es")
    assert isinstance(missing, frozenset)


def test_missing_keys_for_nonexistent_language_returns_all():
    missing = missing_keys("xx")
    assert missing == all_keys()


def test_pseudo_localize_wraps_and_transforms():
    result = pseudo_localize("Hello World")
    assert result.startswith("[")
    assert result.endswith("]")
    assert "H" not in result.strip("[]") or "è" in result


def test_generate_pseudo_catalog_covers_all_spanish_keys():
    pseudo = generate_pseudo_catalog()
    es = CATALOGS["es"]
    assert set(pseudo.keys()) == set(es.keys())
    for key in pseudo:
        assert pseudo[key].startswith("[")


def test_fallback_returns_key_when_no_default():
    previous = active_language()
    try:
        set_language("en")
        assert tr("nonexistent.key.xyz") == "nonexistent.key.xyz"
    finally:
        set_language(previous)


def test_format_values_interpolate_into_translations():
    previous = active_language()
    try:
        set_language("es")
        result = tr("results.count", "{count} results", count=42)
        assert "42" in result
    finally:
        set_language(previous)
