"""
Index cache for instant startup.
Serializes the in-memory file index to disk and restores it on next launch.
Stores per-drive USN journal positions for differential updates.
"""

import os
import struct
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.index import FileEntry, FileIndex, NTFS_ROOT_FRN
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY

logger = logging.getLogger('QuickFind.Cache')

CONFIG_DIR = Path.home() / '.quickfind'
CACHE_FILE = CONFIG_DIR / 'index_cache.bin'

# Binary format:
# Header: MAGIC(4) VERSION(4) DRIVE_COUNT(4) TIMESTAMP(8)
# Per drive: LETTER(2) ENTRY_COUNT(4) JOURNAL_ID(8) NEXT_USN(8)
#   Per entry: FRN(8) PARENT_FRN(8) ATTRS(4) SIZE(8) MTIME(8) CTIME(8) NAME_LEN(2) NAME(var)
# Timestamps stored as int64 unix epoch * 1000 (ms precision)

MAGIC = b'QFC\x01'
FORMAT_VERSION = 2


def _dt_to_ms(dt: Optional[datetime]) -> int:
    if dt is None:
        return 0
    try:
        return int(dt.timestamp() * 1000)
    except (OSError, OverflowError, ValueError):
        return 0


def _ms_to_dt(ms: int) -> Optional[datetime]:
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0)
    except (OSError, OverflowError, ValueError):
        return None


def save_cache(index: FileIndex, usn_positions: dict[str, tuple[int, int]]):
    """
    Save the file index to a binary cache file.

    Args:
        index: The FileIndex to serialize
        usn_positions: dict of drive_letter -> (journal_id, next_usn)
    """
    CONFIG_DIR.mkdir(exist_ok=True)
    start = time.perf_counter()

    try:
        tmp_path = CACHE_FILE.with_suffix('.tmp')
        with open(tmp_path, 'wb') as f:
            drives = list(index._entries.keys())
            now_ms = _dt_to_ms(datetime.now())

            # Header
            f.write(MAGIC)
            f.write(struct.pack('<III', FORMAT_VERSION, len(drives), 0))
            f.write(struct.pack('<q', now_ms))

            for drive in drives:
                drive_entries = index._entries[drive]
                journal_id, next_usn = usn_positions.get(drive, (0, 0))

                # Drive header
                f.write(drive.encode('utf-8').ljust(2, b'\x00'))
                # Exclude root entry from count
                real_entries = {frn: e for frn, e in drive_entries.items() if frn != NTFS_ROOT_FRN}
                f.write(struct.pack('<I', len(real_entries)))
                f.write(struct.pack('<QQ', journal_id, next_usn))

                for frn, entry in real_entries.items():
                    name_bytes = entry.name.encode('utf-8')
                    mtime_ms = _dt_to_ms(entry.date_modified) if entry._stat_loaded else 0
                    ctime_ms = _dt_to_ms(entry.date_created) if entry._stat_loaded else 0
                    size = entry.size if entry._stat_loaded else 0

                    f.write(struct.pack('<QQIqqqH',
                        entry.frn,
                        entry.parent_frn,
                        entry.attributes,
                        size,
                        mtime_ms,
                        ctime_ms,
                        len(name_bytes),
                    ))
                    f.write(name_bytes)

        # Atomic replace
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
        tmp_path.rename(CACHE_FILE)

        elapsed = (time.perf_counter() - start) * 1000
        total = sum(len(v) for v in index._entries.values())
        logger.info(f"Cache saved: {total:,} entries in {elapsed:.0f}ms")

    except Exception as e:
        logger.error(f"Failed to save cache: {e}")


def load_cache(index: FileIndex) -> Optional[dict[str, tuple[int, int]]]:
    """
    Load the file index from cache.

    Returns:
        dict of drive_letter -> (journal_id, next_usn) if successful, None if no cache.
    """
    if not CACHE_FILE.exists():
        return None

    start = time.perf_counter()
    usn_positions = {}

    try:
        with open(CACHE_FILE, 'rb') as f:
            # Header
            magic = f.read(4)
            if magic != MAGIC:
                logger.warning("Cache file has invalid magic")
                return None

            version, drive_count, _ = struct.unpack('<III', f.read(12))
            if version != FORMAT_VERSION:
                logger.warning(f"Cache version mismatch: {version} != {FORMAT_VERSION}")
                return None

            cache_ts_ms = struct.unpack('<q', f.read(8))[0]
            cache_time = _ms_to_dt(cache_ts_ms)
            logger.info(f"Loading cache from {cache_time}")

            total_loaded = 0

            for _ in range(drive_count):
                drive_bytes = f.read(2)
                drive = drive_bytes.decode('utf-8').strip('\x00')

                entry_count, journal_id, next_usn = struct.unpack('<IQQ', f.read(20))
                usn_positions[drive] = (journal_id, next_usn)

                drive_entries = {}
                # Add root entry
                drive_entries[NTFS_ROOT_FRN] = FileEntry(
                    frn=NTFS_ROOT_FRN,
                    parent_frn=0,
                    name="",
                    drive=drive,
                    attributes=FILE_ATTRIBUTE_DIRECTORY,
                )

                for _ in range(entry_count):
                    frn, parent_frn, attrs, size, mtime_ms, ctime_ms, name_len = \
                        struct.unpack('<QQIqqqH', f.read(46))
                    name = f.read(name_len).decode('utf-8')

                    entry = FileEntry(
                        frn=frn,
                        parent_frn=parent_frn,
                        name=name,
                        drive=drive,
                        attributes=attrs,
                    )

                    # Restore cached stat data if available
                    if size or mtime_ms or ctime_ms:
                        entry.size = size
                        entry.date_modified = _ms_to_dt(mtime_ms)
                        entry.date_created = _ms_to_dt(ctime_ms)
                        entry._stat_loaded = True

                    drive_entries[frn] = entry

                index._entries[drive] = drive_entries
                total_loaded += entry_count

            index._rebuild_flat_list()

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"Cache loaded: {total_loaded:,} entries in {elapsed:.0f}ms")
        return usn_positions

    except Exception as e:
        logger.error(f"Failed to load cache: {e}")
        return None


def cache_exists() -> bool:
    return CACHE_FILE.exists()


def cache_age_seconds() -> float:
    if not CACHE_FILE.exists():
        return float('inf')
    return time.time() - CACHE_FILE.stat().st_mtime
