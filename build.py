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
from importlib import metadata as importlib_metadata
import hashlib
import os
import platform
import subprocess
import sys
import shutil
import sqlite3
from pathlib import Path

from core.version import APP_NAME, VERSION
from core.sqlite_compat import fts5_gate_status

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

RUNTIME_PACKAGES = [
    ("PyQt6", "PyQt6"),
    ("PyQt6-Qt6", "PyQt6-Qt6"),
    ("PyQt6-sip", "PyQt6-sip"),
    ("PyInstaller", "pyinstaller"),
    ("pywin32", "pywin32"),
    ("pdfplumber", "pdfplumber"),
    ("py7zr", "py7zr"),
    ("python-docx", "python-docx"),
    ("python-pptx", "python-pptx"),
    ("watchdog", "watchdog"),
]


def _package_version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "missing"


def runtime_matrix() -> dict[str, str]:
    """Return the build/runtime versions that affect release reproducibility."""
    matrix = {
        "Python": sys.version.split()[0],
        "Platform": platform.platform(),
        "SQLite": sqlite3.sqlite_version,
        "SQLite FTS5": fts5_gate_status(sqlite3.sqlite_version),
    }
    for label, distribution in RUNTIME_PACKAGES:
        matrix[label] = _package_version(distribution)
    return matrix


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
            shutil.rmtree(d)
            print(f"[*] Removed {d}")
    if SPEC.exists():
        SPEC.unlink()
        print(f"[*] Removed {SPEC}")


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
        'core.sqlite_compat',
        'gui.main_window', 'gui.results_view', 'gui.settings_dialog',
        'gui.diagnostics_dialog',
        'gui.theme', 'gui.tray', 'gui.accessibility',
        'cli.es', 'server.http_server', 'py7zr',
        'pdfplumber', 'docx', 'pptx',
        'watchdog', 'watchdog.events', 'watchdog.observers',
        'service.ipc', 'service.windows_service',
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
    args = parser.parse_args()

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
