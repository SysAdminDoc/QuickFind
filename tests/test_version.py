"""Tests for application version metadata."""

import zipfile

import pytest

import build
from core.version import APP_NAME, APP_TITLE, VERSION


def test_version_metadata_is_consistent():
    assert APP_NAME == "QuickFind"
    assert APP_TITLE == f"{APP_NAME} v{VERSION}"
    assert build.APP_NAME == APP_NAME
    assert build.VERSION == VERSION


def test_version_info_text_embeds_version_and_identity():
    text = build.version_info_text()
    tup = build._version_tuple()
    expected = tuple((list(int(p) for p in VERSION.split('.') if p.isdigit()) + [0, 0, 0, 0])[:4])
    assert tup == expected
    assert len(tup) == 4
    assert f"filevers={tup}" in text
    assert f"StringStruct('FileVersion', '{VERSION}')" in text
    assert "StringStruct('ProductName', 'QuickFind')" in text
    assert "StringStruct('CompanyName', 'SysAdminDoc')" in text


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


def test_release_check_accepts_matching_local_artifacts(tmp_path, monkeypatch):
    _write_release_fixture(tmp_path, monkeypatch)

    report = build.release_check(
        skip_remote=True,
        allow_unsigned=True,
        signature_status=lambda _path: "NotSigned",
    )

    assert report.passed is True
    assert any("Skipped GitHub" in warning for warning in report.warnings)
    assert not report.errors


def test_release_check_reports_winget_hash_mismatch(tmp_path, monkeypatch):
    _write_release_fixture(tmp_path, monkeypatch)
    installer = build.WINGET / f"{build.PACKAGE_IDENTIFIER}.installer.yaml"
    installer.write_text(
        installer.read_text(encoding="utf-8").replace(
            "InstallerSha256: " + build._sha256_file(build.DIST / build.MSIX_NAME),
            "InstallerSha256: " + ("B" * 64),
        ),
        encoding="utf-8",
    )

    report = build.release_check(
        skip_remote=True,
        allow_unsigned=True,
        signature_status=lambda _path: "NotSigned",
    )

    assert report.passed is False
    assert any("InstallerSha256" in error for error in report.errors)


def test_release_check_reports_missing_github_assets(tmp_path, monkeypatch):
    _write_release_fixture(tmp_path, monkeypatch)

    report = build.release_check(
        allow_unsigned=True,
        url_exists=lambda _url: False,
        signature_status=lambda _path: "Valid",
    )

    assert report.passed is False
    assert any("GitHub release asset" in error for error in report.errors)


def test_release_check_fails_on_unwaived_advisory(tmp_path, monkeypatch):
    from core.dep_audit import Advisory, AuditReport, PackageInfo

    _write_release_fixture(tmp_path, monkeypatch)

    def failing_audit():
        return AuditReport(
            packages=[PackageInfo("pdfminer.six", "pdfminer.six", "1.0", "1.0", "MIT")],
            unwaived=[Advisory("CVE-0000-0001", "pdfminer.six", "critical", "boom")],
        )

    report = build.release_check(
        skip_remote=True,
        allow_unsigned=True,
        signature_status=lambda _path: "NotSigned",
        audit_runner=failing_audit,
    )

    assert report.passed is False
    assert any("CVE-0000-0001" in error for error in report.errors)
    assert (build.DIST / "sbom.json").exists()


def test_release_check_passes_with_clean_audit(tmp_path, monkeypatch):
    from core.dep_audit import AuditReport, PackageInfo

    _write_release_fixture(tmp_path, monkeypatch)

    def clean_audit():
        return AuditReport(
            packages=[PackageInfo("pdfminer.six", "pdfminer.six", "1.0", "1.0", "MIT")]
        )

    report = build.release_check(
        skip_remote=True,
        allow_unsigned=True,
        signature_status=lambda _path: "NotSigned",
        audit_runner=clean_audit,
    )

    assert report.passed is True
    assert any("advisory audit passed" in msg for msg in report.checks)


def test_clean_reports_locked_build_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "BUILD", tmp_path / "build")
    monkeypatch.setattr(build, "SPEC", tmp_path / "QuickFind.spec")
    build.DIST.mkdir()

    def locked_rmtree(_path, onerror=None):
        raise PermissionError("locked")

    monkeypatch.setattr(build.shutil, "rmtree", locked_rmtree)

    with pytest.raises(SystemExit) as exc_info:
        build.clean()

    message = str(exc_info.value)
    assert "Cannot clean" in message
    assert "locked" in message


def _write_release_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", tmp_path / "dist")
    monkeypatch.setattr(build, "WINGET", tmp_path / "winget")
    build.DIST.mkdir()
    build.WINGET.mkdir()
    msix_url = build._release_asset_url(build.MSIX_NAME)
    appinstaller_url = build._release_asset_url(build.APPINSTALLER_NAME)
    msix_path = build.DIST / build.MSIX_NAME

    with zipfile.ZipFile(msix_path, "w") as package:
        package.writestr("AppxManifest.xml", build.render_msix_manifest())
        package.writestr("QuickFind.exe", b"fixture")

    (build.DIST / build.APPINSTALLER_NAME).write_text(
        build.render_appinstaller(msix_url, appinstaller_url),
        encoding="utf-8",
    )
    manifests = build.render_winget_manifests(
        msix_url,
        build._sha256_file(msix_path),
    )
    for filename, content in manifests.items():
        (build.WINGET / filename).write_text(content, encoding="utf-8")
