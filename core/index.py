"""
In-memory file index with path resolution and real-time USN journal monitoring.

Maintains a dict of FRN -> FileEntry for each indexed volume, resolves full paths
via parent-child FRN relationships, and runs a background thread to poll the
USN journal for filesystem changes.
"""

import os
import time
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from core.ntfs import (
    NTFSVolume, FileRecord, USNRecord, get_ntfs_drives,
    FILE_ATTRIBUTE_DIRECTORY, USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_CLOSE, USN_REASON_BASIC_INFO_CHANGE,
    USN_REASON_DATA_OVERWRITE, USN_REASON_DATA_EXTEND, USN_REASON_DATA_TRUNCATION
)

logger = logging.getLogger('QuickFind.Index')

# Root directory FRN for NTFS is always 5
NTFS_ROOT_FRN = 5


@dataclass
class FileEntry:
    """A file or folder in the index with resolved path information."""
    frn: int
    parent_frn: int
    name: str
    drive: str  # Drive letter (e.g., 'C')
    attributes: int = 0
    size: int = 0
    date_modified: Optional[datetime] = None
    date_created: Optional[datetime] = None
    _path: Optional[str] = field(default=None, repr=False)
    _stat_loaded: bool = field(default=False, repr=False)

    @property
    def is_dir(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)

    @property
    def extension(self) -> str:
        if self.is_dir:
            return ""
        dot = self.name.rfind('.')
        if dot > 0:
            return self.name[dot + 1:].lower()
        return ""

    def get_path(self, index: 'FileIndex') -> str:
        """Resolve and cache the full path."""
        if self._path is not None:
            return self._path
        self._path = index.resolve_path(self.drive, self.frn)
        return self._path

    def invalidate_path(self):
        """Clear cached path (e.g., after rename/move)."""
        self._path = None

    def ensure_stat(self, index: 'FileIndex'):
        """Lazy-load size and dates from os.stat() if not already loaded."""
        if self._stat_loaded:
            return
        self._stat_loaded = True
        try:
            path = self.get_path(index)
            st = os.stat(path)
            self.size = st.st_size
            self.date_modified = datetime.fromtimestamp(st.st_mtime)
            self.date_created = datetime.fromtimestamp(st.st_ctime)
        except (OSError, PermissionError, ValueError):
            pass


class IndexStats:
    """Statistics for the current index state."""
    def __init__(self):
        self.total_files = 0
        self.total_folders = 0
        self.total_size = 0
        self.volumes_indexed: list[str] = []
        self.index_time_ms = 0
        self.last_update: Optional[datetime] = None


class FileIndex(QObject):
    """
    Central in-memory file index.
    Indexes all NTFS volumes by reading MFT, resolves paths, and monitors
    USN journals for real-time updates.
    """
    # Signals
    indexing_started = pyqtSignal()
    indexing_progress = pyqtSignal(str, int)  # (drive_letter, record_count)
    indexing_complete = pyqtSignal(object)  # IndexStats
    index_updated = pyqtSignal(int)  # number of changes applied
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Per-drive index: drive_letter -> {frn -> FileEntry}
        self._entries: dict[str, dict[int, FileEntry]] = {}
        # Per-drive volume handles for journal monitoring
        self._volumes: dict[str, NTFSVolume] = {}
        # All entries flat list for search (rebuilt after indexing)
        self._all_entries: list[FileEntry] = []
        self._lock = threading.RLock()
        self._stats = IndexStats()
        self._monitor_thread: Optional[USNMonitorThread] = None
        self._cancel_flag = False

    @property
    def stats(self) -> IndexStats:
        return self._stats

    @property
    def all_entries(self) -> list[FileEntry]:
        return self._all_entries

    def get_entry(self, drive: str, frn: int) -> Optional[FileEntry]:
        """Get a specific entry by drive and FRN."""
        with self._lock:
            drive_entries = self._entries.get(drive.upper())
            if drive_entries:
                return drive_entries.get(frn)
        return None

    def resolve_path(self, drive: str, frn: int) -> str:
        """Resolve the full path for a file by walking parent FRNs."""
        parts = []
        drive = drive.upper()
        visited = set()

        with self._lock:
            drive_entries = self._entries.get(drive, {})
            current_frn = frn

            while current_frn and current_frn not in visited:
                visited.add(current_frn)
                if current_frn == NTFS_ROOT_FRN:
                    break
                entry = drive_entries.get(current_frn)
                if not entry:
                    break
                parts.append(entry.name)
                current_frn = entry.parent_frn

        parts.reverse()
        return f"{drive}:\\" + "\\".join(parts) if parts else f"{drive}:\\"

    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        """Resolve just the parent directory path."""
        if parent_frn == NTFS_ROOT_FRN:
            return f"{drive.upper()}:\\"
        return self.resolve_path(drive, parent_frn)

    def cancel_indexing(self):
        """Signal to cancel any in-progress indexing."""
        self._cancel_flag = True

    def _is_cancelled(self) -> bool:
        return self._cancel_flag

    def load_from_cache(self, drives: Optional[list[str]] = None) -> bool:
        """
        Try to load the index from disk cache and catch up via USN journal.
        Returns True if cache was loaded successfully.
        """
        from core.cache import load_cache, cache_exists
        if not cache_exists():
            return False

        self._cancel_flag = False
        self.indexing_started.emit()

        start_time = time.perf_counter()
        usn_positions = load_cache(self)

        if usn_positions is None:
            return False

        # Open volumes and catch up via USN journal
        if drives is None:
            drives = get_ntfs_drives()

        total_changes = 0
        for drive_letter in drives:
            if self._cancel_flag:
                break
            if drive_letter not in self._entries:
                continue

            vol = NTFSVolume(drive_letter)
            if not vol.open():
                continue

            vol_info = vol.get_volume_info()
            if vol_info and vol_info.filesystem.upper() != 'NTFS':
                vol.close()
                continue

            with self._lock:
                self._volumes[drive_letter] = vol

            # Restore USN position and catch up
            journal_id, next_usn = usn_positions.get(drive_letter, (0, 0))
            if vol.query_usn_journal():
                # Check if journal is still the same (not recycled)
                if vol.journal_id == journal_id and next_usn > 0:
                    logger.info(f"Catching up USN on {drive_letter}: from USN {next_usn}")
                    records = vol.read_usn_journal(start_usn=next_usn)
                    changes = []
                    for rec in records:
                        if rec.is_close:
                            changes.append((drive_letter, rec))
                    if changes:
                        self._apply_usn_changes(changes)
                        total_changes += len(changes)
                    self.indexing_progress.emit(drive_letter, len(self._entries.get(drive_letter, {})))
                else:
                    # Journal was recycled — need full re-index of this drive
                    logger.warning(f"USN journal recycled on {drive_letter}, full re-index needed")
                    self._reindex_drive(vol, drive_letter)

        # Count stats
        total_files = 0
        total_folders = 0
        with self._lock:
            for drive_entries in self._entries.values():
                for frn, entry in drive_entries.items():
                    if frn == NTFS_ROOT_FRN:
                        continue
                    if entry.is_dir:
                        total_folders += 1
                    else:
                        total_files += 1

        elapsed = (time.perf_counter() - start_time) * 1000
        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = drives
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()

        logger.info(
            f"Cache loaded + USN catchup: {total_files} files, {total_folders} folders "
            f"in {elapsed:.0f}ms ({total_changes} USN changes applied)"
        )
        self.indexing_complete.emit(self._stats)
        return True

    def _reindex_drive(self, vol: NTFSVolume, drive_letter: str):
        """Full re-index of a single drive."""
        def progress_cb(record, count):
            self.indexing_progress.emit(drive_letter, count)

        records = vol.enumerate_mft_direct(
            callback=progress_cb,
            cancel_check=self._is_cancelled
        )

        drive_entries: dict[int, FileEntry] = {}
        drive_entries[NTFS_ROOT_FRN] = FileEntry(
            frn=NTFS_ROOT_FRN, parent_frn=0, name="",
            drive=drive_letter, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )

        for rec in records:
            entry = FileEntry(
                frn=rec.frn, parent_frn=rec.parent_frn, name=rec.name,
                drive=drive_letter, attributes=rec.attributes,
                size=rec.size,
                date_modified=rec.timestamp,
                date_created=rec.date_created,
            )
            entry._stat_loaded = rec.mft_metadata  # Only skip os.stat if data came from direct MFT reading
            drive_entries[rec.frn] = entry

        with self._lock:
            self._entries[drive_letter] = drive_entries

        self._rebuild_flat_list()

    def index_all_drives(self, drives: Optional[list[str]] = None):
        """
        Index all NTFS drives (or specified drives).
        This should be called from a worker thread.
        """
        self._cancel_flag = False
        self.indexing_started.emit()

        if drives is None:
            drives = get_ntfs_drives()

        start_time = time.perf_counter()
        total_files = 0
        total_folders = 0

        for drive_letter in drives:
            if self._cancel_flag:
                break

            logger.info(f"Indexing drive {drive_letter}:...")
            vol = NTFSVolume(drive_letter)
            if not vol.open():
                self.error_occurred.emit(f"Failed to open volume {drive_letter}:")
                continue

            vol_info = vol.get_volume_info()
            if vol_info and vol_info.filesystem.upper() != 'NTFS':
                logger.info(f"Skipping non-NTFS volume {drive_letter}:")
                vol.close()
                continue

            def progress_cb(record, count):
                self.indexing_progress.emit(drive_letter, count)

            records = vol.enumerate_mft_direct(
                callback=progress_cb,
                cancel_check=self._is_cancelled
            )

            # Build drive index
            drive_entries: dict[int, FileEntry] = {}

            # Add root entry
            drive_entries[NTFS_ROOT_FRN] = FileEntry(
                frn=NTFS_ROOT_FRN,
                parent_frn=0,
                name="",
                drive=drive_letter,
                attributes=FILE_ATTRIBUTE_DIRECTORY,
            )

            for rec in records:
                entry = FileEntry(
                    frn=rec.frn,
                    parent_frn=rec.parent_frn,
                    name=rec.name,
                    drive=drive_letter,
                    attributes=rec.attributes,
                    size=rec.size,
                    date_modified=rec.timestamp,
                    date_created=rec.date_created,
                )
                entry._stat_loaded = rec.mft_metadata  # Only skip os.stat if data came from direct MFT reading
                drive_entries[rec.frn] = entry

                if rec.is_dir:
                    total_folders += 1
                else:
                    total_files += 1

            with self._lock:
                self._entries[drive_letter] = drive_entries
                self._volumes[drive_letter] = vol

            # Setup USN journal for monitoring
            vol.query_usn_journal()

            self.indexing_progress.emit(drive_letter, len(records))

        # Rebuild flat list
        self._rebuild_flat_list()

        elapsed = (time.perf_counter() - start_time) * 1000

        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = drives
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()

        logger.info(
            f"Indexing complete: {total_files} files, {total_folders} folders "
            f"in {elapsed:.0f}ms across {len(drives)} drives"
        )
        self.indexing_complete.emit(self._stats)

    def _rebuild_flat_list(self):
        """Rebuild the flat list of all entries for searching.
        Builds into a new list first to avoid a window where all_entries is empty.
        """
        new_list = []
        with self._lock:
            for drive_entries in self._entries.values():
                for frn, entry in drive_entries.items():
                    if frn != NTFS_ROOT_FRN and entry.name:
                        new_list.append(entry)
            self._all_entries = new_list

    def start_monitoring(self):
        """Start the USN journal monitor thread."""
        if self._monitor_thread and self._monitor_thread.isRunning():
            return

        self._monitor_thread = USNMonitorThread(self)
        self._monitor_thread.changes_detected.connect(self._apply_usn_changes)
        self._monitor_thread.start()
        logger.info("USN journal monitoring started")

    def stop_monitoring(self):
        """Stop the USN journal monitor thread."""
        if self._monitor_thread:
            self._monitor_thread.stop()
            self._monitor_thread.wait(3000)
            self._monitor_thread = None
            logger.info("USN journal monitoring stopped")

    def _apply_usn_changes(self, changes: list):
        """Apply USN journal changes to the index."""
        if not changes:
            return

        added = 0
        removed = 0
        modified = 0

        with self._lock:
            for drive, record in changes:
                drive_entries = self._entries.get(drive, {})

                if record.is_delete and record.is_close:
                    # File deleted
                    if record.frn in drive_entries:
                        del drive_entries[record.frn]
                        removed += 1

                elif record.is_create and record.is_close:
                    # New file created
                    entry = FileEntry(
                        frn=record.frn,
                        parent_frn=record.parent_frn,
                        name=record.name,
                        drive=drive,
                        attributes=record.attributes,
                        date_modified=record.timestamp,
                        date_created=record.timestamp,
                    )
                    drive_entries[record.frn] = entry
                    added += 1

                elif record.is_rename and (record.reason & USN_REASON_RENAME_NEW_NAME) and record.is_close:
                    # File renamed - update name
                    existing = drive_entries.get(record.frn)
                    if existing:
                        existing.name = record.name
                        existing.parent_frn = record.parent_frn
                        existing.invalidate_path()
                        modified += 1
                    else:
                        entry = FileEntry(
                            frn=record.frn,
                            parent_frn=record.parent_frn,
                            name=record.name,
                            drive=drive,
                            attributes=record.attributes,
                            date_modified=record.timestamp,
                        )
                        drive_entries[record.frn] = entry
                        added += 1

                elif record.is_modify and record.is_close:
                    # File modified
                    existing = drive_entries.get(record.frn)
                    if existing:
                        existing.date_modified = record.timestamp
                        existing.attributes = record.attributes
                        # If data changed, invalidate cached size so next access re-reads
                        if record.reason & (
                            USN_REASON_DATA_OVERWRITE | USN_REASON_DATA_EXTEND |
                            USN_REASON_DATA_TRUNCATION
                        ):
                            existing._stat_loaded = False
                        modified += 1

        if added or removed:
            self._rebuild_flat_list()

        total_changes = added + removed + modified
        if total_changes > 0:
            self._stats.last_update = datetime.now()
            self.index_updated.emit(total_changes)
            logger.debug(f"Applied {total_changes} changes: +{added} -{removed} ~{modified}")

    def get_usn_positions(self) -> dict[str, tuple[int, int]]:
        """Get current USN journal positions for all indexed volumes."""
        positions = {}
        for drive, vol in self._volumes.items():
            positions[drive] = (vol.journal_id, vol.current_usn)
        return positions

    def save_to_cache(self):
        """Save the current index state to disk cache."""
        from core.cache import save_cache
        save_cache(self, self.get_usn_positions())

    def get_file_size(self, entry: FileEntry) -> int:
        """Get file size via OS (not stored in MFT enum)."""
        try:
            path = entry.get_path(self)
            if os.path.exists(path):
                return os.path.getsize(path)
        except (OSError, PermissionError):
            pass
        return 0

    def shutdown(self):
        """Clean shutdown of index and monitoring."""
        self.stop_monitoring()
        for vol in self._volumes.values():
            vol.close()
        self._volumes.clear()


class USNMonitorThread(QThread):
    """Background thread that polls USN journals for filesystem changes."""
    changes_detected = pyqtSignal(list)

    def __init__(self, index: FileIndex, poll_interval_ms: int = 1000):
        super().__init__()
        self._index = index
        self._poll_interval = poll_interval_ms / 1000.0
        self._running = False

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        logger.info("USN monitor thread started")

        while self._running:
            all_changes = []

            for drive, vol in self._index._volumes.items():
                try:
                    records = vol.read_usn_journal()
                    for rec in records:
                        # Only process records with CLOSE flag to avoid duplicates
                        if rec.is_close:
                            all_changes.append((drive, rec))
                except Exception as e:
                    logger.error(f"Error reading USN journal on {drive}: {e}")

            if all_changes:
                self.changes_detected.emit(all_changes)

            # Sleep in small increments so we can check _running flag
            elapsed = 0.0
            while elapsed < self._poll_interval and self._running:
                time.sleep(0.1)
                elapsed += 0.1

        logger.info("USN monitor thread stopped")


class IndexWorker(QThread):
    """Worker thread for initial MFT indexing."""
    finished = pyqtSignal()

    def __init__(self, index: FileIndex, drives: Optional[list[str]] = None,
                 use_cache: bool = True):
        super().__init__()
        self._index = index
        self._drives = drives
        self._use_cache = use_cache

    def run(self):
        if self._use_cache:
            loaded = self._index.load_from_cache(self._drives)
            if loaded:
                self.finished.emit()
                return
            logger.info("No cache found, performing full MFT scan")

        self._index.index_all_drives(self._drives)
        self.finished.emit()
