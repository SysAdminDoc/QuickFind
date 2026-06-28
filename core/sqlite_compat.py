"""SQLite runtime compatibility checks."""

import sqlite3

MIN_SAFE_FTS5_SQLITE_VERSION = (3, 53, 2)
MIN_SAFE_FTS5_SQLITE_VERSION_TEXT = ".".join(str(part) for part in MIN_SAFE_FTS5_SQLITE_VERSION)


def sqlite_version_tuple(version: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for piece in version.split("."):
        digits = ""
        for char in piece:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
        if len(parts) == 3:
            break

    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_fts5_sqlite_version_safe(version: str = sqlite3.sqlite_version) -> bool:
    return sqlite_version_tuple(version) >= MIN_SAFE_FTS5_SQLITE_VERSION


def fts5_gate_status(version: str = sqlite3.sqlite_version) -> str:
    if is_fts5_sqlite_version_safe(version):
        return f"FTS5 allowed (SQLite {version})"
    return (
        f"FTS5 disabled: SQLite {version} is below patched minimum "
        f"{MIN_SAFE_FTS5_SQLITE_VERSION_TEXT}"
    )
