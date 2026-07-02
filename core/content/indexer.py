"""Background content indexing job with quotas and diagnostics."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from core.cache import (
    get_content_cache,
    get_content_cache_size_bytes,
    upsert_content_cache,
)
from core.content.adapters import (
    MAX_EXTRACT_CHARS,
    SUPPORTED_CONTENT_EXTENSIONS,
    adapter_for_path,
)
from core.content.sandbox import (
    DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    ExtractionOutcome,
    extract_text_with_diagnostics,
)
from core.archives import (
    extract_archive_member_sandboxed,
    is_supported_archive,
    read_archive_members_sandboxed,
)
from core.index import FileEntry


DEFAULT_CONTENT_CACHE_BYTES = 512 * 1024 * 1024
DEFAULT_CONTENT_FILE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class ContentIndexSettings:
    roots: tuple[str, ...] = ()
    extensions: frozenset[str] | None = None
    max_cache_bytes: int = DEFAULT_CONTENT_CACHE_BYTES
    max_file_bytes: int = DEFAULT_CONTENT_FILE_BYTES
    max_chars: int = MAX_EXTRACT_CHARS
    timeout_seconds: float = DEFAULT_EXTRACTION_TIMEOUT_SECONDS

    @property
    def allowed_extensions(self) -> frozenset[str]:
        if self.extensions:
            return frozenset(ext.lower().lstrip(".") for ext in self.extensions)
        return frozenset(SUPPORTED_CONTENT_EXTENSIONS)

    @property
    def normalized_roots(self) -> tuple[str, ...]:
        roots = []
        for root in self.roots:
            if not root:
                continue
            roots.append(os.path.normcase(os.path.abspath(os.path.expanduser(root))))
        return tuple(roots)


@dataclass
class ContentIndexStats:
    scanned: int = 0
    indexed: int = 0
    cached: int = 0
    skipped: int = 0
    failed: int = 0
    quota_skipped: int = 0
    bytes_cached: int = 0
    cancelled: bool = False
    adapter_failures: dict[str, int] = field(default_factory=dict)
    last_error: str = ""

    def record_failure(self, adapter_name: str, error: str = ""):
        self.failed += 1
        self.adapter_failures[adapter_name] = self.adapter_failures.get(adapter_name, 0) + 1
        if error:
            self.last_error = error


class ContentIndexJob:
    def __init__(
        self,
        settings: ContentIndexSettings,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[ContentIndexStats], None] | None = None,
    ):
        self._settings = settings
        self._cancel_check = cancel_check or (lambda: False)
        self._progress_callback = progress_callback

    def run(
        self,
        entries: Iterable[FileEntry],
        resolve_path: Callable[[FileEntry], str],
    ) -> ContentIndexStats:
        stats = ContentIndexStats(bytes_cached=get_content_cache_size_bytes())
        roots = self._settings.normalized_roots
        allowed_extensions = self._settings.allowed_extensions

        for entry in entries:
            if self._cancel_check():
                stats.cancelled = True
                break

            stats.scanned += 1
            if entry.is_dir:
                stats.skipped += 1
                continue

            try:
                path = resolve_path(entry)
            except Exception as exc:
                stats.record_failure("path", str(exc))
                continue

            if roots and not _path_within_roots(path, roots):
                stats.skipped += 1
                continue

            if is_supported_archive(entry):
                # Descend into archive members: extract and cache each member's
                # text under a virtual "archive\member" path.
                self._index_archive_members(entry, path, stats)
                continue

            adapter = adapter_for_path(path)
            if adapter is None or _extension(path) not in allowed_extensions:
                stats.skipped += 1
                continue

            try:
                st = os.stat(path)
            except (OSError, PermissionError) as exc:
                stats.record_failure(adapter.name, str(exc))
                continue

            if st.st_size > self._settings.max_file_bytes:
                stats.skipped += 1
                continue

            modified_ms = int(st.st_mtime * 1000)
            if get_content_cache(path, st.st_size, modified_ms) is not None:
                stats.cached += 1
                continue

            if stats.bytes_cached >= self._settings.max_cache_bytes:
                stats.quota_skipped += 1
                continue

            outcome = extract_text_with_diagnostics(
                path,
                max_chars=self._settings.max_chars,
                max_file_bytes=self._settings.max_file_bytes,
                timeout_seconds=self._settings.timeout_seconds,
            )
            if outcome.content is None:
                stats.record_failure(_failure_key(adapter.name, outcome), outcome.error)
                continue
            extracted = outcome.content

            text_bytes = len(extracted.text.encode("utf-8", errors="ignore"))
            if stats.bytes_cached + text_bytes > self._settings.max_cache_bytes:
                stats.quota_skipped += 1
                continue

            upsert_content_cache(
                path=path,
                size=st.st_size,
                modified_ms=modified_ms,
                extractor=extracted.extractor,
                text=extracted.text,
            )
            stats.indexed += 1
            stats.bytes_cached += text_bytes

            if self._progress_callback and stats.scanned % 25 == 0:
                self._progress_callback(stats)

        if self._progress_callback:
            self._progress_callback(stats)
        return stats

    def _index_archive_members(self, archive_entry: FileEntry, archive_path: str,
                               stats: ContentIndexStats) -> None:
        """Extract and cache text for content-supported members of one archive.

        Member content is keyed by the archive's own size+mtime so it invalidates
        as a unit when the archive changes; malformed members fail closed.
        """
        try:
            st = os.stat(archive_path)
        except (OSError, PermissionError) as exc:
            stats.record_failure("archive", str(exc))
            return
        archive_size = st.st_size
        archive_mtime_ms = int(st.st_mtime * 1000)
        allowed = self._settings.allowed_extensions

        outcome = read_archive_members_sandboxed(
            archive_path, archive_entry.extension,
            timeout_seconds=self._settings.timeout_seconds,
        )
        for member in outcome.members:
            if self._cancel_check():
                stats.cancelled = True
                break
            if member.get("is_dir"):
                continue
            member_path = member["member_path"]
            member_ext = _extension(member_path)
            if member_ext not in allowed:
                continue
            if int(member.get("size") or 0) > self._settings.max_file_bytes:
                stats.skipped += 1
                continue

            virtual_path = f"{archive_path}\\{member_path}"
            if get_content_cache(virtual_path, archive_size, archive_mtime_ms) is not None:
                stats.cached += 1
                continue
            if stats.bytes_cached >= self._settings.max_cache_bytes:
                stats.quota_skipped += 1
                continue

            content, error = extract_archive_member_sandboxed(
                archive_path, archive_entry.extension, member_path, member_ext,
                max_chars=self._settings.max_chars,
                max_bytes=self._settings.max_file_bytes,
                timeout_seconds=self._settings.timeout_seconds,
            )
            if content is None:
                if error:
                    stats.record_failure(f"archive:{member_ext}", error)
                continue

            text_bytes = len(content.text.encode("utf-8", errors="ignore"))
            if stats.bytes_cached + text_bytes > self._settings.max_cache_bytes:
                stats.quota_skipped += 1
                continue

            upsert_content_cache(
                path=virtual_path,
                size=archive_size,
                modified_ms=archive_mtime_ms,
                extractor=content.extractor,
                text=content.text,
            )
            stats.indexed += 1
            stats.bytes_cached += text_bytes


def _glob_to_regex(pattern: str) -> "re.Pattern[str]":
    """Translate an Everything-style content-scope glob to a regex.

    ``**`` matches any characters including path separators (recursive), ``*``
    matches within a single path segment, and ``?`` matches one non-separator
    character. Patterns are matched against normcase'd absolute paths.
    """
    sep = re.escape(os.sep)
    out = ["^"]
    i = 0
    while i < len(pattern):
        if pattern[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append(f"[^{sep}]*")
            i += 1
        elif pattern[i] == "?":
            out.append(f"[^{sep}]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def _path_within_roots(path: str, roots: tuple[str, ...]) -> bool:
    normalized = os.path.normcase(os.path.abspath(path))
    for root in roots:
        if "*" in root or "?" in root:
            # Glob scope (e.g. c:\docs\**.pdf recursive, c:\docs\*.docx one level).
            if _glob_to_regex(root).match(normalized):
                return True
            continue
        try:
            common = os.path.commonpath([normalized, root])
        except ValueError:
            continue
        if common == root:
            return True
    return False


def _extension(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    if suffix:
        return suffix
    return Path(path).name.lower()


def _failure_key(adapter_name: str, outcome: ExtractionOutcome) -> str:
    if outcome.timed_out:
        return f"{adapter_name}:timeout"
    return outcome.adapter_name or adapter_name
