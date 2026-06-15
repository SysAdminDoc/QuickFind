"""
In-memory file index with path resolution and real-time USN journal monitoring.

Maintains a dict of FRN -> FileEntry for each indexed volume, resolves full paths
via parent-child FRN relationships, and runs a background thread to poll the
USN journal for filesystem changes.

v0.6.0: Batch DB writes, deferred path resolution, non-admin fallback (os.scandir).
"""

import os
import time
import fnmatch
import logging
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer

from core.ntfs import (
    NTFSVolume, FileRecord, USNRecord, get_ntfs_drives, get_all_drives, DriveInfo,
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM,
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_CLOSE, USN_REASON_BASIC_INFO_CHANGE,
    USN_REASON_DATA_OVERWRITE, USN_REASON_DATA_EXTEND, USN_REASON_DATA_TRUNCATION
)

logger = logging.getLogger('QuickFind.Index')

# Root directory FRN for NTFS is always 5
NTFS_ROOT_FRN = 5

# Deferred path resolution: batch resolve paths on a timer instead of per-entry
_PATH_RESOLVE_INTERVAL_MS = 500
_PATH_RESOLVE_BATCH_SIZE = 1000


class FileEntry:
    """A file or folder in the index with resolved path information.
    Uses __slots__ for minimal memory footprint across millions of entries.
    """
    __slots__ = ('frn', 'parent_frn', 'name', 'drive', 'attributes',
                 'size', 'date_modified', 'date_created', '_path', '_stat_loaded')

    def __init__(self, frn: int, parent_frn: int, name: str, drive: str,
                 attributes: int = 0, size: int = 0,
                 date_modified: Optional[datetime] = None,
                 date_created: Optional[datetime] = None):
        self.frn = frn
        self.parent_frn = parent_frn
        self.name = name
        self.drive = drive
        self.attributes = attributes
        self.size = size
        self.date_modified = date_modified
        self.date_created = date_created
        self._path: Optional[str] = None
        self._stat_loaded: bool = False

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
        self.entries_per_sec: float = 0.0  # Startup performance metric


class FileIndex(QObject):
    """
    Central in-memory file index.
    Indexes NTFS volumes via MFT and FAT/exFAT/ReFS volumes via os.scandir,
    resolves paths, and monitors USN journals for real-time updates on NTFS.

    v0.6.0: Non-admin fallback (os.scandir for all drives if no admin),
             deferred path resolution, batch DB writes.
    """
    # Signals
    indexing_started = pyqtSignal()
    indexing_progress = pyqtSignal(str, int)  # (drive_letter, record_count)
    indexing_complete = pyqtSignal(object)  # IndexStats
    index_updated = pyqtSignal(int)  # number of changes applied
    error_occurred = pyqtSignal(str)

    # Synthetic FRN counter for non-NTFS drives (start high to avoid NTFS FRN collisions)
    _SYNTHETIC_FRN_BASE = 0x1_0000_0000

    def __init__(self, parent=None):
        super().__init__(parent)
        # Per-drive index: drive_letter -> {frn -> FileEntry}
        self._entries: dict[str, dict[int, FileEntry]] = {}
        # Per-drive volume handles for journal monitoring (NTFS only)
        self._volumes: dict[str, NTFSVolume] = {}
        # Drives indexed via os.scandir (FAT/exFAT/ReFS or non-admin fallback)
        self._walked_drives: set[str] = set()
        # All entries flat list for search (rebuilt after indexing)
        self._all_entries: list[FileEntry] = []
        self._lock = threading.RLock()
        self._stats = IndexStats()
        self._monitor_thread: Optional[USNMonitorThread] = None
        self._rescan_thread: Optional['FATRescanThread'] = None
        self._cancel_flag = False
        self._next_synthetic_frn = self._SYNTHETIC_FRN_BASE
        self._admin_mode: bool = True  # Assume admin; set False if MFT access fails

        # Filtering options (set from settings before indexing)
        self._exclude_hidden: bool = False
        self._exclude_system: bool = False
        self._usn_poll_interval_ms: int = 1000
        self._drive_rescan_intervals: dict[str, int] = {}

        # Deferred path resolution queue
        self._path_resolve_queue: deque[FileEntry] = deque()
        self._path_resolve_timer: Optional[QTimer] = None

    @property
    def stats(self) -> IndexStats:
        return self._stats

    @property
    def all_entries(self) -> list[FileEntry]:
        return self._all_entries

    @property
    def is_admin_mode(self) -> bool:
        return self._admin_mode

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

    # ── Deferred Path Resolution ─────────────────────────

    def queue_path_resolve(self, entry: FileEntry):
        """Queue an entry for deferred path resolution."""
        self._path_resolve_queue.append(entry)

    def _start_path_resolve_timer(self):
        """Start the deferred path resolution timer."""
        if self._path_resolve_timer is None:
            self._path_resolve_timer = QTimer()
            self._path_resolve_timer.setInterval(_PATH_RESOLVE_INTERVAL_MS)
            self._path_resolve_timer.timeout.connect(self._flush_path_resolve)
        if not self._path_resolve_timer.isActive():
            self._path_resolve_timer.start()

    def _flush_path_resolve(self):
        """Resolve queued paths in a batch."""
        if not self._path_resolve_queue:
            if self._path_resolve_timer:
                self._path_resolve_timer.stop()
            return

        batch = []
        count = 0
        while self._path_resolve_queue and count < _PATH_RESOLVE_BATCH_SIZE:
            entry = self._path_resolve_queue.popleft()
            if entry._path is None:
                entry._path = self.resolve_path(entry.drive, entry.frn)
                batch.append(entry)
            count += 1

        if batch:
            logger.debug(f"Deferred path resolve: {len(batch)} entries")

    # ── Cache Load/Save ──────────────────────────────────

    def load_from_cache(self, drives: Optional[list[str]] = None) -> bool:
        """
        Try to load the index from disk cache.
        Emits indexing_complete immediately so the UI can display results,
        then performs USN journal catchup in a separate pass.
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

        if drives is None:
            drives = get_ntfs_drives()

        # Count stats from cached data
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
        total = total_files + total_folders
        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = drives
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()
        self._stats.entries_per_sec = (total / (elapsed / 1000.0)) if elapsed > 0 else 0

        logger.info(
            f"Cache loaded: {total_files} files, {total_folders} folders in {elapsed:.0f}ms"
            f" ({self._stats.entries_per_sec:,.0f} entries/sec)"
        )
        # Emit immediately so UI shows cached results while USN catches up
        self.indexing_complete.emit(self._stats)

        # Store positions for deferred USN catchup
        self._pending_usn_positions = usn_positions
        self._pending_usn_drives = drives
        return True

    def usn_catchup(self):
        """
        Catch up the index via USN journal (NTFS) or re-walk (FAT/exFAT/ReFS)
        after a cache load. Called on a worker thread after the UI is already
        showing cached results.
        """
        usn_positions = getattr(self, '_pending_usn_positions', None)
        drives = getattr(self, '_pending_usn_drives', None)
        if not usn_positions or not drives:
            return

        start_time = time.perf_counter()
        total_changes = 0
        needs_reindex = []
        walked_updated = False

        for drive_letter in drives:
            if self._cancel_flag:
                break
            if drive_letter not in self._entries:
                continue

            # Non-NTFS drives: re-walk to detect changes
            if drive_letter in self._walked_drives:
                logger.info(f"Re-walking non-NTFS drive {drive_letter}: for catchup")
                old_count = len(self._entries.get(drive_letter, {}))
                self._walk_drive(drive_letter)
                new_count = len(self._entries.get(drive_letter, {}))
                diff = abs(new_count - old_count)
                if diff > 0:
                    total_changes += diff
                    walked_updated = True
                continue

            # NTFS drives: USN journal catchup
            vol = NTFSVolume(drive_letter)
            if not vol.open():
                continue

            vol_info = vol.get_volume_info()
            if vol_info and vol_info.filesystem.upper() != 'NTFS':
                vol.close()
                continue

            with self._lock:
                self._volumes[drive_letter] = vol

            journal_id, next_usn = usn_positions.get(drive_letter, (0, 0))
            if vol.query_usn_journal():
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
                else:
                    logger.warning(f"USN journal recycled on {drive_letter}, full re-index needed")
                    needs_reindex.append((vol, drive_letter))

        # Handle NTFS drives that need full re-index
        for vol, drive_letter in needs_reindex:
            if self._cancel_flag:
                break
            self._reindex_drive(vol, drive_letter)

        elapsed = (time.perf_counter() - start_time) * 1000

        if total_changes > 0 or needs_reindex or walked_updated:
            # Rebuild flat list if walked drives changed
            if walked_updated:
                self._rebuild_flat_list()
            # Recount stats after catchup
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
            self._stats.total_files = total_files
            self._stats.total_folders = total_folders
            self._stats.last_update = datetime.now()
            self.index_updated.emit(total_changes)

        logger.info(f"USN catchup: {total_changes} changes applied in {elapsed:.0f}ms")

        # Cleanup
        self._pending_usn_positions = None
        self._pending_usn_drives = None

    def _reindex_drive(self, vol: NTFSVolume, drive_letter: str):
        """Full re-index of a single drive."""
        def progress_cb(record, count):
            self.indexing_progress.emit(drive_letter, count)

        drive_entries: dict[int, FileEntry] = {}
        drive_entries[NTFS_ROOT_FRN] = FileEntry(
            frn=NTFS_ROOT_FRN, parent_frn=0, name="",
            drive=drive_letter, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )

        # Consume generator directly — no intermediate list
        for rec in vol.enumerate_mft_direct(
            callback=progress_cb,
            cancel_check=self._is_cancelled
        ):
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

    def _index_single_ntfs_drive(self, drive_letter: str) -> tuple[str, dict[int, FileEntry], NTFSVolume, int, int]:
        """
        Index a single NTFS drive via MFT. Called from thread pool.
        Returns (drive_letter, drive_entries, volume, file_count, folder_count).
        """
        vol = NTFSVolume(drive_letter)
        if not vol.open():
            return (drive_letter, {}, None, 0, 0)

        vol_info = vol.get_volume_info()
        if vol_info and vol_info.filesystem.upper() != 'NTFS':
            logger.info(f"Skipping unsupported volume {drive_letter}: ({vol_info.filesystem})")
            vol.close()
            return (drive_letter, {}, None, 0, 0)

        def progress_cb(record, count):
            self.indexing_progress.emit(drive_letter, count)

        drive_entries: dict[int, FileEntry] = {}
        drive_entries[NTFS_ROOT_FRN] = FileEntry(
            frn=NTFS_ROOT_FRN, parent_frn=0, name="",
            drive=drive_letter, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )

        files = 0
        folders = 0
        # Consume generator directly — FileRecord objects are immediately
        # converted to FileEntry and discarded, halving peak memory
        for rec in vol.enumerate_mft_direct(
            callback=progress_cb,
            cancel_check=self._is_cancelled
        ):
            entry = FileEntry(
                frn=rec.frn, parent_frn=rec.parent_frn, name=rec.name,
                drive=drive_letter, attributes=rec.attributes,
                size=rec.size,
                date_modified=rec.timestamp,
                date_created=rec.date_created,
            )
            entry._stat_loaded = rec.mft_metadata
            drive_entries[rec.frn] = entry

            if rec.is_dir:
                folders += 1
            else:
                files += 1

        vol.query_usn_journal()
        self.indexing_progress.emit(drive_letter, files + folders)

        return (drive_letter, drive_entries, vol, files, folders)

    @staticmethod
    def _load_ignore_patterns(directory: str) -> list[str]:
        """Load patterns from .quickfindignore in the given directory."""
        ignore_file = os.path.join(directory, '.quickfindignore')
        try:
            with open(ignore_file, 'r', encoding='utf-8') as f:
                return [
                    line.strip() for line in f
                    if line.strip() and not line.startswith('#')
                ]
        except (OSError, PermissionError):
            return []

    @staticmethod
    def _matches_ignore(name: str, patterns: list[str]) -> bool:
        """Check if a filename matches any ignore pattern (fnmatch glob)."""
        for pat in patterns:
            if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(name.lower(), pat.lower()):
                return True
        return False

    def _walk_drive(self, drive_letter: str):
        """
        Index a non-NTFS drive (FAT32, exFAT, ReFS) or fallback drive via recursive os.scandir.
        Generates synthetic FRNs and pre-resolves full paths.
        """
        root = f"{drive_letter}:\\"
        logger.info(f"Walking drive {drive_letter}: via os.scandir...")

        drive_entries: dict[int, FileEntry] = {}
        # Root entry
        root_frn = NTFS_ROOT_FRN
        drive_entries[root_frn] = FileEntry(
            frn=root_frn, parent_frn=0, name="",
            drive=drive_letter, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )

        # Map directory paths to their synthetic FRN for parent resolution.
        # Entries are popped after processing so memory stays proportional
        # to current stack depth rather than total directory count.
        dir_frn_map: dict[str, int] = {root: root_frn}
        total = 0
        callback_interval = 10000

        stack = [root]
        while stack:
            if self._cancel_flag:
                break

            current_dir = stack.pop()
            # Pop instead of get — this directory's FRN is no longer needed
            # in the map once we've retrieved it (children look up their own
            # path, not their parent's)
            parent_frn = dir_frn_map.pop(current_dir, root_frn)

            try:
                ignore_patterns = self._load_ignore_patterns(current_dir)
                with os.scandir(current_dir) as it:
                    for de in it:
                        if self._cancel_flag:
                            break
                        try:
                            name = de.name
                            if ignore_patterns and self._matches_ignore(name, ignore_patterns):
                                continue
                            is_dir = de.is_dir(follow_symlinks=False)
                            st = de.stat(follow_symlinks=False)

                            self._next_synthetic_frn += 1
                            frn = self._next_synthetic_frn

                            attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_ARCHIVE

                            entry = FileEntry(
                                frn=frn,
                                parent_frn=parent_frn,
                                name=name,
                                drive=drive_letter,
                                attributes=attrs,
                                size=st.st_size if not is_dir else 0,
                                date_modified=datetime.fromtimestamp(st.st_mtime),
                                date_created=datetime.fromtimestamp(st.st_ctime),
                            )
                            entry._stat_loaded = True
                            drive_entries[frn] = entry
                            total += 1

                            if is_dir:
                                full_path = de.path
                                dir_frn_map[full_path] = frn
                                stack.append(full_path)

                            if total % callback_interval == 0:
                                self.indexing_progress.emit(drive_letter, total)

                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

        # Explicitly clear — shouldn't have entries but ensures no lingering refs
        dir_frn_map.clear()

        with self._lock:
            self._entries[drive_letter] = drive_entries
            self._walked_drives.add(drive_letter)

        logger.info(f"Walk complete on {drive_letter}: {total:,} entries")
        self.indexing_progress.emit(drive_letter, total)
        return total

    def index_all_drives(self, drives: Optional[list[str]] = None,
                         force_walk: bool = False):
        """
        Index all supported drives (NTFS via MFT in parallel, FAT/exFAT/ReFS via os.scandir).
        If force_walk=True or MFT access fails, falls back to os.scandir for all drives.
        This should be called from a worker thread.
        """
        self._cancel_flag = False
        self.indexing_started.emit()

        # Build drive info map for all available drives
        all_drive_info = {d.letter: d for d in get_all_drives()}

        if drives is None:
            drives = [d.letter for d in all_drive_info.values()]

        start_time = time.perf_counter()
        total_files = 0
        total_folders = 0

        # Separate NTFS and non-NTFS drives
        ntfs_drives = []
        non_ntfs_drives = []
        for drive_letter in drives:
            info = all_drive_info.get(drive_letter)
            if force_walk or (info and info.needs_walk):
                non_ntfs_drives.append(drive_letter)
            elif info and info.is_ntfs:
                ntfs_drives.append(drive_letter)
            else:
                # Unknown filesystem — try walk
                non_ntfs_drives.append(drive_letter)

        # Index non-NTFS drives sequentially (they use synthetic FRNs with shared counter)
        for drive_letter in non_ntfs_drives:
            if self._cancel_flag:
                break
            info = all_drive_info.get(drive_letter)
            logger.info(f"Indexing drive {drive_letter}: ({info.filesystem if info else 'unknown'}) via os.scandir...")
            self._walk_drive(drive_letter)
            drive_entries = self._entries.get(drive_letter, {})
            for frn, entry in drive_entries.items():
                if frn == NTFS_ROOT_FRN:
                    continue
                if entry.is_dir:
                    total_folders += 1
                else:
                    total_files += 1

        # Index NTFS drives in parallel (one thread per drive)
        mft_failed_drives = []
        if ntfs_drives and not self._cancel_flag:
            max_workers = min(len(ntfs_drives), os.cpu_count() or 4)
            logger.info(f"Parallel MFT scan: {len(ntfs_drives)} NTFS drives with {max_workers} threads")

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._index_single_ntfs_drive, dl): dl
                    for dl in ntfs_drives
                }

                for future in as_completed(futures):
                    if self._cancel_flag:
                        break
                    try:
                        drive_letter, drive_entries, vol, files, folders = future.result()
                        if not drive_entries:
                            # MFT access failed — queue for os.scandir fallback
                            mft_failed_drives.append(drive_letter)
                            continue

                        with self._lock:
                            self._entries[drive_letter] = drive_entries
                            if vol:
                                self._volumes[drive_letter] = vol

                        total_files += files
                        total_folders += folders
                        logger.info(f"Drive {drive_letter}: indexed: {files:,} files, {folders:,} folders")

                    except Exception as e:
                        dl = futures[future]
                        logger.error(f"Error indexing drive {dl}: {e}")
                        mft_failed_drives.append(dl)

        # Non-admin fallback: walk NTFS drives that failed MFT access
        if mft_failed_drives and not self._cancel_flag:
            self._admin_mode = False
            logger.warning(
                f"MFT access failed for {', '.join(mft_failed_drives)}. "
                f"Falling back to os.scandir (non-admin mode)."
            )
            for drive_letter in mft_failed_drives:
                if self._cancel_flag:
                    break
                self._walk_drive(drive_letter)
                drive_entries = self._entries.get(drive_letter, {})
                for frn, entry in drive_entries.items():
                    if frn == NTFS_ROOT_FRN:
                        continue
                    if entry.is_dir:
                        total_folders += 1
                    else:
                        total_files += 1

        # Rebuild flat list
        self._rebuild_flat_list()

        elapsed = (time.perf_counter() - start_time) * 1000
        total = total_files + total_folders

        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = drives
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()
        self._stats.entries_per_sec = (total / (elapsed / 1000.0)) if elapsed > 0 else 0

        logger.info(
            f"Indexing complete: {total_files} files, {total_folders} folders "
            f"in {elapsed:.0f}ms across {len(drives)} drives"
            f" ({self._stats.entries_per_sec:,.0f} entries/sec)"
        )
        self.indexing_complete.emit(self._stats)

    def _should_exclude(self, entry: FileEntry) -> bool:
        """Check if an entry should be excluded based on attribute filters."""
        if self._exclude_hidden and (entry.attributes & FILE_ATTRIBUTE_HIDDEN):
            return True
        if self._exclude_system and (entry.attributes & FILE_ATTRIBUTE_SYSTEM):
            return True
        return False

    def _rebuild_flat_list(self):
        """Rebuild the flat list of all entries for searching.
        Builds into a new list first to avoid a window where all_entries is empty.
        """
        new_list = []
        with self._lock:
            for drive_entries in self._entries.values():
                for frn, entry in drive_entries.items():
                    if frn != NTFS_ROOT_FRN and entry.name:
                        if not self._should_exclude(entry):
                            new_list.append(entry)
            self._all_entries = new_list

    def start_monitoring(self):
        """Start the USN journal monitor thread and FAT rescan thread."""
        if self._monitor_thread and self._monitor_thread.isRunning():
            pass  # Already running
        else:
            self._monitor_thread = USNMonitorThread(self, poll_interval_ms=self._usn_poll_interval_ms)
            self._monitor_thread.changes_detected.connect(self._apply_usn_changes)
            self._monitor_thread.start()
            logger.info(f"USN journal monitoring started (poll interval: {self._usn_poll_interval_ms}ms)")

        # Start periodic rescan for non-NTFS drives
        if self._walked_drives:
            if not self._rescan_thread or not self._rescan_thread.isRunning():
                self._rescan_thread = FATRescanThread(
                    self, drive_intervals=self._drive_rescan_intervals
                )
                self._rescan_thread.rescan_complete.connect(self._on_fat_rescan)
                self._rescan_thread.start()
                logger.info(f"FAT rescan thread started for drives: {', '.join(sorted(self._walked_drives))}")

        # Start deferred path resolution timer
        self._start_path_resolve_timer()

    def stop_monitoring(self):
        """Stop the USN journal monitor thread and FAT rescan thread."""
        if self._monitor_thread:
            self._monitor_thread.stop()
            self._monitor_thread.wait(3000)
            self._monitor_thread = None
            logger.info("USN journal monitoring stopped")
        if self._rescan_thread:
            self._rescan_thread.stop()
            self._rescan_thread.wait(5000)
            self._rescan_thread = None
            logger.info("FAT rescan thread stopped")
        if self._path_resolve_timer:
            self._path_resolve_timer.stop()

    def _on_fat_rescan(self, changes: int):
        """Handle FAT rescan completion.
        Always rebuilds flat list to release stale FileEntry references
        from the previous walk (even when count is unchanged, entries were replaced).
        """
        self._rebuild_flat_list()
        self._stats.last_update = datetime.now()
        if changes > 0:
            self.index_updated.emit(changes)

    def _apply_usn_changes(self, changes: list):
        """Apply USN journal changes to the index and batch-sync to DB."""
        if not changes:
            return

        from core.cache import db_batch_apply

        added = 0
        removed = 0
        modified = 0

        # Collect batch operations for single-transaction DB write
        db_inserts = []
        db_deletes = []
        db_updates = []

        with self._lock:
            for drive, record in changes:
                drive_entries = self._entries.get(drive, {})

                if record.is_delete and record.is_close:
                    # File deleted
                    if record.frn in drive_entries:
                        del drive_entries[record.frn]
                        removed += 1
                        db_deletes.append((drive, record.frn))

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
                    path = entry.get_path(self)
                    db_inserts.append((entry, path))

                elif record.is_rename and (record.reason & USN_REASON_RENAME_NEW_NAME) and record.is_close:
                    # File renamed - update name
                    existing = drive_entries.get(record.frn)
                    if existing:
                        existing.name = record.name
                        existing.parent_frn = record.parent_frn
                        existing.invalidate_path()
                        modified += 1
                        path = existing.get_path(self)
                        db_updates.append((existing, path))
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
                        path = entry.get_path(self)
                        db_inserts.append((entry, path))

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
                        db_updates.append((existing, ""))

            # Rebuild flat list under same lock to prevent concurrent modification
            if added or removed:
                new_list = []
                for de in self._entries.values():
                    for frn, entry in de.items():
                        if frn != NTFS_ROOT_FRN and entry.name:
                            if not self._should_exclude(entry):
                                new_list.append(entry)
                self._all_entries = new_list

        # Single-transaction batch DB write (outside lock to avoid holding it during I/O)
        if db_inserts or db_deletes or db_updates:
            db_batch_apply(db_inserts, db_deletes, db_updates)

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


class FATRescanThread(QThread):
    """Background thread that periodically re-walks non-NTFS drives to detect changes.

    Supports per-drive rescan intervals via drive_intervals dict.
    """
    rescan_complete = pyqtSignal(int)  # total changed entries

    DEFAULT_INTERVAL = 60

    def __init__(self, index: FileIndex,
                 interval_seconds: int = 60,
                 drive_intervals: Optional[dict[str, int]] = None):
        super().__init__()
        self._index = index
        self._default_interval = interval_seconds
        self._drive_intervals = drive_intervals or {}
        self._running = False

    def _get_interval(self, drive_letter: str) -> int:
        return self._drive_intervals.get(drive_letter, self._default_interval)

    def stop(self):
        self._running = False

    def run(self):
        self._running = True
        logger.info("FAT rescan thread started")

        last_scan: dict[str, float] = {}
        for d in self._index._walked_drives:
            last_scan[d] = time.monotonic()

        while self._running:
            time.sleep(0.5)
            if not self._running:
                break

            now = time.monotonic()
            walked_any = False
            total_changes = 0

            for drive_letter in list(self._index._walked_drives):
                if not self._running:
                    break
                interval = self._get_interval(drive_letter)
                if now - last_scan.get(drive_letter, 0) < interval:
                    continue
                try:
                    old_count = len(self._index._entries.get(drive_letter, {}))
                    self._index._walk_drive(drive_letter)
                    new_count = len(self._index._entries.get(drive_letter, {}))
                    total_changes += abs(new_count - old_count)
                    walked_any = True
                    last_scan[drive_letter] = time.monotonic()
                except Exception as e:
                    logger.error(f"Error re-walking {drive_letter}: {e}")
                    last_scan[drive_letter] = time.monotonic()

            if walked_any:
                self.rescan_complete.emit(total_changes)

        logger.info("FAT rescan thread stopped")


class IndexWorker(QThread):
    """Worker thread for initial MFT indexing."""
    finished = pyqtSignal()
    cache_loaded = pyqtSignal()  # Emitted when cache is loaded (before USN catchup)

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
                self.cache_loaded.emit()
                # USN catchup happens after UI has displayed cached results
                self._index.usn_catchup()
                self.finished.emit()
                return
            logger.info("No cache found, performing full MFT scan")

        self._index.index_all_drives(self._drives)
        self.finished.emit()
