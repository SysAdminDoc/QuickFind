"""Workspace root helpers for constraining searches to named root sets."""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Callable, Optional


def parse_workspace_roots(value: str | Iterable[str] | None) -> list[str]:
    """Return normalized, de-duplicated workspace roots."""
    if value is None:
        return []
    if isinstance(value, str):
        raw_parts = value.replace("\n", ";").split(";")
    else:
        raw_parts = value

    roots: list[str] = []
    seen: set[str] = set()
    for raw in raw_parts:
        text = str(raw).strip().strip('"').strip("'")
        if not text:
            continue
        normalized = normalize_workspace_root(text)
        key = _workspace_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        roots.append(normalized)
    return roots


def normalize_workspace_root(root: str) -> str:
    text = os.path.expandvars(os.path.expanduser(root.strip()))
    return os.path.normpath(text)


def workspace_roots_text(roots: Iterable[str] | None) -> str:
    return ";".join(parse_workspace_roots(roots))


def path_matches_workspace(path: str, roots: Iterable[str] | None) -> bool:
    workspace_roots = parse_workspace_roots(roots)
    if not workspace_roots:
        return True
    if not path:
        return False

    path_key = _workspace_key(os.path.normpath(path))
    for root in workspace_roots:
        root_key = _workspace_key(root)
        try:
            if os.path.commonpath([path_key, root_key]) == root_key:
                return True
        except ValueError:
            continue
    return False


def filter_entries_by_workspace(
    entries: Iterable,
    index,
    roots: Iterable[str] | None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> list:
    workspace_roots = parse_workspace_roots(roots)
    if not workspace_roots:
        return list(entries)

    filtered = []
    for entry in entries:
        if cancel_check and cancel_check():
            break
        try:
            path = entry.get_path(index)
        except Exception:
            continue
        if path_matches_workspace(path, workspace_roots):
            filtered.append(entry)
    return filtered


def _workspace_key(path: str) -> str:
    key = os.path.normcase(os.path.normpath(path))
    drive, tail = os.path.splitdrive(key)
    if drive and tail in ("\\", "/"):
        return drive + "\\"
    return key.rstrip("\\/")
