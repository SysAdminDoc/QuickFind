"""Archive member enumeration for opt-in archive searches."""

import hashlib
import logging
import zipfile
from datetime import datetime

from core.index import FileEntry, FileIndex
from core.ntfs import FILE_ATTRIBUTE_ARCHIVE, FILE_ATTRIBUTE_DIRECTORY

try:
    import py7zr
except ImportError:  # pragma: no cover - covered by packaging/install checks
    py7zr = None


logger = logging.getLogger('QuickFind.Archives')

SUPPORTED_ARCHIVE_EXTENSIONS = {'zip', '7z'}


def is_supported_archive(entry: FileEntry) -> bool:
    return not entry.is_dir and entry.extension in SUPPORTED_ARCHIVE_EXTENSIONS


def iter_archive_entries(archive_entry: FileEntry, index: FileIndex):
    """Yield virtual FileEntry records for supported archive members."""
    if not is_supported_archive(archive_entry):
        return

    archive_path = archive_entry.get_path(index)
    try:
        if archive_entry.extension == 'zip':
            yield from _iter_zip_entries(archive_entry, archive_path)
        elif archive_entry.extension == '7z':
            yield from _iter_7z_entries(archive_entry, archive_path)
    except (OSError, PermissionError, zipfile.BadZipFile) as exc:
        logger.debug(f"Skipping unreadable archive {archive_path}: {exc}")
    except Exception as exc:
        logger.debug(f"Skipping archive {archive_path}: {exc}")


def _iter_zip_entries(archive_entry: FileEntry, archive_path: str):
    with zipfile.ZipFile(archive_path, 'r') as archive:
        for info in archive.infolist():
            member_path = _normalize_member_path(info.filename)
            if not member_path:
                continue
            is_dir = info.is_dir()
            modified = _safe_zip_datetime(info.date_time)
            yield _make_virtual_entry(
                archive_entry=archive_entry,
                archive_path=archive_path,
                member_path=member_path,
                is_dir=is_dir,
                size=0 if is_dir else info.file_size,
                modified=modified,
                created=modified,
            )


def _iter_7z_entries(archive_entry: FileEntry, archive_path: str):
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
            yield _make_virtual_entry(
                archive_entry=archive_entry,
                archive_path=archive_path,
                member_path=member_path,
                is_dir=is_dir,
                size=0 if is_dir else int(getattr(info, 'uncompressed', 0) or 0),
                modified=created,
                created=created,
            )


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
    return member_path.replace('/', '\\').strip('\\')


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


def _virtual_frn(archive_path: str, member_path: str) -> int:
    key = f"{archive_path}\0{member_path}".encode('utf-8', errors='ignore')
    digest = hashlib.blake2b(key, digest_size=8).digest()
    return -int.from_bytes(digest, 'big')
