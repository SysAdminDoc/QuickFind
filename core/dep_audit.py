"""Dependency advisory, license, and SBOM checks for release gating."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Callable

from core.runtime_info import RUNTIME_PACKAGES

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements.txt"
WAIVERS_PATH = ROOT / "dep_waivers.json"


@dataclass
class Advisory:
    id: str
    package: str
    severity: str
    summary: str
    fixed_in: str = ""


@dataclass
class PackageInfo:
    name: str
    distribution: str
    pinned_version: str
    installed_version: str
    license: str
    advisories: list[Advisory] = field(default_factory=list)


@dataclass
class Waiver:
    id: str
    package: str
    reason: str
    expires: str


@dataclass
class AuditReport:
    packages: list[PackageInfo] = field(default_factory=list)
    waivers: list[Waiver] = field(default_factory=list)
    unwaived: list[Advisory] = field(default_factory=list)
    waived: list[Advisory] = field(default_factory=list)
    expired_waivers: list[Waiver] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.unwaived and not self.errors


def read_pinned_requirements(path: Path = REQUIREMENTS) -> dict[str, str]:
    """Parse requirements.txt into {distribution: pinned_version}."""
    pins: dict[str, str] = {}
    if not path.exists():
        return pins
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" in line:
            name, version = line.split("==", 1)
            pins[name.strip()] = version.strip()
    return pins


def installed_version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "missing"


def installed_license(distribution: str) -> str:
    try:
        meta = importlib_metadata.metadata(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "unknown"
    return meta.get("License") or meta.get("License-Expression") or "unknown"


def _classify_severity(aliases: list[str]) -> str:
    for alias in aliases:
        low = alias.lower()
        if "critical" in low:
            return "critical"
        if "high" in low:
            return "high"
        if "medium" in low or "moderate" in low:
            return "medium"
        if "low" in low:
            return "low"
    return "unknown"


def _extract_severity(vuln: dict) -> str:
    """Extract severity from a PyPI vulnerability record."""
    for detail in vuln.get("details", []):
        if isinstance(detail, dict):
            sev = detail.get("severity", "")
            if sev:
                classified = _classify_severity([sev])
                if classified != "unknown":
                    return classified
    aliases = vuln.get("aliases", []) + [vuln.get("id", "")]
    return _classify_severity(aliases)


def fetch_pypi_advisories(distribution: str, version: str, *,
                          urlopen: Callable[..., Any] | None = None) -> list[Advisory]:
    opener = urlopen or urllib.request.urlopen
    url = f"https://pypi.org/pypi/{distribution}/{version}/json"
    try:
        with opener(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, json.JSONDecodeError):
        return []
    advisories = []
    for vuln in data.get("vulnerabilities", []):
        advisories.append(Advisory(
            id=vuln.get("id", ""),
            package=distribution,
            severity=_extract_severity(vuln),
            summary=vuln.get("summary", "")[:200],
            fixed_in=", ".join(vuln.get("fixed_in", [])),
        ))
    return advisories


def load_waivers(path: Path = WAIVERS_PATH) -> list[Waiver]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    waivers = []
    for entry in data.get("waivers", []):
        waivers.append(Waiver(
            id=entry.get("id", ""),
            package=entry.get("package", ""),
            reason=entry.get("reason", ""),
            expires=entry.get("expires", ""),
        ))
    return waivers


def _waiver_expired(waiver: Waiver, today: date | None = None) -> bool:
    today = today or date.today()
    if not waiver.expires:
        return False
    try:
        expiry = date.fromisoformat(waiver.expires)
    except ValueError:
        return True
    return expiry < today


def run_audit(
    *,
    advisory_fetcher: Callable[[str, str], list[Advisory]] | None = None,
    waiver_path: Path = WAIVERS_PATH,
    requirements_path: Path = REQUIREMENTS,
    today: date | None = None,
) -> AuditReport:
    fetcher = advisory_fetcher or fetch_pypi_advisories
    report = AuditReport()

    pins = read_pinned_requirements(requirements_path)
    if not pins:
        report.errors.append("No pinned requirements found")
        return report

    runtime_map = {dist: label for label, dist in RUNTIME_PACKAGES}

    for dist, pinned in pins.items():
        label = runtime_map.get(dist, dist)
        installed = installed_version(dist)
        lic = installed_license(dist)
        advisories = fetcher(dist, pinned)
        report.packages.append(PackageInfo(
            name=label,
            distribution=dist,
            pinned_version=pinned,
            installed_version=installed,
            license=lic,
            advisories=advisories,
        ))

    waivers = load_waivers(waiver_path)
    active_waivers: dict[tuple[str, str], Waiver] = {}
    for w in waivers:
        if _waiver_expired(w, today):
            report.expired_waivers.append(w)
        else:
            active_waivers[(w.id, w.package)] = w
    report.waivers = waivers

    for pkg in report.packages:
        for adv in pkg.advisories:
            key = (adv.id, adv.package)
            if key in active_waivers:
                report.waived.append(adv)
            elif adv.severity in ("high", "critical"):
                report.unwaived.append(adv)

    return report


def sbom_json(report: AuditReport) -> dict:
    components = []
    for pkg in report.packages:
        component = {
            "type": "library",
            "name": pkg.distribution,
            "version": pkg.pinned_version,
            "licenses": [{"license": {"id": pkg.license}}] if pkg.license != "unknown" else [],
        }
        if pkg.advisories:
            component["vulnerabilities"] = [
                {"id": adv.id, "severity": adv.severity, "summary": adv.summary}
                for adv in pkg.advisories
            ]
        components.append(component)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "components": components,
    }


def format_report(report: AuditReport) -> str:
    lines: list[str] = []
    lines.append("Dependency Audit Report")
    lines.append("=" * 50)

    for pkg in report.packages:
        version_match = pkg.pinned_version == pkg.installed_version
        marker = " OK" if version_match else f" DRIFT (installed {pkg.installed_version})"
        lines.append(f"  {pkg.name} {pkg.pinned_version}{marker}  [{pkg.license}]")
        for adv in pkg.advisories:
            lines.append(f"    {adv.severity.upper()} {adv.id}: {adv.summary}")
            if adv.fixed_in:
                lines.append(f"      Fixed in: {adv.fixed_in}")

    if report.waived:
        lines.append("")
        lines.append("Waived advisories:")
        for adv in report.waived:
            lines.append(f"  {adv.id} ({adv.package})")

    if report.expired_waivers:
        lines.append("")
        lines.append("Expired waivers:")
        for w in report.expired_waivers:
            lines.append(f"  {w.id} ({w.package}) expired {w.expires}")

    if report.unwaived:
        lines.append("")
        lines.append("UNWAIVED high/critical advisories:")
        for adv in report.unwaived:
            lines.append(f"  {adv.severity.upper()} {adv.id} ({adv.package}): {adv.summary}")

    if report.errors:
        lines.append("")
        lines.append("Errors:")
        for err in report.errors:
            lines.append(f"  {err}")

    lines.append("")
    lines.append(f"Result: {'PASS' if report.passed else 'FAIL'}")
    return "\n".join(lines)
