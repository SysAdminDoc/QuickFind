"""Tests for the dependency advisory, license, and SBOM release gate."""

import json
from datetime import date
from pathlib import Path

import pytest

from core.dep_audit import (
    Advisory,
    AuditReport,
    PackageInfo,
    Waiver,
    format_report,
    load_waivers,
    read_pinned_requirements,
    run_audit,
    sbom_json,
)


def _fake_requirements(tmp_path: Path, content: str) -> Path:
    req = tmp_path / "requirements.txt"
    req.write_text(content, encoding="utf-8")
    return req


def _fake_waivers(tmp_path: Path, waivers: list[dict]) -> Path:
    path = tmp_path / "dep_waivers.json"
    path.write_text(json.dumps({"waivers": waivers}), encoding="utf-8")
    return path


def _no_advisories(_dist: str, _version: str) -> list[Advisory]:
    return []


def _critical_advisory(dist: str, _version: str) -> list[Advisory]:
    if dist == "py7zr":
        return [Advisory(
            id="PYSEC-2025-9999",
            package="py7zr",
            severity="critical",
            summary="Remote code execution in py7zr archive handling",
            fixed_in="1.2.0",
        )]
    return []


def _high_advisory(dist: str, _version: str) -> list[Advisory]:
    if dist == "watchdog":
        return [Advisory(
            id="PYSEC-2025-1111",
            package="watchdog",
            severity="high",
            summary="Path traversal in watchdog observer",
        )]
    return []


def _medium_advisory(dist: str, _version: str) -> list[Advisory]:
    if dist == "pdfplumber":
        return [Advisory(
            id="PYSEC-2025-5555",
            package="pdfplumber",
            severity="medium",
            summary="Denial of service via crafted PDF",
        )]
    return []


SAMPLE_REQUIREMENTS = """\
# Runtime
PyQt6==6.11.0
py7zr==1.1.3
watchdog==6.0.0
pdfplumber==0.11.10

# Build
pyinstaller==6.21.0
pytest==9.0.3
"""


def test_read_pinned_requirements(tmp_path):
    path = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    pins = read_pinned_requirements(path)
    assert pins["PyQt6"] == "6.11.0"
    assert pins["py7zr"] == "1.1.3"
    assert pins["watchdog"] == "6.0.0"
    assert "pyinstaller" in pins


def test_read_pinned_requirements_missing_file(tmp_path):
    pins = read_pinned_requirements(tmp_path / "nonexistent.txt")
    assert pins == {}


def test_audit_passes_with_no_advisories(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    report = run_audit(
        advisory_fetcher=_no_advisories,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    assert report.passed is True
    assert len(report.packages) == 6
    assert not report.unwaived


def test_audit_fails_on_critical_advisory(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    report = run_audit(
        advisory_fetcher=_critical_advisory,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    assert report.passed is False
    assert len(report.unwaived) == 1
    assert report.unwaived[0].id == "PYSEC-2025-9999"
    assert report.unwaived[0].severity == "critical"


def test_audit_fails_on_high_advisory(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    report = run_audit(
        advisory_fetcher=_high_advisory,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    assert report.passed is False
    assert len(report.unwaived) == 1
    assert report.unwaived[0].severity == "high"


def test_audit_passes_medium_without_waiver(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    report = run_audit(
        advisory_fetcher=_medium_advisory,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    assert report.passed is True
    assert not report.unwaived


def test_waiver_suppresses_critical(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    waivers = _fake_waivers(tmp_path, [{
        "id": "PYSEC-2025-9999",
        "package": "py7zr",
        "reason": "Not exploitable in our usage",
        "expires": "2099-12-31",
    }])
    report = run_audit(
        advisory_fetcher=_critical_advisory,
        waiver_path=waivers,
        requirements_path=req,
    )
    assert report.passed is True
    assert len(report.waived) == 1
    assert not report.unwaived


def test_expired_waiver_does_not_suppress(tmp_path):
    req = _fake_requirements(tmp_path, SAMPLE_REQUIREMENTS)
    waivers = _fake_waivers(tmp_path, [{
        "id": "PYSEC-2025-9999",
        "package": "py7zr",
        "reason": "Was not exploitable",
        "expires": "2020-01-01",
    }])
    report = run_audit(
        advisory_fetcher=_critical_advisory,
        waiver_path=waivers,
        requirements_path=req,
        today=date(2025, 6, 1),
    )
    assert report.passed is False
    assert len(report.expired_waivers) == 1
    assert len(report.unwaived) == 1


def test_load_waivers_from_file(tmp_path):
    path = _fake_waivers(tmp_path, [
        {"id": "A", "package": "x", "reason": "test", "expires": "2030-01-01"},
        {"id": "B", "package": "y", "reason": "test2", "expires": ""},
    ])
    waivers = load_waivers(path)
    assert len(waivers) == 2
    assert waivers[0].id == "A"


def test_load_waivers_missing_file(tmp_path):
    assert load_waivers(tmp_path / "nope.json") == []


def test_sbom_json_structure(tmp_path):
    req = _fake_requirements(tmp_path, "py7zr==1.1.3\n")
    report = run_audit(
        advisory_fetcher=_critical_advisory,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    sbom = sbom_json(report)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.4"
    assert len(sbom["components"]) == 1
    comp = sbom["components"][0]
    assert comp["name"] == "py7zr"
    assert comp["version"] == "1.1.3"
    assert len(comp["vulnerabilities"]) == 1
    assert comp["vulnerabilities"][0]["id"] == "PYSEC-2025-9999"


def test_format_report_pass():
    report = AuditReport(
        packages=[PackageInfo("py7zr", "py7zr", "1.1.3", "1.1.3", "LGPL-2.1")],
    )
    text = format_report(report)
    assert "PASS" in text
    assert "py7zr" in text


def test_format_report_fail_with_unwaived():
    adv = Advisory("PYSEC-1", "py7zr", "critical", "bad things", "2.0.0")
    report = AuditReport(
        packages=[PackageInfo("py7zr", "py7zr", "1.1.3", "1.1.3", "LGPL-2.1", [adv])],
        unwaived=[adv],
    )
    text = format_report(report)
    assert "FAIL" in text
    assert "UNWAIVED" in text
    assert "PYSEC-1" in text


def test_format_report_shows_version_drift():
    report = AuditReport(
        packages=[PackageInfo("py7zr", "py7zr", "1.1.3", "1.0.0", "LGPL-2.1")],
    )
    text = format_report(report)
    assert "DRIFT" in text


def test_audit_fails_on_empty_requirements(tmp_path):
    req = _fake_requirements(tmp_path, "# nothing here\n")
    report = run_audit(
        advisory_fetcher=_no_advisories,
        waiver_path=tmp_path / "waivers.json",
        requirements_path=req,
    )
    assert report.passed is False
    assert any("No pinned" in e for e in report.errors)
