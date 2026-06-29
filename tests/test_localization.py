"""Tests for runtime localization helpers."""

from core.localization import (
    active_language,
    available_languages,
    normalize_language,
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
