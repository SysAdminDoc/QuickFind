"""Tests for visual query builder chip extraction, composition, and validation."""

from gui.query_chips import (
    QueryChip,
    add_chip,
    available_modifiers,
    compose_query,
    extract_chips,
    remove_chip,
    validate_chip,
)


def test_extract_simple_modifier():
    chips, text = extract_chips("ext:pdf report")
    assert len(chips) == 1
    assert chips[0].modifier == "ext"
    assert chips[0].value == "pdf"
    assert text == "report"


def test_extract_multiple_modifiers():
    chips, text = extract_chips("size:>1mb ext:docx quarterly")
    assert len(chips) == 2
    assert chips[0].modifier == "size"
    assert chips[1].modifier == "ext"
    assert text == "quarterly"


def test_extract_no_modifiers():
    chips, text = extract_chips("hello world")
    assert chips == []
    assert text == "hello world"


def test_extract_unknown_modifier_stays_in_text():
    chips, text = extract_chips("unknown:value report")
    assert chips == []
    assert "unknown:value" in text


def test_compose_roundtrips():
    original = "ext:pdf size:>1mb quarterly report"
    chips, text = extract_chips(original)
    reconstructed = compose_query(chips, text)
    assert "ext:pdf" in reconstructed
    assert "size:>1mb" in reconstructed
    assert "quarterly report" in reconstructed


def test_add_chip_appends_modifier():
    result = add_chip("report", "ext", "pdf")
    assert result == "report ext:pdf"


def test_add_chip_to_empty_query():
    result = add_chip("", "size", ">1mb")
    assert result == "size:>1mb"


def test_remove_chip():
    query = "ext:pdf size:>1mb report"
    chips, _ = extract_chips(query)
    ext_chip = chips[0]
    result = remove_chip(query, ext_chip)
    assert "ext:pdf" not in result
    assert "size:>1mb" in result
    assert "report" in result


def test_chip_display():
    chip = QueryChip(modifier="ext", value="pdf", label="Extension", raw="ext:pdf")
    assert chip.display == "ext:pdf"


def test_validate_valid_chips():
    assert validate_chip("ext", "pdf") is None
    assert validate_chip("size", ">1mb") is None
    assert validate_chip("dm", "today") is None


def test_validate_unknown_modifier():
    error = validate_chip("foobar", "x")
    assert error is not None
    assert "Unknown" in error


def test_validate_missing_required_value():
    error = validate_chip("ext", "")
    assert error is not None
    assert "requires" in error


def test_validate_invalid_size():
    error = validate_chip("size", "abc")
    assert error is not None
    assert "Invalid" in error


def test_available_modifiers_returns_all():
    mods = available_modifiers()
    names = [name for name, _ in mods]
    assert "ext" in names
    assert "size" in names
    assert "content" in names
    assert len(mods) >= 10


def test_extract_preserves_quoted_strings():
    chips, text = extract_chips('ext:pdf "my report"')
    assert len(chips) == 1
    assert '"my report"' in text


def test_modifier_only_chip():
    chips, text = extract_chips("file: report")
    assert len(chips) == 1
    assert chips[0].modifier == "file"
    assert chips[0].value == ""
    assert text == "report"


def test_validate_broken_without_value_is_valid():
    assert validate_chip("broken", "") is None


def test_validate_dupe_without_value_is_valid():
    assert validate_chip("dupe", "") is None
