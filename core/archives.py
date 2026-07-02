"""Archive member enumeration for opt-in archive searches."""

import hashlib
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import datetime

from core.worker_isolation import run_in_worker
from core.index import FileEntry, FileIndex
from core.ntfs import FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_DIRECTORY

try:
    import py7zr
except ImportError:  # pragma: no cover - covered by packaging/install checks
    py7zr = None


logger = logging.getLogger('QuickFind.Archives')

SUPPORTED_ARCHIVE_EXTENSIONS = {'zip', '7z'}
DEFAULT_ARCHIVE_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ArchiveReadOutcome:
    members: list[dict]
    error: str = ""
    timed_out: bool = False


def is_supported_archive(entry: FileEntry) -> bool:
    return not entry.is_dir and entry.extension in SUPPORTED_ARCHIVE_EXTENSIONS


def iter_archive_entries(archive_entry: FileEntry, index: FileIndex):
    """Yield virtual FileEntry records for supported archive members."""
    if not is_supported_archive(archive_entry):
        return

    archive_path = archive_entry.get_path(index)
    fingerprint = _archive_fingerprint(archive_path)
    if fingerprint is None:
        return
    archive_size, archive_modified_ms = fingerprint

    try:
        members = _cached_or_read_members(
            archive_entry,
            archive_path,
            archive_size,
            archive_modified_ms,
        )
        for member in members:
            yield _make_virtual_entry(
                archive_entry=archive_entry,
                archive_path=archive_path,
                member_path=member["member_path"],
                is_dir=bool(member["is_dir"]),
                size=int(member["size"]),
                modified=_ms_to_dt(int(member.get("modified_ms") or 0)),
                created=_ms_to_dt(int(member.get("created_ms") or 0)),
            )
    except (OSError, PermissionError, zipfile.BadZipFile) as exc:
        logger.debug(f"Skipping unreadable archive {archive_path}: {exc}")
    except Exception as exc:
        logger.debug(f"Skipping archive {archive_path}: {exc}")


def _cached_or_read_members(archive_entry: FileEntry, archive_path: str,
                            archive_size: int, archive_modified_ms: int) -> list[dict]:
    from core.cache import get_archive_member_cache, upsert_archive_member_cache

    cached = get_archive_member_cache(archive_path, archive_size, archive_modified_ms)
    if cached is not None:
        return cached

    outcome = read_archive_members_sandboxed(archive_path, archive_entry.extension)
    if outcome.error:
        logger.debug("Skipping archive %s: %s", archive_path, outcome.error)
        return []
    members = outcome.members
    upsert_archive_member_cache(archive_path, archive_size, archive_modified_ms, members)
    return members


def read_archive_members_sandboxed(
    archive_path: str,
    extension: str,
    timeout_seconds: float = DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
) -> ArchiveReadOutcome:
    outcome = run_in_worker(
        _read_archive_members_direct,
        archive_path,
        extension,
        timeout_seconds=timeout_seconds,
    )
    if not outcome.ok:
        return ArchiveReadOutcome(
            members=[],
            error=outcome.error,
            timed_out=outcome.timed_out,
        )
    return ArchiveReadOutcome(members=outcome.value)


def _read_archive_members_direct(archive_path: str, extension: str) -> list[dict]:
    if extension == 'zip':
        return list(_iter_zip_members(archive_path))
    if extension == '7z':
        return list(_iter_7z_members(archive_path))
    return []


# Per-member content extraction cap (matches the default single-file content cap).
MEMBER_CONTENT_MAX_BYTES = 10 * 1024 * 1024


def extract_archive_member_sandboxed(
    archive_path: str,
    extension: str,
    member_path: str,
    member_ext: str,
    max_chars: int,
    max_bytes: int = MEMBER_CONTENT_MAX_BYTES,
    timeout_seconds: float = DEFAULT_ARCHIVE_TIMEOUT_SECONDS,
):
    """Extract text from a single archive member in an isolated worker.

    Returns (ExtractedContent | None, error). Malformed members, oversized
    members, and parser crashes fail closed (None) without touching the parent.
    """
    outcome = run_in_worker(
        _extract_member_text_direct,
        archive_path,
        extension,
        member_path,
        member_ext,
        max_chars,
        max_bytes,
        timeout_seconds=timeout_seconds,
    )
    if not outcome.ok:
        return None, outcome.error
    return outcome.value, ""


def _read_member_bytes(archive_path: str, extension: str, member_path: str,
                       max_bytes: int):
    """Return a member's bytes (up to max_bytes), or None if missing/oversized."""
    if extension == 'zip':
        with zipfile.ZipFile(archive_path, 'r') as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                if _normalize_member_path(info.filename) != member_path:
                    continue
                if info.file_size > max_bytes:
                    return None
                with archive.open(info) as fh:
                    return fh.read(max_bytes)
        return None
    if extension == '7z':
        if py7zr is None:
            return None
        with py7zr.SevenZipFile(archive_path, 'r') as archive:
            targets = [
                name for name in archive.getnames()
                if _normalize_member_path(name) == member_path
            ]
            if not targets:
                return None
            extracted = archive.read(targets)
            buffer = extracted.get(targets[0])
            if buffer is None:
                return None
            return buffer.read(max_bytes)
    return None


def _extract_member_text_direct(archive_path: str, extension: str, member_path: str,
                                member_ext: str, max_chars: int, max_bytes: int):
    import tempfile
    from core.content.adapters import extract_text

    data = _read_member_bytes(archive_path, extension, member_path, max_bytes)
    if not data:
        return None
    fd, tmp_path = tempfile.mkstemp(suffix=f".{member_ext}" if member_ext else "")
    try:
        with os.fdopen(fd, 'wb') as fh:
            fh.write(data)
        return extract_text(tmp_path, max_chars=max_chars)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _iter_zip_members(archive_path: str):
    with zipfile.ZipFile(archive_path, 'r') as archive:
        for info in archive.infolist():
            member_path = _normalize_member_path(info.filename)
            if not member_path:
                continue
            is_dir = info.is_dir()
            modified = _safe_zip_datetime(info.date_time)
            yield _member_metadata(
                member_path=member_path,
                is_dir=is_dir,
                size=0 if is_dir else info.file_size,
                modified=modified,
                created=modified,
            )


def _iter_7z_members(archive_path: str):
    if py7zr is None:
        logger.debug("py7zr is not installed; skipping 7z archive search")
        return

    with py7zr.SevenZipFile(archive_path, 'r') as archive:
        for info in archive.list():
            member_path = _normalize_member_path(info.filename)
            if not member_path:
                continue
            is_dir = bool(getattr(info, 'is_directory', False))
            created = _normalize_datetime(getattr(info, 'creationtime', None))
            yield _member_metadata(
                member_path=member_path,
                is_dir=is_dir,
                size=0 if is_dir else int(getattr(info, 'uncompressed', 0) or 0),
                modified=created,
                created=created,
            )


def _member_metadata(member_path: str, is_dir: bool, size: int,
                     modified: datetime | None,
                     created: datetime | None) -> dict:
    return {
        "member_path": member_path,
        "name": _member_name(member_path),
        "is_dir": is_dir,
        "size": size,
        "modified_ms": _dt_to_ms(modified),
        "created_ms": _dt_to_ms(created),
    }


def _make_virtual_entry(archive_entry: FileEntry, archive_path: str,
                        member_path: str, is_dir: bool, size: int,
                        modified: datetime | None,
                        created: datetime | None) -> FileEntry:
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_ARCHIVE
    entry = FileEntry(
        frn=_virtual_frn(archive_path, member_path),
        parent_frn=archive_entry.frn,
        name=_member_name(member_path),
        drive=archive_entry.drive,
        attributes=attrs,
        size=size,
        date_modified=modified,
        date_created=created,
    )
    entry._path = f"{archive_path}\\{member_path}"
    entry._stat_loaded = True
    return entry


def _normalize_member_path(member_path: str) -> str:
    # Drop drive/device prefixes, "." and ".." components so a crafted member
    # name (e.g. "..\..\Users\x\evil.exe") cannot make the virtual entry's path
    # lexically resolve to a real file outside the archive when opened.
    normalized = member_path.replace('/', '\\').strip('\\')
    parts = []
    for part in normalized.split('\\'):
        part = part.strip()
        if not part or part in ('.', '..') or ':' in part:
            continue
        parts.append(part)
    return '\\'.join(parts)


def _member_name(member_path: str) -> str:
    return member_path.rsplit('\\', 1)[-1]


def _safe_zip_datetime(parts: tuple[int, int, int, int, int, int]) -> datetime | None:
    try:
        return datetime(*parts)
    except (TypeError, ValueError):
        return None


def _normalize_datetime(value) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def _archive_fingerprint(archive_path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(archive_path)
    except (OSError, PermissionError):
        return None
    return st.st_size, int(st.st_mtime * 1000)


def _dt_to_ms(value: datetime | None) -> int:
    if value is None:
        return 0
    try:
        return int(value.timestamp() * 1000)
    except (OSError, OverflowError, ValueError):
        return 0


def _ms_to_dt(value: int) -> datetime | None:
    if value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0)
    except (OSError, OverflowError, ValueError):
        return None


def _virtual_frn(archive_path: str, member_path: str) -> int:
    key = f"{archive_path}\0{member_path}".encode('utf-8', errors='ignore')
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return -int.from_bytes(digest, 'big')
