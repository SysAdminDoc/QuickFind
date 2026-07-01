"""Worker-isolated content extraction facade."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from core.content.adapters import (
    MAX_EXTRACT_CHARS,
    MAX_TEXT_BYTES,
    ExtractedContent,
    adapter_for_path,
    extract_text,
)
from core.worker_isolation import run_in_worker


logger = logging.getLogger("QuickFind.Content")

DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ExtractionOutcome:
    content: ExtractedContent | None
    adapter_name: str = ""
    error: str = ""
    timed_out: bool = False


def extract_text_sandboxed(
    path: str,
    max_chars: int = MAX_EXTRACT_CHARS,
    max_file_bytes: int = MAX_TEXT_BYTES,
    timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
) -> ExtractedContent | None:
    return extract_text_with_diagnostics(
        path,
        max_chars=max_chars,
        max_file_bytes=max_file_bytes,
        timeout_seconds=timeout_seconds,
    ).content


def extract_text_with_diagnostics(
    path: str,
    max_chars: int = MAX_EXTRACT_CHARS,
    max_file_bytes: int = MAX_TEXT_BYTES,
    timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
) -> ExtractionOutcome:
    adapter = adapter_for_path(path)
    if adapter is None:
        return ExtractionOutcome(content=None)

    try:
        size = os.path.getsize(path)
    except (OSError, PermissionError) as exc:
        return ExtractionOutcome(content=None, adapter_name=adapter.name, error=str(exc))

    if size > max_file_bytes:
        return ExtractionOutcome(
            content=None,
            adapter_name=adapter.name,
            error=f"Skipped {size} byte file above {max_file_bytes} byte cap",
        )

    outcome = run_in_worker(
        _extract_text_worker,
        path,
        max_chars,
        timeout_seconds=timeout_seconds,
    )
    if not outcome.ok:
        logger.debug("Sandboxed content extraction failed for %s: %s", path, outcome.error)
        return ExtractionOutcome(
            content=None,
            adapter_name=adapter.name,
            error=outcome.error,
            timed_out=outcome.timed_out,
        )
    return ExtractionOutcome(content=outcome.value, adapter_name=adapter.name)


def _extract_text_worker(path: str, max_chars: int) -> ExtractedContent | None:
    return extract_text(path, max_chars=max_chars)
