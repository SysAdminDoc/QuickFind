"""Tests for application version metadata."""

import build
from core.version import APP_NAME, APP_TITLE, VERSION


def test_version_metadata_is_consistent():
    assert APP_NAME == "QuickFind"
    assert APP_TITLE == f"{APP_NAME} v{VERSION}"
    assert build.APP_NAME == APP_NAME
    assert build.VERSION == VERSION


def test_build_runtime_matrix_reports_core_dependencies():
    matrix = build.runtime_matrix()

    assert matrix["Python"]
    assert matrix["SQLite"]
    assert "SQLite FTS5" in matrix
    for package, _ in build.RUNTIME_PACKAGES:
        assert package in matrix
        assert matrix[package]


def test_build_requires_pyinstaller_without_installing():
    def missing_pyinstaller(_name):
        raise ImportError("missing")

    try:
        build.require_pyinstaller(missing_pyinstaller)
    except SystemExit as exc:
        assert exc.code == "PyInstaller is missing. Run: python -m pip install -r requirements.txt"
    else:
        raise AssertionError("require_pyinstaller should stop when PyInstaller is missing")
