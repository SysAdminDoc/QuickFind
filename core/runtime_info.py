"""Runtime dependency metadata shared by diagnostics and release checks."""

import platform
import sqlite3
import sys
from importlib import metadata as importlib_metadata

from core.sqlite_compat import fts5_gate_status

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


def package_version(distribution: str) -> str:
    try:
        return importlib_metadata.version(distribution)
    except importlib_metadata.PackageNotFoundError:
        return "missing"


def runtime_matrix() -> dict[str, str]:
    """Return the runtime versions that affect support and release reproducibility."""
    matrix = {
        "Python": sys.version.split()[0],
        "Platform": platform.platform(),
        "SQLite": sqlite3.sqlite_version,
        "SQLite FTS5": fts5_gate_status(sqlite3.sqlite_version),
    }
    for label, distribution in RUNTIME_PACKAGES:
        matrix[label] = package_version(distribution)
    return matrix
