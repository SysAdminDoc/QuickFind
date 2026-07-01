"""Duplicate review workflow: group, preview keep/delete candidates, safe remediation."""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Sequence

from core.index import FileEntry, FileIndex


@dataclass(frozen=True)
class DuplicateGroup:
    key: str
    entries: tuple[FileEntry, ...]
    total_size: int = 0
    recoverable_size: int = 0

    @property
    def count(self) -> int:
        return len(self.entries)


@dataclass
class KeepRule:
    """Select which entry to keep in a duplicate group."""
    prefer_shortest_path: bool = True
    prefer_newest: bool = False
    prefer_root: str = ""


@dataclass(frozen=True)
class RemediationPreview:
    keep: FileEntry
    delete_candidates: tuple[FileEntry, ...]
    recoverable_bytes: int = 0


@dataclass
class RemediationResult:
    recycled: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def group_by_name(entries: Sequence[FileEntry], index: FileIndex) -> list[DuplicateGroup]:
    """Group entries by lowercase filename, keeping only groups with 2+ members."""
    groups: dict[str, list[FileEntry]] = defaultdict(list)
    for entry in entries:
        if entry.is_dir:
            continue
        groups[entry.name.lower()].append(entry)

    result = []
    for key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        total = sum(getattr(e, "size", 0) or 0 for e in members)
        result.append(DuplicateGroup(
            key=key,
            entries=tuple(members),
            total_size=total,
            recoverable_size=total - (max(getattr(e, "size", 0) or 0 for e in members) if members else 0),
        ))
    return result


def group_by_size(entries: Sequence[FileEntry], index: FileIndex) -> list[DuplicateGroup]:
    """Group entries by file size, keeping only groups with 2+ members."""
    groups: dict[int, list[FileEntry]] = defaultdict(list)
    for entry in entries:
        if entry.is_dir:
            continue
        size = getattr(entry, "size", 0) or 0
        groups[size].append(entry)

    result = []
    for size, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        result.append(DuplicateGroup(
            key=str(size),
            entries=tuple(members),
            total_size=size * len(members),
            recoverable_size=size * (len(members) - 1),
        ))
    return result


def preview_remediation(
    group: DuplicateGroup,
    rule: KeepRule,
    index: FileIndex,
) -> RemediationPreview:
    """Preview which entry to keep and which to delete in a group."""
    entries = list(group.entries)
    if not entries:
        raise ValueError("Empty duplicate group")

    def _sort_key(entry: FileEntry) -> tuple:
        path = entry.get_path(index)
        path_len = len(path) if rule.prefer_shortest_path else -len(path)
        date_val = 0
        if rule.prefer_newest and entry.date_modified:
            date_val = -int(entry.date_modified.timestamp())
        root_match = 0
        if rule.prefer_root and path.lower().startswith(rule.prefer_root.lower()):
            root_match = -1
        return (root_match, date_val, path_len, path.lower())

    sorted_entries = sorted(entries, key=_sort_key)
    keep = sorted_entries[0]
    delete_candidates = tuple(sorted_entries[1:])
    recoverable = sum(getattr(e, "size", 0) or 0 for e in delete_candidates)

    return RemediationPreview(
        keep=keep,
        delete_candidates=delete_candidates,
        recoverable_bytes=recoverable,
    )


def safe_recycle(
    paths: Sequence[str],
    recycle_fn: Callable[[str], bool] | None = None,
) -> RemediationResult:
    """Move files to Recycle Bin with structured results."""
    result = RemediationResult()
    recycler = recycle_fn or _default_recycle

    for path in paths:
        if not os.path.exists(path):
            result.skipped.append(path)
            continue
        try:
            if recycler(path):
                result.recycled.append(path)
            else:
                result.failed.append((path, "Recycle operation returned False"))
        except Exception as e:
            result.failed.append((path, str(e)))

    return result


def _default_recycle(path: str) -> bool:
    """Platform recycle using shell on Windows, fallback to os.remove."""
    try:
        import ctypes
        from ctypes import wintypes

        class SHFILEOPSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR),
                ("fFlags", wintypes.WORD),
                ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004

        op = SHFILEOPSTRUCT()
        op.wFunc = FO_DELETE
        op.pFrom = path + "\0"
        op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT
        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0
    except Exception:
        return False
