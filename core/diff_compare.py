"""Bounded text diff helpers for comparing two selected results."""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass


MAX_DIFF_BYTES = 1024 * 1024


@dataclass(frozen=True)
class DiffResult:
    left_path: str
    right_path: str
    text: str
    error: str = ""


def build_unified_diff(
    left_path: str,
    right_path: str,
    max_bytes: int = MAX_DIFF_BYTES,
) -> DiffResult:
    """Build a unified diff for two text files, or return a user-readable error."""
    left_lines, left_error = _read_text_lines(left_path, max_bytes)
    if left_error:
        return DiffResult(left_path, right_path, "", left_error)

    right_lines, right_error = _read_text_lines(right_path, max_bytes)
    if right_error:
        return DiffResult(left_path, right_path, "", right_error)

    diff = difflib.unified_diff(
        left_lines,
        right_lines,
        fromfile=os.path.basename(left_path) or left_path,
        tofile=os.path.basename(right_path) or right_path,
        lineterm="",
    )
    text = "\n".join(diff)
    if not text:
        text = "Files are identical."
    return DiffResult(left_path, right_path, text)


def _read_text_lines(path: str, max_bytes: int) -> tuple[list[str], str]:
    if not os.path.isfile(path):
        return [], f"Cannot compare non-file path: {path}"

    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as exc:
        return [], f"Failed to read {path}: {exc}"

    sample = data[: min(len(data), 4096)]
    if b"\x00" in sample:
        return [], f"Binary file cannot be compared inline: {path}"

    truncated = size > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    lines = text.splitlines()
    if truncated:
        lines.append(f"... truncated at {max_bytes:,} bytes ...")
    return lines, ""
