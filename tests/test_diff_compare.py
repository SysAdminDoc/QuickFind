"""Tests for inline file diff helpers."""

from core.diff_compare import build_unified_diff


def test_build_unified_diff_reports_changed_lines(tmp_path):
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("alpha\nbeta\n", encoding="utf-8")
    right.write_text("alpha\ngamma\n", encoding="utf-8")

    result = build_unified_diff(str(left), str(right))

    assert not result.error
    assert "--- left.txt" in result.text
    assert "+++ right.txt" in result.text
    assert "-beta" in result.text
    assert "+gamma" in result.text


def test_build_unified_diff_handles_identical_files(tmp_path):
    left = tmp_path / "left.txt"
    right = tmp_path / "right.txt"
    left.write_text("same\n", encoding="utf-8")
    right.write_text("same\n", encoding="utf-8")

    result = build_unified_diff(str(left), str(right))

    assert result.text == "Files are identical."


def test_build_unified_diff_rejects_binary_files(tmp_path):
    left = tmp_path / "left.bin"
    right = tmp_path / "right.txt"
    left.write_bytes(b"abc\x00def")
    right.write_text("text", encoding="utf-8")

    result = build_unified_diff(str(left), str(right))

    assert "Binary file cannot be compared inline" in result.error
