#!/usr/bin/env python3
"""
QuickFind Build Script - PyInstaller packaging
Produces a single-folder or single-file distribution.

Usage:
    python build.py              # Build single-folder dist
    python build.py --onefile    # Build single-file exe
    python build.py --clean      # Clean build artifacts
"""

import importlib
from importlib import metadata as importlib_metadata
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

ENTRY = "quickfind.py"

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
        'core.ntfs', 'core.index', 'core.cache', 'core.search', 'core.archives',
        'core.content', 'core.content.adapters', 'core.content.indexer',
        'core.sqlite_compat',
        'gui.main_window', 'gui.results_view', 'gui.settings_dialog',
        'gui.theme', 'gui.tray', 'cli.es', 'server.http_server', 'py7zr',
        'pdfplumber', 'docx', 'pptx',
        'service.ipc', 'service.windows_service',
        'win32serviceutil', 'win32service', 'win32event', 'servicemanager',
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
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    build(onefile=args.onefile)


if __name__ == '__main__':
    main()
