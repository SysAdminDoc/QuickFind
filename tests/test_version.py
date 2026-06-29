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


def test_msix_version_uses_four_numeric_parts():
    assert build.msix_version("1.2.3") == "1.2.3.0"


def test_msix_manifest_includes_shell_integration():
    manifest = build.render_msix_manifest("1.2.3")

    assert 'Name="SysAdminDoc.QuickFind"' in manifest
    assert 'Category="windows.protocol"' in manifest
    assert '<uap:Protocol Name="quickfind" />' in manifest
    assert 'Alias="quickfind.exe"' in manifest
    assert '<rescap:Capability Name="runFullTrust" />' in manifest


def test_appinstaller_enables_background_update_checks():
    appinstaller = build.render_appinstaller(
        "https://example.test/QuickFind.msix",
        "https://example.test/QuickFind.appinstaller",
        "1.2.3",
    )

    assert 'HoursBetweenUpdateChecks="24"' in appinstaller
    assert "<AutomaticBackgroundTask />" in appinstaller


def test_winget_manifest_uses_msix_hash_and_release_url():
    manifests = build.render_winget_manifests(
        "https://example.test/QuickFind.msix",
        "A" * 64,
        "1.2.3",
    )
    installer = manifests["SysAdminDoc.QuickFind.installer.yaml"]

    assert "InstallerType: msix" in installer
    assert "InstallerSha256: " + ("A" * 64) in installer
