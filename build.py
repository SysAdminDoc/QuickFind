#!/usr/bin/env python3
"""
QuickFind Build Script - PyInstaller packaging
Produces a single-folder or single-file distribution.

Usage:
    python build.py              # Build single-folder dist
    python build.py --onefile    # Build single-file exe
    python build.py --msix       # Build MSIX package from one-file exe
    python build.py --winget     # Write winget manifests for an existing MSIX
    python build.py --clean      # Clean build artifacts
"""

import importlib
from dataclasses import dataclass, field
import hashlib
import os
import platform
import re
import subprocess
import sys
import shutil
import stat
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from core.version import APP_NAME, VERSION
from core.runtime_info import RUNTIME_PACKAGES, runtime_matrix

ROOT = Path(__file__).parent
DIST = ROOT / 'dist'
BUILD = ROOT / 'build'
SPEC = ROOT / 'QuickFind.spec'
ASSETS = ROOT / 'assets'
ICON = ASSETS / 'quickfind.ico'
ROOT_ICON = ROOT / 'icon.png'
PACKAGING = ROOT / 'packaging'
WINGET = PACKAGING / 'winget'

ENTRY = "quickfind.py"
PACKAGE_IDENTIFIER = "SysAdminDoc.QuickFind"
PUBLISHER = "CN=SysAdminDoc"
PUBLISHER_DISPLAY = "SysAdminDoc"
MSIX_NAME = f"{APP_NAME}.msix"
APPINSTALLER_NAME = f"{APP_NAME}.appinstaller"

@dataclass
class ReleaseCheckReport:
    checks: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def ok(self, message: str) -> None:
        self.checks.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def fail(self, message: str) -> None:
        self.errors.append(message)


def print_runtime_matrix() -> None:
    print("[*] Runtime matrix:")
    for key, value in runtime_matrix().items():
        print(f"    {key}: {value}")


def require_pyinstaller(import_module=importlib.import_module):
    """Fail clearly when the pinned build dependency is not installed."""
    try:
        import_module("PyInstaller")
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is missing. Run: python -m pip install -r requirements.txt"
        ) from exc


def clean():
    """Remove build artifacts."""
    for d in [DIST, BUILD]:
        if d.exists():
            _remove_tree(d)
            print(f"[*] Removed {d}")
    if SPEC.exists():
        _remove_file(SPEC)
        print(f"[*] Removed {SPEC}")


def _remove_tree(path: Path) -> None:
    try:
        shutil.rmtree(path, onerror=_chmod_and_retry)
    except (OSError, PermissionError) as exc:
        raise SystemExit(_locked_path_message(path, exc)) from exc


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
        except (OSError, PermissionError) as exc:
            raise SystemExit(_locked_path_message(path, exc)) from exc
    except OSError as exc:
        raise SystemExit(_locked_path_message(path, exc)) from exc


def _chmod_and_retry(function, path: str, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except Exception:
        raise exc_info[1]


def _locked_path_message(path: Path, exc: BaseException) -> str:
    return (
        f"Cannot clean {path}: {exc}. Close any running QuickFind build, "
        "Explorer preview, terminal, or antivirus scan holding the artifact and retry."
    )


def msix_version(version: str = VERSION) -> str:
    parts = [int(part) for part in version.split(".")]
    if len(parts) > 4:
        raise ValueError("MSIX versions support at most four numeric parts")
    while len(parts) < 4:
        parts.append(0)
    return ".".join(str(part) for part in parts)


def _release_asset_url(asset_name: str, version: str = VERSION) -> str:
    return (
        "https://github.com/SysAdminDoc/QuickFind/releases/download/"
        f"v{version}/{asset_name}"
    )


def render_msix_manifest(version: str = VERSION, architecture: str = "x64") -> str:
    package_version = msix_version(version)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
  xmlns:desktop="http://schemas.microsoft.com/appx/manifest/desktop/windows10"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap3 desktop rescap">
  <Identity Name="{PACKAGE_IDENTIFIER}" Publisher="{PUBLISHER}" Version="{package_version}" ProcessorArchitecture="{architecture}" />
  <Properties>
    <DisplayName>{APP_NAME}</DisplayName>
    <PublisherDisplayName>{PUBLISHER_DISPLAY}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>
  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
  <Applications>
    <Application Id="{APP_NAME}" Executable="{APP_NAME}.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{APP_NAME}" Description="Lightning-fast file search" BackgroundColor="#1e1e2e" Square44x44Logo="Assets\\SmallLogo.png" Square150x150Logo="Assets\\Logo.png" />
      <Extensions>
        <uap:Extension Category="windows.protocol">
          <uap:Protocol Name="quickfind" />
        </uap:Extension>
        <uap3:Extension Category="windows.appExecutionAlias" Executable="{APP_NAME}.exe" EntryPoint="Windows.FullTrustApplication">
          <uap3:AppExecutionAlias>
            <desktop:ExecutionAlias Alias="quickfind.exe" />
          </uap3:AppExecutionAlias>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>
</Package>
"""


def render_appinstaller(msix_uri: str, appinstaller_uri: str,
                        version: str = VERSION) -> str:
    package_version = msix_version(version)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AppInstaller
  Uri="{appinstaller_uri}"
  Version="{package_version}"
  xmlns="http://schemas.microsoft.com/appx/appinstaller/2018">
  <MainPackage
    Name="{PACKAGE_IDENTIFIER}"
    Publisher="{PUBLISHER}"
    Version="{package_version}"
    Uri="{msix_uri}"
    ProcessorArchitecture="x64" />
  <UpdateSettings>
    <OnLaunch HoursBetweenUpdateChecks="24" ShowPrompt="false" UpdateBlocksActivation="false" />
    <AutomaticBackgroundTask />
  </UpdateSettings>
</AppInstaller>
"""


def render_winget_manifests(installer_url: str, installer_sha256: str,
                            version: str = VERSION) -> dict[str, str]:
    return {
        f"{PACKAGE_IDENTIFIER}.yaml": f"""PackageIdentifier: {PACKAGE_IDENTIFIER}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.9.0
""",
        f"{PACKAGE_IDENTIFIER}.installer.yaml": f"""PackageIdentifier: {PACKAGE_IDENTIFIER}
PackageVersion: {version}
InstallerType: msix
Installers:
- Architecture: x64
  InstallerUrl: {installer_url}
  InstallerSha256: {installer_sha256}
ManifestType: installer
ManifestVersion: 1.9.0
""",
        f"{PACKAGE_IDENTIFIER}.locale.en-US.yaml": f"""PackageIdentifier: {PACKAGE_IDENTIFIER}
PackageVersion: {version}
PackageLocale: en-US
Publisher: {PUBLISHER_DISPLAY}
PublisherUrl: https://github.com/SysAdminDoc
PackageName: {APP_NAME}
PackageUrl: https://github.com/SysAdminDoc/QuickFind
License: MIT
LicenseUrl: https://github.com/SysAdminDoc/QuickFind/blob/main/LICENSE
ShortDescription: Lightning-fast file search powered by NTFS MFT, SQLite cache, and a PyQt6 interface.
Tags:
- file-search
- ntfs
- sqlite
- pyqt6
ManifestType: defaultLocale
ManifestVersion: 1.9.0
""",
    }


def _find_windows_sdk_tool(tool: str) -> str:
    candidates = [
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64") / tool,
        Path(r"C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64") / tool,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which(tool)
    if found:
        return found
    raise SystemExit(f"{tool} was not found in the Windows SDK or PATH")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _prepare_msix_assets(staging: Path) -> None:
    asset_dir = staging / "Assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    source = ROOT_ICON if ROOT_ICON.exists() else ICON
    if not source.exists():
        raise SystemExit("MSIX packaging requires icon.png or assets/quickfind.ico")
    for name in ["Logo.png", "SmallLogo.png", "StoreLogo.png"]:
        shutil.copy2(source, asset_dir / name)


def build_msix(sign: bool = True,
               installer_url: str | None = None,
               appinstaller_url: str | None = None) -> Path:
    """Build an MSIX package from the one-file executable."""
    if platform.system() != "Windows":
        raise SystemExit("MSIX packaging requires Windows")

    exe = DIST / f"{APP_NAME}.exe"
    if not exe.exists():
        build(onefile=True)

    staging = BUILD / "msix" / APP_NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copy2(exe, staging / f"{APP_NAME}.exe")
    _prepare_msix_assets(staging)
    (staging / "AppxManifest.xml").write_text(
        render_msix_manifest(),
        encoding="utf-8",
    )

    msix_path = DIST / MSIX_NAME
    makeappx = _find_windows_sdk_tool("makeappx.exe")
    subprocess.run(
        [makeappx, "pack", "/d", str(staging), "/p", str(msix_path), "/o"],
        check=True,
    )
    print(f"[+] MSIX package: {msix_path}")

    if sign:
        signtool = _find_windows_sdk_tool("signtool.exe")
        sign_cmd = [
            signtool, "sign", "/fd", "SHA256", "/tr",
            "http://timestamp.digicert.com", "/td", "SHA256",
        ]
        pfx = os.environ.get("QUICKFIND_SIGN_PFX")
        if pfx:
            sign_cmd.extend(["/f", pfx])
            password = os.environ.get("QUICKFIND_SIGN_PFX_PASSWORD")
            if password:
                sign_cmd.extend(["/p", password])
        else:
            sign_cmd.append("/a")
        sign_cmd.append(str(msix_path))
        subprocess.run(
            sign_cmd,
            check=True,
        )
        print(f"[+] Signed MSIX package: {msix_path}")

    msix_uri = installer_url or _release_asset_url(MSIX_NAME)
    appinstaller_uri = appinstaller_url or _release_asset_url(APPINSTALLER_NAME)
    appinstaller = DIST / APPINSTALLER_NAME
    appinstaller.write_text(
        render_appinstaller(msix_uri, appinstaller_uri),
        encoding="utf-8",
    )
    print(f"[+] App Installer file: {appinstaller}")
    return msix_path


def write_winget_manifests(installer_url: str | None = None,
                           msix_path: Path | None = None) -> None:
    """Write winget manifests for the current version."""
    msix_path = msix_path or DIST / MSIX_NAME
    if not msix_path.exists():
        raise SystemExit("Build the MSIX before generating winget manifests")
    WINGET.mkdir(parents=True, exist_ok=True)
    url = installer_url or _release_asset_url(MSIX_NAME)
    manifests = render_winget_manifests(url, _sha256_file(msix_path))
    for filename, content in manifests.items():
        path = WINGET / filename
        path.write_text(content, encoding="utf-8")
        print(f"[+] Wrote winget manifest: {path}")


def release_check(
    *,
    skip_remote: bool = False,
    allow_unsigned: bool = False,
    url_exists=None,
    signature_status=None,
) -> ReleaseCheckReport:
    """Validate local release metadata before publishing artifacts."""
    url_exists = url_exists or _release_asset_exists
    signature_status = signature_status or _msix_signature_status
    report = ReleaseCheckReport()
    expected_version = VERSION
    expected_msix_version = msix_version(expected_version)
    expected_msix_url = _release_asset_url(MSIX_NAME, expected_version)
    expected_appinstaller_url = _release_asset_url(APPINSTALLER_NAME, expected_version)
    msix_path = DIST / MSIX_NAME
    appinstaller_path = DIST / APPINSTALLER_NAME
    installer_manifest = WINGET / f"{PACKAGE_IDENTIFIER}.installer.yaml"

    _check_readme_version(report, expected_version)
    manifests = _read_winget_manifests(report)
    for filename, manifest in manifests.items():
        package_version = _manifest_value(manifest, "PackageVersion")
        if package_version == expected_version:
            report.ok(f"{filename} version matches {expected_version}")
        else:
            report.fail(f"{filename} PackageVersion is {package_version or 'missing'}, expected {expected_version}")

    installer_text = manifests.get(installer_manifest.name, "")
    installer_url = _manifest_value(installer_text, "InstallerUrl")
    if installer_url == expected_msix_url:
        report.ok("winget InstallerUrl matches the current release URL")
    else:
        report.fail(f"winget InstallerUrl is {installer_url or 'missing'}, expected {expected_msix_url}")

    installer_hash = _manifest_value(installer_text, "InstallerSha256")
    msix_hash = ""
    if msix_path.exists():
        msix_hash = _sha256_file(msix_path)
        if installer_hash == msix_hash:
            report.ok("winget InstallerSha256 matches the local MSIX")
        else:
            report.fail(f"winget InstallerSha256 is {installer_hash or 'missing'}, expected {msix_hash}")
        msix_manifest_version = _msix_manifest_version(msix_path)
        if msix_manifest_version == expected_msix_version:
            report.ok("MSIX manifest version matches the application version")
        else:
            report.fail(
                f"MSIX manifest version is {msix_manifest_version or 'missing'}, "
                f"expected {expected_msix_version}"
            )
        status = signature_status(msix_path)
        if status == "Valid":
            report.ok("MSIX signature is valid")
        elif allow_unsigned:
            report.warn(f"MSIX signature status is {status}; unsigned local package allowed")
        else:
            report.fail(f"MSIX signature status is {status}; sign the package or pass --allow-unsigned for local-only checks")
    else:
        report.fail(f"Missing MSIX artifact: {msix_path}")

    if appinstaller_path.exists():
        appinstaller = _read_appinstaller(appinstaller_path)
        _check_value(report, "App Installer Version", appinstaller.get("version"), expected_msix_version)
        _check_value(report, "App Installer Uri", appinstaller.get("uri"), expected_appinstaller_url)
        _check_value(report, "App Installer MainPackage Version", appinstaller.get("main_version"), expected_msix_version)
        _check_value(report, "App Installer MainPackage Uri", appinstaller.get("main_uri"), expected_msix_url)
    else:
        report.fail(f"Missing App Installer feed: {appinstaller_path}")

    if not skip_remote:
        for url in (expected_msix_url, expected_appinstaller_url):
            if url_exists(url):
                report.ok(f"GitHub release asset exists: {url}")
            else:
                report.fail(f"GitHub release asset is missing or unreachable: {url}")
    else:
        report.warn("Skipped GitHub release asset checks")

    return report


def print_release_check_report(report: ReleaseCheckReport) -> None:
    for message in report.checks:
        print(f"[+] {message}")
    for message in report.warnings:
        print(f"[!] {message}")
    for message in report.errors:
        print(f"[-] {message}")


def _read_winget_manifests(report: ReleaseCheckReport) -> dict[str, str]:
    manifests = {}
    for filename in (
        f"{PACKAGE_IDENTIFIER}.yaml",
        f"{PACKAGE_IDENTIFIER}.installer.yaml",
        f"{PACKAGE_IDENTIFIER}.locale.en-US.yaml",
    ):
        path = WINGET / filename
        if not path.exists():
            report.fail(f"Missing winget manifest: {path}")
            manifests[filename] = ""
            continue
        manifests[filename] = path.read_text(encoding="utf-8")
    return manifests


def _check_readme_version(report: ReleaseCheckReport, version: str) -> None:
    readme = ROOT / "README.md"
    if not readme.exists():
        report.fail("README.md is missing")
        return
    text = readme.read_text(encoding="utf-8")
    expected_header = f"# {APP_NAME} v{version}"
    expected_badge = f"Version-v{version}-"
    if expected_header in text and expected_badge in text:
        report.ok("README version header and badge match")
    else:
        report.fail(f"README version header or badge does not match v{version}")


def _manifest_value(text: str, key: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _check_value(report: ReleaseCheckReport, label: str, actual: str | None, expected: str) -> None:
    if actual == expected:
        report.ok(f"{label} matches")
    else:
        report.fail(f"{label} is {actual or 'missing'}, expected {expected}")


def _read_appinstaller(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    data = {
        "version": root.attrib.get("Version", ""),
        "uri": root.attrib.get("Uri", ""),
    }
    for child in root:
        if _xml_local_name(child.tag) == "MainPackage":
            data["main_version"] = child.attrib.get("Version", "")
            data["main_uri"] = child.attrib.get("Uri", "")
            break
    return data


def _msix_manifest_version(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as package:
            manifest = ET.fromstring(package.read("AppxManifest.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
        return ""
    for child in manifest:
        if _xml_local_name(child.tag) == "Identity":
            return child.attrib.get("Version", "")
    return ""


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _msix_signature_status(path: Path) -> str:
    if platform.system() != "Windows":
        return "Skipped"
    literal = str(path).replace("'", "''")
    command = (
        "$sig = Get-AuthenticodeSignature -LiteralPath "
        f"'{literal}'; $sig.Status"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Unknown ({exc})"
    if result.returncode != 0:
        first_error = next((line.strip() for line in result.stderr.splitlines() if line.strip()), "")
        return f"Unknown ({first_error or result.returncode})"
    status = result.stdout.strip()
    return status or f"Unknown ({result.returncode})"


def _release_asset_exists(url: str, timeout: float = 10.0) -> bool:
    request = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except urllib.error.HTTPError as exc:
        if exc.code != 405:
            return False
    except (urllib.error.URLError, TimeoutError, OSError):
        return False

    request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def build(onefile=False):
    """Build the application with PyInstaller."""
    require_pyinstaller()

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--name', APP_NAME,
        '--noconfirm',
        '--clean',
        '--windowed',
    ]

    if onefile:
        cmd.append('--onefile')
    else:
        cmd.append('--onedir')

    # Icon
    if ICON.exists():
        cmd.extend(['--icon', str(ICON)])

    # Hidden imports for dynamic modules
    hidden = [
        'core.ntfs', 'core.index', 'core.cache', 'core.search',
        'core.query_slots', 'core.archives', 'core.dialog_switch',
        'core.localization',
        'core.network_shares', 'core.platform_engines',
        'core.content', 'core.content.adapters', 'core.content.indexer',
        'core.content.sandbox', 'core.worker_isolation', 'core.sqlite_compat',
        'core.runtime_info', 'core.support_bundle',
        'gui.main_window', 'gui.results_view', 'gui.settings_dialog',
        'gui.diagnostics_dialog',
        'gui.theme', 'gui.tray', 'gui.accessibility', 'gui.help_docs',
        'cli.es', 'server.http_server', 'py7zr',
        'pdfplumber', 'docx', 'pptx',
        'watchdog', 'watchdog.events', 'watchdog.observers',
        'service.ipc', 'service.windows_service',
        'pythoncom', 'pywintypes', 'win32com', 'win32com.client',
        'win32serviceutil', 'win32service', 'win32event', 'servicemanager',
        'win32gui', 'win32con', 'win32cred', 'win32wnet', 'win32netcon',
    ]
    for h in hidden:
        cmd.extend(['--hidden-import', h])

    # Add data files
    if ASSETS.exists():
        cmd.extend(['--add-data', f'{ASSETS};assets'])

    # Entry point
    cmd.append(str(ROOT / ENTRY))

    print(f"[*] Building {APP_NAME} v{VERSION} ({'onefile' if onefile else 'onedir'})...")
    print_runtime_matrix()
    print(f"    Command: {' '.join(cmd)}")

    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode == 0:
        if onefile:
            exe_path = DIST / f'{APP_NAME}.exe'
        else:
            exe_path = DIST / APP_NAME / f'{APP_NAME}.exe'
        print(f"\n[+] Build successful!")
        print(f"    Output: {exe_path}")
    else:
        print(f"\n[-] Build failed with exit code {result.returncode}")
        sys.exit(1)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=f'Build {APP_NAME}')
    parser.add_argument('--onefile', action='store_true', help='Build single-file exe')
    parser.add_argument('--clean', action='store_true', help='Clean build artifacts')
    parser.add_argument('--msix', action='store_true', help='Build MSIX package from the one-file exe')
    parser.add_argument('--skip-sign', action='store_true', help='Skip MSIX signing')
    parser.add_argument('--winget', action='store_true', help='Write winget manifests for the MSIX')
    parser.add_argument('--installer-url', help='Release URL for the MSIX in App Installer and winget manifests')
    parser.add_argument('--appinstaller-url', help='Release URL for the .appinstaller update feed')
    parser.add_argument('--release-check', action='store_true', help='Validate local release artifacts and metadata')
    parser.add_argument('--skip-remote', action='store_true', help='Skip GitHub release asset checks during --release-check')
    parser.add_argument('--allow-unsigned', action='store_true', help='Allow unsigned MSIX packages during --release-check')
    parser.add_argument('--dep-audit', action='store_true', help='Run dependency advisory, license, and SBOM check')
    parser.add_argument('--sbom', action='store_true', help='Emit CycloneDX SBOM JSON alongside --dep-audit')
    args = parser.parse_args()

    if args.dep_audit:
        from core.dep_audit import run_audit, format_report, sbom_json
        audit = run_audit()
        print(format_report(audit))
        if args.sbom:
            sbom = sbom_json(audit)
            sbom_path = DIST / "sbom.json"
            DIST.mkdir(parents=True, exist_ok=True)
            sbom_path.write_text(json.dumps(sbom, indent=2), encoding="utf-8")
            print(f"\n[+] SBOM written to {sbom_path}")
        if not audit.passed:
            sys.exit(1)
        return

    if args.release_check:
        report = release_check(
            skip_remote=args.skip_remote,
            allow_unsigned=args.allow_unsigned,
        )
        print_release_check_report(report)
        if not report.passed:
            sys.exit(1)
        return

    if args.clean:
        clean()
        return

    if args.msix:
        msix_path = build_msix(
            sign=not args.skip_sign,
            installer_url=args.installer_url,
            appinstaller_url=args.appinstaller_url,
        )
        if args.winget:
            write_winget_manifests(args.installer_url, msix_path)
        return

    if args.winget:
        write_winget_manifests(args.installer_url)
        return

    build(onefile=args.onefile)


if __name__ == '__main__':
    main()
