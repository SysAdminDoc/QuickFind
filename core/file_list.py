"""
EFU (Everything File List) support for indexing non-NTFS and network drives.

EFU format is CSV with headers: Filename,Size,Date Modified,Date Created,Attributes
Paths are absolute (e.g., \\\\server\\share\\folder\\file.txt)
"""

import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.index import FileEntry
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY

logger = logging.getLogger('QuickFind.FileList')

_FILETIME_EPOCH_DIFF = 116444736000000000  # 100ns intervals between 1601 and 1970


def _parse_efu_date(date_str: str) -> Optional[datetime]:
    """Parse EFU date format (Windows FILETIME as decimal string)."""
    if not date_str:
        return None
    try:
        ft = int(date_str)
        if ft <= 0:
            return None
        unix_us = (ft - _FILETIME_EPOCH_DIFF) // 10
        return datetime.fromtimestamp(unix_us / 1_000_000)
    except (ValueError, OverflowError, OSError):
        return None


def load_efu(filepath: str) -> list[FileEntry]:
    """
    Load an EFU file and return FileEntry objects.

    EFU files contain: Filename, Size, Date Modified, Date Created, Attributes
    """
    entries = []
    frn_counter = 0x1000000000  # Start FRNs high to avoid NTFS collisions

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return entries

            # Normalize headers
            header_lower = [h.strip().lower() for h in header]
            idx_name = 0
            idx_size = header_lower.index('size') if 'size' in header_lower else -1
            idx_dm = header_lower.index('date modified') if 'date modified' in header_lower else -1
            idx_dc = header_lower.index('date created') if 'date created' in header_lower else -1
            idx_attr = header_lower.index('attributes') if 'attributes' in header_lower else -1

            # Build parent mapping
            path_to_frn: dict[str, int] = {}

            for row in reader:
                if not row:
                    continue

                full_path = row[idx_name].strip()
                if not full_path:
                    continue

                frn_counter += 1
                frn = frn_counter

                # Parse filename from path
                name = os.path.basename(full_path)
                parent_path = os.path.dirname(full_path)

                # Get or create parent FRN
                parent_frn = path_to_frn.get(parent_path, 0)

                # Parse other fields
                size = int(row[idx_size]) if idx_size >= 0 and len(row) > idx_size and row[idx_size] else 0
                date_mod = _parse_efu_date(row[idx_dm]) if idx_dm >= 0 and len(row) > idx_dm else None
                date_create = _parse_efu_date(row[idx_dc]) if idx_dc >= 0 and len(row) > idx_dc else None
                attributes = int(row[idx_attr]) if idx_attr >= 0 and len(row) > idx_attr and row[idx_attr] else 0

                # Determine drive letter (or use 'N' for network)
                if len(full_path) >= 2 and full_path[1] == ':':
                    drive = full_path[0].upper()
                else:
                    drive = 'N'  # Network path

                entry = FileEntry(
                    frn=frn,
                    parent_frn=parent_frn,
                    name=name or full_path,
                    drive=drive,
                    attributes=attributes,
                    size=size,
                    date_modified=date_mod,
                    date_created=date_create,
                )
                entry._path = full_path
                if size or date_mod or date_create:
                    entry._stat_loaded = True
                entries.append(entry)

                # Register this path for parent lookups
                path_to_frn[full_path] = frn

    except Exception as e:
        logger.error(f"Failed to load EFU file {filepath}: {e}")

    logger.info(f"Loaded {len(entries)} entries from EFU: {filepath}")
    return entries


def save_efu(entries: list[FileEntry], filepath: str, index=None):
    """
    Save FileEntry objects to an EFU file.
    """
    try:
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Filename', 'Size', 'Date Modified', 'Date Created', 'Attributes'])

            for entry in entries:
                if index:
                    path = entry.get_path(index)
                else:
                    path = entry._path or entry.name

                # Convert dates to FILETIME
                dm = ''
                dc = ''
                if entry.date_modified:
                    dm = str(int(entry.date_modified.timestamp() * 10_000_000) + _FILETIME_EPOCH_DIFF)
                if entry.date_created:
                    dc = str(int(entry.date_created.timestamp() * 10_000_000) + _FILETIME_EPOCH_DIFF)

                writer.writerow([
                    path,
                    entry.size,
                    dm,
                    dc,
                    entry.attributes
                ])

        logger.info(f"Saved {len(entries)} entries to EFU: {filepath}")
    except Exception as e:
        logger.error(f"Failed to save EFU file {filepath}: {e}")


def scan_directory_to_efu(directory: str, output_path: str):
    """Scan a non-NTFS directory and create an EFU file."""
    entries = []
    frn_counter = 0x2000000000

    try:
        for root, dirs, files in os.walk(directory):
            for name in dirs + files:
                full_path = os.path.join(root, name)
                frn_counter += 1

                try:
                    stat = os.stat(full_path)
                    is_dir = os.path.isdir(full_path)
                    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else 0

                    entry = FileEntry(
                        frn=frn_counter,
                        parent_frn=0,
                        name=name,
                        drive=full_path[0].upper() if len(full_path) >= 2 and full_path[1] == ':' else 'N',
                        attributes=attrs,
                        size=stat.st_size if not is_dir else 0,
                        date_modified=datetime.fromtimestamp(stat.st_mtime),
                        date_created=datetime.fromtimestamp(stat.st_ctime),
                    )
                    entry._path = full_path
                    entries.append(entry)
                except (OSError, PermissionError):
                    continue

    except (OSError, PermissionError) as e:
        logger.error(f"Failed to scan directory {directory}: {e}")

    save_efu(entries, output_path)
    return entries
