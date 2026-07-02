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
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QThread, QTimer

from core.ntfs import (
    NTFSVolume, FileRecord, USNRecord, get_ntfs_drives, get_all_drives, DriveInfo,
    FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_ATTRIBUTE_EA,
    USN_REASON_FILE_CREATE, USN_REASON_FILE_DELETE,
    USN_REASON_RENAME_OLD_NAME, USN_REASON_RENAME_NEW_NAME,
    USN_REASON_CLOSE, USN_REASON_BASIC_INFO_CHANGE,
    USN_REASON_DATA_OVERWRITE, USN_REASON_DATA_EXTEND, USN_REASON_DATA_TRUNCATION
)
from core.network_shares import (
    connect_network_share,
    network_source_key,
    normalize_network_root,
)
from core.platform_engines import PlatformRoot, select_platform_engine

logger = logging.getLogger('QuickFind.Index')

# Root directory FRN for NTFS is always 5
NTFS_ROOT_FRN = 5


@dataclass
class DriveState:
    """Runtime trust state for a cached or indexed drive."""
    letter: str
    filesystem: str = ""
    drive_type: int = 0
    label: str = ""
    online: bool = False
    stale: bool = False
    stale_reason: str = ""
    last_seen: Optional[datetime] = None
    last_scan: Optional[datetime] = None
    refresh_error: str = ""

    @property
    def state(self) -> str:
        if not self.online:
            return "offline"
        if self.stale:
            return "stale"
        return "online"


class FileEntry:
    """A file or folder in the index with resolved path information.
    Uses __slots__ for minimal memory footprint across millions of entries.
    """
    __slots__ = ('frn', 'parent_frn', 'name', 'drive', 'attributes',
                 'size', 'date_modified', 'date_created', 'reparse_tag',
                 'has_extended_attributes', 'content_snippet', 'content_rank',
                 '_path', '_stat_loaded')

    def __init__(self, frn: int, parent_frn: int, name: str, drive: str,
                 attributes: int = 0, size: int = 0,
                 date_modified: Optional[datetime] = None,
                 date_created: Optional[datetime] = None,
                 reparse_tag: int = 0,
                 has_extended_attributes: bool = False):
        self.frn = frn
        self.parent_frn = parent_frn
        self.name = name
        self.drive = drive
        self.attributes = attributes
        self.size = size
        self.date_modified = date_modified
        self.date_created = date_created
        self.reparse_tag = reparse_tag
        self.has_extended_attributes = has_extended_attributes
        self.content_snippet: str = ""
        self.content_rank: float = 0.0
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
        # Network share source key -> UNC root path
        self._network_roots: dict[str, str] = {}
        # POSIX platform source key -> root metadata
        self._platform_roots: dict[str, PlatformRoot] = {}
        self._platform_engine = select_platform_engine()
        self._platform_watch_thread: Optional['PlatformWatchThread'] = None
        # Runtime online/offline/stale state for indexed or cached drives
        self._drive_states: dict[str, DriveState] = {}
        # All entries flat list for search (rebuilt after indexing)
        self._all_entries: list[FileEntry] = []
        self._lock = threading.RLock()
        self._stats = IndexStats()
        self._monitor_thread: Optional[USNMonitorThread] = None
        self._rescan_thread: Optional['FATRescanThread'] = None
        self._cancel_flag = False
        self._next_synthetic_frn = self._SYNTHETIC_FRN_BASE
        self._admin_mode: bool = True  # Assume admin; set False if MFT access fails
        self._last_index_source: str = "not indexed"

        # Filtering options (set from settings before indexing)
        self._exclude_hidden: bool = False
        self._exclude_system: bool = False
        self._exclude_globs: list[str] = []
        self._exclude_regexes: list[str] = []
        self._exclude_regex_objects: list[re.Pattern] = []
        self._exclude_attribute_mask: int = 0
        self._follow_reparse_points: bool = False
        self._index_case_mode: str = "smart"
        self._usn_poll_interval_ms: int = 1000
        self._drive_rescan_intervals: dict[str, int] = {}

    @property
    def stats(self) -> IndexStats:
        return self._stats

    @property
    def all_entries(self) -> list[FileEntry]:
        return self._all_entries

    @property
    def is_admin_mode(self) -> bool:
        return self._admin_mode

    @property
    def last_index_source(self) -> str:
        return self._last_index_source

    def set_external_source(self, source: str) -> None:
        self._last_index_source = source or "external source"

    def set_exclude_rules(self, globs: Optional[list[str]] = None,
                          regexes: Optional[list[str]] = None,
                          attribute_mask: int = 0) -> None:
        self._exclude_globs = [p.strip() for p in (globs or []) if p and p.strip()]
        self._exclude_regexes = [p.strip() for p in (regexes or []) if p and p.strip()]
        self._exclude_attribute_mask = int(attribute_mask or 0)
        self._exclude_regex_objects = []
        for pattern in self._exclude_regexes:
            try:
                self._exclude_regex_objects.append(re.compile(pattern, re.IGNORECASE))
            except re.error as exc:
                logger.warning("Ignoring invalid exclude regex %r: %s", pattern, exc)

    def _available_drive_info(self) -> dict[str, DriveInfo]:
        return {d.letter.upper(): d for d in get_all_drives()}

    def _state_for_drive(self, drive: str) -> DriveState:
        drive = self._state_key(drive)
        state = self._drive_states.get(drive)
        if state is None:
            state = DriveState(letter=drive)
            self._drive_states[drive] = state
        return state

    @staticmethod
    def _state_key(drive: str) -> str:
        if drive.startswith(("POSIX:", "UNC:")):
            return drive
        return drive.upper()

    def _mark_drive_available(self, info: DriveInfo, *, stale: bool = False,
                              reason: str = "") -> None:
        state = self._state_for_drive(info.letter)
        state.filesystem = info.filesystem
        state.drive_type = info.drive_type
        state.label = info.label
        state.online = True
        state.stale = stale
        state.stale_reason = reason if stale else ""
        state.last_seen = datetime.now()
        state.refresh_error = ""

    def _mark_drive_fresh(self, drive: str, info: Optional[DriveInfo] = None) -> None:
        if info is None:
            info = self._available_drive_info().get(drive.upper())
        if info is not None:
            self._mark_drive_available(info, stale=False)
        else:
            state = self._state_for_drive(drive)
            state.online = True
            state.stale = False
            state.stale_reason = ""
        self._state_for_drive(drive).last_scan = datetime.now()

    def _mark_drive_stale(self, drive: str, reason: str, *,
                          info: Optional[DriveInfo] = None,
                          online: bool = False,
                          error: str = "") -> None:
        if info is not None:
            self._mark_drive_available(info, stale=True, reason=reason)
            state = self._state_for_drive(info.letter)
            state.online = online
        else:
            state = self._state_for_drive(drive)
            state.online = online
            state.stale = True
            state.stale_reason = reason
        state.refresh_error = error

    def _mark_cached_drive_states(self, drives: list[str]) -> None:
        available = self._available_drive_info()
        for drive in sorted({self._state_key(d) for d in drives}):
            platform_root = self._platform_roots.get(drive)
            if platform_root is not None:
                self._mark_platform_root_state(
                    platform_root,
                    stale=True,
                    reason="Loaded from cache; waiting for native watcher catchup",
                    online=os.path.exists(platform_root.path),
                )
                continue
            info = available.get(drive)
            if info:
                self._mark_drive_stale(
                    drive,
                    "Loaded from cache; waiting for catchup or refresh",
                    info=info,
                    online=True,
                )
            else:
                self._mark_drive_stale(
                    drive,
                    "Drive unavailable; cached results may be stale",
                    online=False,
                )

    def _recount_stats(self) -> None:
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
        total = total_files + total_folders
        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = sorted(self._entries)
        self._stats.last_update = datetime.now()
        if self._stats.index_time_ms > 0:
            self._stats.entries_per_sec = total / (self._stats.index_time_ms / 1000.0)

    @staticmethod
    def _drive_type_name(drive_type: int) -> str:
        return {
            2: "removable",
            3: "fixed",
            4: "remote",
        }.get(drive_type, "unknown")

    def index_diagnostics(self) -> dict:
        """Return structured index state for UI diagnostics."""
        platform_monitor_running = bool(
            self._platform_watch_thread and self._platform_watch_thread.isRunning()
        )
        monitor_running = bool(self._monitor_thread and self._monitor_thread.isRunning()) or platform_monitor_running
        rescan_running = bool(self._rescan_thread and self._rescan_thread.isRunning())
        pending_usn = bool(getattr(self, '_pending_usn_positions', None))
        return {
            "source": self._last_index_source,
            "admin_mode": self._admin_mode,
            "case_mode": self._index_case_mode,
            "total_entries": len(self._all_entries),
            "total_files": self._stats.total_files,
            "total_folders": self._stats.total_folders,
            "volumes_indexed": list(self._stats.volumes_indexed),
            "index_time_ms": self._stats.index_time_ms,
            "entries_per_sec": self._stats.entries_per_sec,
            "last_update": self._stats.last_update.isoformat(timespec="seconds") if self._stats.last_update else "",
            "monitor_running": monitor_running,
            "rescan_running": rescan_running,
            "pending_usn_catchup": pending_usn,
            "drive_states": {
                drive: state.state
                for drive, state in sorted(self._drive_states.items())
            },
            "drives": self.drive_diagnostics(),
        }

    def drive_diagnostics(self) -> list[dict]:
        """Return per-drive index mode, counts, and USN position details."""
        rows = []
        with self._lock:
            drive_letters = sorted(self._entries)
            for drive in drive_letters:
                entries = self._entries.get(drive, {})
                files = 0
                folders = 0
                for frn, entry in entries.items():
                    if frn == NTFS_ROOT_FRN:
                        continue
                    if entry.is_dir:
                        folders += 1
                    else:
                        files += 1

                volume = self._volumes.get(drive)
                platform_root = self._platform_roots.get(drive)
                if platform_root is not None:
                    mode = f"{platform_root.watcher} + os.scandir"
                    if platform_root.search_fallback:
                        mode += f" + {platform_root.search_fallback}"
                elif drive in self._walked_drives:
                    mode = "os.scandir fallback" if not self._admin_mode else "os.scandir"
                elif volume is not None:
                    mode = "MFT + USN"
                else:
                    mode = "cache"

                state = self._state_for_drive(drive)
                rows.append({
                    "drive": drive,
                    "state": state.state,
                    "online": state.online,
                    "stale": state.stale,
                    "stale_reason": state.stale_reason,
                    "drive_type": self._drive_type_name(state.drive_type),
                    "filesystem": state.filesystem,
                    "label": state.label,
                    "last_seen": state.last_seen.isoformat(timespec="seconds") if state.last_seen else "",
                    "last_scan": state.last_scan.isoformat(timespec="seconds") if state.last_scan else "",
                    "refresh_error": state.refresh_error,
                    "mode": mode,
                    "entries": files + folders,
                    "files": files,
                    "folders": folders,
                    "journal_id": getattr(volume, "journal_id", 0) if volume else 0,
                    "next_usn": getattr(volume, "current_usn", 0) if volume else 0,
                    "monitoring": bool(
                        (
                            platform_root is not None
                            and self._platform_watch_thread
                            and self._platform_watch_thread.isRunning()
                        )
                        or (
                            volume is not None
                            and self._monitor_thread
                            and self._monitor_thread.isRunning()
                        )
                    ),
                    "rescanning": bool(
                        platform_root is None
                        and (
                            drive in self._walked_drives
                            and self._rescan_thread
                            and self._rescan_thread.isRunning()
                        )
                    ),
                })
        return rows

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
        original_drive = drive
        drive = drive.upper() if len(drive) <= 3 and not drive.startswith("POSIX:") else drive
        source_root = self._source_root_path(original_drive)
        visited = set()

        with self._lock:
            drive_entries = self._entries.get(drive, {})
            if source_root is not None:
                entry = drive_entries.get(frn)
                if entry and entry._path:
                    return entry._path
                if frn == NTFS_ROOT_FRN:
                    return source_root
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
        if source_root is not None:
            return os.path.join(source_root, *parts) if parts else source_root
        return f"{drive}:\\" + "\\".join(parts) if parts else f"{drive}:\\"

    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        """Resolve just the parent directory path."""
        source_root = self._source_root_path(drive)
        if source_root is not None and parent_frn == NTFS_ROOT_FRN:
            return source_root
        if parent_frn == NTFS_ROOT_FRN:
            return f"{drive.upper()}:\\"
        return self.resolve_path(drive, parent_frn)

    def _source_root_path(self, source_key: str) -> Optional[str]:
        if source_key in self._network_roots:
            return self._network_roots[source_key]
        root = self._platform_roots.get(source_key)
        return root.path if root else None

    def cancel_indexing(self):
        """Signal to cancel any in-progress indexing."""
        self._cancel_flag = True

    def _is_cancelled(self) -> bool:
        return self._cancel_flag

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

        loaded_drives = sorted(self._entries)
        if drives is None:
            if not self._platform_engine.is_windows:
                self._refresh_platform_roots(None)
            drives = loaded_drives
        elif not self._platform_engine.is_windows:
            platform_roots = self._refresh_platform_roots(drives)
            drives = [root.key for root in platform_roots] or loaded_drives
        else:
            drives = [drive.upper() for drive in drives]
        self._mark_cached_drive_states(loaded_drives)
        for drive in sorted(set(drives) - set(loaded_drives)):
            self._mark_drive_stale(
                drive,
                "Selected drive was not present in the cache",
                online=False,
            )

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
        self._last_index_source = "SQLite cache"
        self._stats.total_files = total_files
        self._stats.total_folders = total_folders
        self._stats.volumes_indexed = loaded_drives
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
        available = self._available_drive_info()

        for drive_letter in drives:
            if self._cancel_flag:
                break
            if drive_letter not in self._entries:
                continue
            platform_root = self._platform_roots.get(drive_letter)
            if platform_root is not None:
                if not os.path.exists(platform_root.path):
                    self._mark_platform_root_state(
                        platform_root,
                        stale=True,
                        reason="Root unavailable; cached results may be stale",
                        online=False,
                    )
                    continue
                logger.info("Re-walking platform root %s for cache catchup", platform_root.path)
                old_count = len(self._entries.get(drive_letter, {}))
                self._walk_platform_root(platform_root)
                new_count = len(self._entries.get(drive_letter, {}))
                diff = abs(new_count - old_count)
                if diff > 0:
                    total_changes += diff
                    walked_updated = True
                continue
            drive_info = available.get(drive_letter)

            # Non-NTFS drives: re-walk to detect changes
            if drive_letter in self._walked_drives:
                if not drive_info:
                    self._mark_drive_stale(
                        drive_letter,
                        "Drive unavailable; cached results may be stale",
                        online=False,
                    )
                    continue
                logger.info(f"Re-walking non-NTFS drive {drive_letter}: for catchup")
                old_count = len(self._entries.get(drive_letter, {}))
                self._walk_drive(drive_letter)
                new_count = len(self._entries.get(drive_letter, {}))
                diff = abs(new_count - old_count)
                if diff > 0:
                    total_changes += diff
                    walked_updated = True
                self._mark_drive_fresh(drive_letter, drive_info)
                continue

            # NTFS drives: USN journal catchup
            vol = NTFSVolume(drive_letter)
            if not vol.open():
                self._mark_drive_stale(
                    drive_letter,
                    "Drive unavailable; cached results may be stale",
                    info=drive_info,
                    online=drive_info is not None,
                )
                continue

            vol_info = vol.get_volume_info()
            if vol_info and vol_info.filesystem.upper() != 'NTFS':
                self._mark_drive_stale(
                    drive_letter,
                    f"Drive filesystem changed to {vol_info.filesystem}; refresh required",
                    info=drive_info,
                    online=True,
                )
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
                    self._mark_drive_fresh(drive_letter, drive_info)
                else:
                    logger.warning(f"USN journal recycled on {drive_letter}, full re-index needed")
                    needs_reindex.append((vol, drive_letter))
            else:
                self._mark_drive_stale(
                    drive_letter,
                    "USN journal unavailable; refresh required",
                    info=drive_info,
                    online=True,
                )

        # Handle NTFS drives that need full re-index
        for vol, drive_letter in needs_reindex:
            if self._cancel_flag:
                break
            self._reindex_drive(vol, drive_letter)
            self._mark_drive_fresh(drive_letter, available.get(drive_letter))

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

        if self._platform_engine.is_windows:
            self._last_index_source = "SQLite cache + USN catchup"
        else:
            self._last_index_source = (
                f"SQLite cache + {self._platform_engine.watcher} catchup"
            )
        catchup_label = "USN" if self._platform_engine.is_windows else self._platform_engine.watcher
        logger.info(f"{catchup_label} catchup: {total_changes} changes applied in {elapsed:.0f}ms")

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
                reparse_tag=rec.reparse_tag,
                has_extended_attributes=rec.has_extended_attributes,
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
                reparse_tag=rec.reparse_tag,
                has_extended_attributes=rec.has_extended_attributes,
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

    @staticmethod
    def _directory_identity(path: str):
        """Stable identity for loop-safe directory traversal."""
        try:
            st = os.stat(path)
            dev = getattr(st, "st_dev", 0)
            ino = getattr(st, "st_ino", 0)
            if dev or ino:
                return ("stat", dev, ino)
        except (OSError, PermissionError):
            pass
        try:
            resolved = os.path.realpath(path)
        except (OSError, ValueError):
            resolved = os.path.abspath(path)
        return ("path", os.path.normcase(resolved))

    @classmethod
    def _reserve_directory_for_walk(cls, path: str, visited: set) -> bool:
        """Return True once per resolved directory target."""
        identity = cls._directory_identity(path)
        if identity in visited:
            return False
        visited.add(identity)
        return True

    def index_network_roots(self, roots: Optional[list[str]], rebuild: bool = True) -> list[str]:
        """Index configured SMB/UNC roots through read-only directory walking."""
        indexed_sources: list[str] = []
        for raw_root in roots or []:
            try:
                root = normalize_network_root(raw_root)
            except ValueError as exc:
                logger.warning("Skipping invalid network root %r: %s", raw_root, exc)
                continue

            source_key = network_source_key(root)
            self._network_roots[source_key] = root
            try:
                connect_network_share(root)
            except Exception as exc:
                logger.warning("Could not connect stored credential for %s: %s", root, exc)

            self._walk_network_root(source_key, root)
            indexed_sources.append(source_key)

        if rebuild:
            self._rebuild_flat_list()
            self._recount_stats()
        return indexed_sources

    def _refresh_platform_roots(self, configured: Optional[list[str]] = None) -> list[PlatformRoot]:
        if self._platform_engine.is_windows:
            return []
        roots = self._platform_engine.discover_roots(configured)
        for root in roots:
            self._platform_roots[root.key] = root
        return roots

    def _mark_platform_root_state(self, root: PlatformRoot, *, stale: bool = False,
                                  reason: str = "", online: bool = True,
                                  error: str = "") -> None:
        state = self._drive_states.get(root.key)
        if state is None:
            state = DriveState(letter=root.key)
            self._drive_states[root.key] = state
        state.filesystem = root.filesystem
        state.drive_type = 0
        state.label = root.label
        state.online = online
        state.stale = stale
        state.stale_reason = reason if stale else ""
        state.last_seen = datetime.now() if online else state.last_seen
        if online and not stale:
            state.last_scan = datetime.now()
        state.refresh_error = error

    def _walk_platform_root(self, root: PlatformRoot) -> int:
        """Index a POSIX root using recursive os.scandir and synthetic FRNs."""
        self._platform_roots[root.key] = root
        logger.info(
            "Walking %s root %s via os.scandir (%s)...",
            self._platform_engine.display_name,
            root.path,
            root.watcher,
        )
        if not os.path.exists(root.path):
            self._mark_platform_root_state(
                root,
                stale=True,
                reason="Root unavailable; cached results may be stale",
                online=False,
            )
            return len(self._entries.get(root.key, {}))

        drive_entries: dict[int, FileEntry] = {}
        root_frn = NTFS_ROOT_FRN
        root_entry = FileEntry(
            frn=root_frn, parent_frn=0, name="",
            drive=root.key, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )
        root_entry._path = root.path
        root_entry._stat_loaded = True
        drive_entries[root_frn] = root_entry

        dir_frn_map: dict[str, int] = {root.path: root_frn}
        visited_dirs = set()
        self._reserve_directory_for_walk(root.path, visited_dirs)
        total = 0
        callback_interval = 10000
        stack = [root.path]

        while stack:
            if self._cancel_flag:
                break

            current_dir = stack.pop()
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
                            st = de.stat(follow_symlinks=False)
                            is_reparse = False
                            try:
                                is_reparse = de.is_symlink()
                            except OSError:
                                pass
                            is_dir = de.is_dir(follow_symlinks=False)
                            if is_reparse and self._follow_reparse_points:
                                try:
                                    is_dir = is_dir or de.is_dir(follow_symlinks=True)
                                except OSError:
                                    pass

                            self._next_synthetic_frn += 1
                            frn = self._next_synthetic_frn

                            attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_ARCHIVE
                            if is_reparse:
                                attrs |= FILE_ATTRIBUTE_REPARSE_POINT

                            entry = FileEntry(
                                frn=frn,
                                parent_frn=parent_frn,
                                name=name,
                                drive=root.key,
                                attributes=attrs,
                                size=st.st_size if not is_dir else 0,
                                date_modified=datetime.fromtimestamp(st.st_mtime),
                                date_created=datetime.fromtimestamp(st.st_ctime),
                            )
                            entry._stat_loaded = True
                            entry._path = de.path

                            excluded = self._should_exclude(entry)
                            if excluded:
                                if is_dir:
                                    logger.debug("Skipped excluded platform directory: %s", de.path)
                                continue

                            drive_entries[frn] = entry
                            total += 1

                            if is_dir:
                                full_path = de.path
                                should_descend = (
                                    not is_reparse or self._follow_reparse_points
                                )
                                if should_descend and self._reserve_directory_for_walk(full_path, visited_dirs):
                                    dir_frn_map[full_path] = frn
                                    stack.append(full_path)

                            if total % callback_interval == 0:
                                self.indexing_progress.emit(root.label, total)

                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

        dir_frn_map.clear()

        with self._lock:
            self._entries[root.key] = drive_entries
            self._walked_drives.add(root.key)

        self._mark_platform_root_state(root)
        logger.info("Platform root walk complete on %s: %s entries", root.path, f"{total:,}")
        self.indexing_progress.emit(root.label, total)
        return total

    def _index_platform_roots(self, configured: Optional[list[str]] = None) -> None:
        roots = self._refresh_platform_roots(configured)
        start_time = time.perf_counter()

        for root in roots:
            if self._cancel_flag:
                break
            self._mark_platform_root_state(
                root,
                stale=True,
                reason="Index refresh in progress",
                online=True,
            )
            self._walk_platform_root(root)
            self._rebuild_flat_list()

        self._rebuild_flat_list()
        self._recount_stats()

        elapsed = (time.perf_counter() - start_time) * 1000
        total = self._stats.total_files + self._stats.total_folders
        self._stats.volumes_indexed = sorted(self._entries)
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()
        self._stats.entries_per_sec = (total / (elapsed / 1000.0)) if elapsed > 0 else 0
        self._last_index_source = (
            f"{self._platform_engine.display_name} os.scandir + SQLite cache"
        )
        logger.info(
            "%s indexing complete: %s entries in %.0fms",
            self._platform_engine.display_name,
            f"{total:,}",
            elapsed,
        )
        self.indexing_complete.emit(self._stats)

    def _walk_drive(self, drive_letter: str):
        """
        Index a non-NTFS drive (FAT32, exFAT, ReFS) or fallback drive via recursive os.scandir.
        Generates synthetic FRNs and pre-resolves full paths.
        """
        root = f"{drive_letter}:\\"
        logger.info(f"Walking drive {drive_letter}: via os.scandir...")
        if not os.path.exists(root):
            self._mark_drive_stale(
                drive_letter,
                "Drive unavailable; cached results may be stale",
                online=False,
            )
            logger.warning(f"Skipping unavailable drive {drive_letter}: during os.scandir refresh")
            return len(self._entries.get(drive_letter, {}))

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
        visited_dirs = set()
        self._reserve_directory_for_walk(root, visited_dirs)
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
                            st = de.stat(follow_symlinks=False)
                            raw_attrs = getattr(st, "st_file_attributes", 0)
                            reparse_tag = getattr(st, "st_reparse_tag", 0)
                            is_reparse = bool(raw_attrs & FILE_ATTRIBUTE_REPARSE_POINT)
                            try:
                                is_reparse = is_reparse or de.is_symlink()
                            except OSError:
                                pass
                            is_dir = bool(raw_attrs & FILE_ATTRIBUTE_DIRECTORY) if raw_attrs else de.is_dir(follow_symlinks=False)
                            if is_reparse and self._follow_reparse_points:
                                try:
                                    is_dir = is_dir or de.is_dir(follow_symlinks=True)
                                except OSError:
                                    pass

                            self._next_synthetic_frn += 1
                            frn = self._next_synthetic_frn

                            attrs = raw_attrs or (FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_ARCHIVE)
                            if is_dir:
                                attrs |= FILE_ATTRIBUTE_DIRECTORY
                            elif not attrs:
                                attrs = FILE_ATTRIBUTE_ARCHIVE

                            entry = FileEntry(
                                frn=frn,
                                parent_frn=parent_frn,
                                name=name,
                                drive=drive_letter,
                                attributes=attrs,
                                size=st.st_size if not is_dir else 0,
                                date_modified=datetime.fromtimestamp(st.st_mtime),
                                date_created=datetime.fromtimestamp(st.st_ctime),
                                reparse_tag=reparse_tag,
                                has_extended_attributes=bool(raw_attrs & FILE_ATTRIBUTE_EA),
                            )
                            entry._stat_loaded = True
                            entry._path = de.path

                            excluded = self._should_exclude(entry)
                            if excluded:
                                if is_dir:
                                    logger.debug("Skipped excluded directory during walk: %s", de.path)
                                continue

                            drive_entries[frn] = entry
                            total += 1

                            if is_dir:
                                full_path = de.path
                                should_descend = (
                                    not is_reparse or self._follow_reparse_points
                                )
                                if should_descend and self._reserve_directory_for_walk(full_path, visited_dirs):
                                    dir_frn_map[full_path] = frn
                                    stack.append(full_path)
                                elif is_reparse:
                                    logger.debug("Skipped reparse directory during walk: %s", full_path)

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

        self._mark_drive_fresh(drive_letter)
        logger.info(f"Walk complete on {drive_letter}: {total:,} entries")
        self.indexing_progress.emit(drive_letter, total)
        return total

    def _walk_network_root(self, source_key: str, root_path: str) -> int:
        """Index a UNC root using recursive os.scandir without drive metadata."""
        logger.info("Walking network root %s at %s via os.scandir...", source_key, root_path)
        if not os.path.exists(root_path):
            logger.warning("Skipping unavailable network root %s: %s", source_key, root_path)
            return len(self._entries.get(source_key, {}))

        drive_entries: dict[int, FileEntry] = {}
        root_frn = NTFS_ROOT_FRN
        drive_entries[root_frn] = FileEntry(
            frn=root_frn, parent_frn=0, name="",
            drive=source_key, attributes=FILE_ATTRIBUTE_DIRECTORY,
        )

        dir_frn_map: dict[str, int] = {root_path: root_frn}
        visited_dirs = set()
        self._reserve_directory_for_walk(root_path, visited_dirs)
        total = 0
        callback_interval = 10000

        stack = [root_path]
        while stack:
            if self._cancel_flag:
                break

            current_dir = stack.pop()
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
                            st = de.stat(follow_symlinks=False)
                            raw_attrs = getattr(st, "st_file_attributes", 0)
                            reparse_tag = getattr(st, "st_reparse_tag", 0)
                            is_reparse = bool(raw_attrs & FILE_ATTRIBUTE_REPARSE_POINT)
                            try:
                                is_reparse = is_reparse or de.is_symlink()
                            except OSError:
                                pass
                            is_dir = bool(raw_attrs & FILE_ATTRIBUTE_DIRECTORY) if raw_attrs else de.is_dir(follow_symlinks=False)
                            if is_reparse and self._follow_reparse_points:
                                try:
                                    is_dir = is_dir or de.is_dir(follow_symlinks=True)
                                except OSError:
                                    pass

                            self._next_synthetic_frn += 1
                            frn = self._next_synthetic_frn

                            attrs = raw_attrs or (FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_ARCHIVE)
                            if is_dir:
                                attrs |= FILE_ATTRIBUTE_DIRECTORY
                            elif not attrs:
                                attrs = FILE_ATTRIBUTE_ARCHIVE

                            entry = FileEntry(
                                frn=frn,
                                parent_frn=parent_frn,
                                name=name,
                                drive=source_key,
                                attributes=attrs,
                                size=st.st_size if not is_dir else 0,
                                date_modified=datetime.fromtimestamp(st.st_mtime),
                                date_created=datetime.fromtimestamp(st.st_ctime),
                                reparse_tag=reparse_tag,
                                has_extended_attributes=bool(raw_attrs & FILE_ATTRIBUTE_EA),
                            )
                            entry._stat_loaded = True
                            entry._path = de.path

                            excluded = self._should_exclude(entry)
                            if excluded:
                                if is_dir:
                                    logger.debug("Skipped excluded network directory: %s", de.path)
                                continue

                            drive_entries[frn] = entry
                            total += 1

                            if is_dir:
                                full_path = de.path
                                should_descend = (
                                    not is_reparse or self._follow_reparse_points
                                )
                                if should_descend and self._reserve_directory_for_walk(full_path, visited_dirs):
                                    dir_frn_map[full_path] = frn
                                    stack.append(full_path)
                                elif is_reparse:
                                    logger.debug("Skipped reparse network directory: %s", full_path)

                            if total % callback_interval == 0:
                                self.indexing_progress.emit(source_key, total)

                        except (OSError, PermissionError):
                            continue
            except (OSError, PermissionError):
                continue

        dir_frn_map.clear()

        with self._lock:
            self._entries[source_key] = drive_entries

        logger.info("Network root walk complete on %s: %s entries", source_key, f"{total:,}")
        self.indexing_progress.emit(source_key, total)
        return total

    def index_all_drives(self, drives: Optional[list[str]] = None,
                         force_walk: bool = False,
                         network_roots: Optional[list[str]] = None):
        """
        Index all supported drives (NTFS via MFT in parallel, FAT/exFAT/ReFS via os.scandir).
        If force_walk=True or MFT access fails, falls back to os.scandir for all drives.
        This should be called from a worker thread.
        """
        self._cancel_flag = False
        self._admin_mode = not force_walk
        self.indexing_started.emit()

        if not self._platform_engine.is_windows:
            self._admin_mode = False
            self._index_platform_roots(drives)
            return

        # Build drive info map for all available drives
        all_drive_info = {d.letter: d for d in get_all_drives()}

        if drives is None:
            drives = [d.letter for d in all_drive_info.values()]
        else:
            drives = [drive.upper() for drive in drives]

        for drive_letter in drives:
            info = all_drive_info.get(drive_letter)
            if info:
                self._mark_drive_available(info, stale=True, reason="Index refresh in progress")
            else:
                self._mark_drive_stale(
                    drive_letter,
                    "Drive unavailable at startup; cached results may be stale",
                    online=False,
                )

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
            self._rebuild_flat_list()
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
                            self._walked_drives.discard(drive_letter)

                        self._mark_drive_fresh(drive_letter, all_drive_info.get(drive_letter))
                        total_files += files
                        total_folders += folders
                        self._rebuild_flat_list()
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
                self._rebuild_flat_list()
                drive_entries = self._entries.get(drive_letter, {})
                for frn, entry in drive_entries.items():
                    if frn == NTFS_ROOT_FRN:
                        continue
                    if entry.is_dir:
                        total_folders += 1
                    else:
                        total_files += 1

        if force_walk:
            self._last_index_source = "Full os.scandir scan"
        elif mft_failed_drives:
            self._last_index_source = "Full scan with os.scandir fallback"
        elif non_ntfs_drives:
            self._last_index_source = "Full scan (MFT + os.scandir)"
        else:
            self._last_index_source = "Full MFT scan"

        if network_roots and not self._cancel_flag:
            self.index_network_roots(network_roots, rebuild=False)
            self._last_index_source += " + network shares"

        # Final rebuild to ensure consistency
        self._rebuild_flat_list()
        self._recount_stats()

        elapsed = (time.perf_counter() - start_time) * 1000
        total_files = self._stats.total_files
        total_folders = self._stats.total_folders
        total = total_files + total_folders

        self._stats.volumes_indexed = sorted(self._entries)
        self._stats.index_time_ms = int(elapsed)
        self._stats.last_update = datetime.now()
        self._stats.entries_per_sec = (total / (elapsed / 1000.0)) if elapsed > 0 else 0

        logger.info(
            f"Indexing complete: {total_files} files, {total_folders} folders "
            f"in {elapsed:.0f}ms across {len(drives)} drives"
            f" ({self._stats.entries_per_sec:,.0f} entries/sec)"
        )
        self.indexing_complete.emit(self._stats)

    def refresh_drive(self, drive_letter: str) -> str:
        """Refresh one indexed drive and update its stale/offline state."""
        drive_letter = drive_letter.strip().upper().rstrip(":\\")
        if not drive_letter:
            raise ValueError("Drive letter is required")

        available = self._available_drive_info()
        info = available.get(drive_letter)
        if not info:
            self._mark_drive_stale(
                drive_letter,
                "Drive unavailable; cached results may be stale",
                online=False,
            )
            return f"{drive_letter}: is offline; cached results kept as stale."

        self._mark_drive_available(info, stale=True, reason="Refresh in progress")
        old_count = len(self._entries.get(drive_letter, {}))

        if info.needs_walk:
            self._walk_drive(drive_letter)
        else:
            drive, drive_entries, vol, _files, _folders = self._index_single_ntfs_drive(drive_letter)
            if drive_entries:
                with self._lock:
                    old_vol = self._volumes.get(drive)
                    if old_vol and old_vol is not vol:
                        try:
                            old_vol.close()
                        except Exception:
                            pass
                    self._entries[drive] = drive_entries
                    if vol:
                        self._volumes[drive] = vol
                    self._walked_drives.discard(drive)
                self._mark_drive_fresh(drive, info)
            else:
                self._walk_drive(drive_letter)

        self._rebuild_flat_list()
        new_count = len(self._entries.get(drive_letter, {}))
        self._recount_stats()
        self._last_index_source = f"Drive refresh: {drive_letter}:"
        changes = abs(new_count - old_count)
        self.index_updated.emit(changes)
        return f"{drive_letter}: refreshed ({new_count:,} cached records)."

    def _should_exclude(self, entry: FileEntry) -> bool:
        """Check if an entry should be excluded based on attribute filters."""
        if self._exclude_hidden and (entry.attributes & FILE_ATTRIBUTE_HIDDEN):
            return True
        if self._exclude_system and (entry.attributes & FILE_ATTRIBUTE_SYSTEM):
            return True
        if self._exclude_attribute_mask and (entry.attributes & self._exclude_attribute_mask):
            return True
        if self._exclude_globs or self._exclude_regex_objects:
            try:
                path = entry._path or entry.get_path(self)
            except Exception as exc:
                logger.debug("Could not resolve path for exclude rules: %s", exc)
                path = entry.name
            path_lower = path.lower()
            name_lower = entry.name.lower()
            for pattern in self._exclude_globs:
                pattern_lower = pattern.lower()
                if (
                    fnmatch.fnmatch(entry.name, pattern)
                    or fnmatch.fnmatch(path, pattern)
                    or fnmatch.fnmatch(name_lower, pattern_lower)
                    or fnmatch.fnmatch(path_lower, pattern_lower)
                ):
                    return True
            for regex in self._exclude_regex_objects:
                if regex.search(entry.name) or regex.search(path):
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
        if not self._platform_engine.is_windows:
            if self._platform_roots and (
                not self._platform_watch_thread
                or not self._platform_watch_thread.isRunning()
            ):
                self._platform_watch_thread = PlatformWatchThread(
                    list(self._platform_roots.values())
                )
                self._platform_watch_thread.roots_changed.connect(
                    self._on_platform_roots_changed
                )
                self._platform_watch_thread.start()
                logger.info(
                    "%s monitoring started for %s roots",
                    self._platform_engine.watcher,
                    len(self._platform_roots),
                )
            return

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

    def stop_monitoring(self):
        """Stop the USN journal monitor thread and FAT rescan thread."""
        if self._platform_watch_thread:
            self._platform_watch_thread.stop()
            self._platform_watch_thread.wait(5000)
            self._platform_watch_thread = None
            logger.info("%s monitoring stopped", self._platform_engine.watcher)
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

    def _on_fat_rescan(self, changes: int):
        """Handle FAT rescan completion.
        Always rebuilds flat list to release stale FileEntry references
        from the previous walk (even when count is unchanged, entries were replaced).
        """
        self._rebuild_flat_list()
        self._stats.last_update = datetime.now()
        if changes > 0:
            self.index_updated.emit(changes)

    def _on_platform_roots_changed(self, root_keys: list[str]):
        """Handle native POSIX watcher changes by re-walking affected roots."""
        total_changes = 0
        walked_any = False
        for root_key in root_keys:
            root = self._platform_roots.get(root_key)
            if root is None:
                continue
            old_count = len(self._entries.get(root.key, {}))
            self._walk_platform_root(root)
            new_count = len(self._entries.get(root.key, {}))
            total_changes += abs(new_count - old_count)
            walked_any = True

        if walked_any:
            self._rebuild_flat_list()
            self._recount_stats()
            self._stats.last_update = datetime.now()
            self.index_updated.emit(total_changes)

    @staticmethod
    def _invalidate_subtree_paths(drive_entries: dict, root_frn: int):
        """Clear cached _path on every descendant of root_frn within a drive.

        Called after a directory rename/move so descendants re-resolve their
        full path through the updated parent chain instead of serving a stale
        cached path (wrong results, failed opens, persisted stale DB rows).
        """
        children: dict[int, list[int]] = {}
        for frn, entry in drive_entries.items():
            children.setdefault(entry.parent_frn, []).append(frn)
        stack = list(children.get(root_frn, []))
        while stack:
            frn = stack.pop()
            entry = drive_entries.get(frn)
            if entry is None:
                continue
            entry.invalidate_path()
            stack.extend(children.get(frn, []))

    def _apply_usn_changes(self, changes: list):
        """Apply USN journal changes to the index and batch-sync to DB."""
        if not changes:
            return

        from core.cache import db_batch_apply

        added = 0
        removed = 0
        modified = 0
        touched_drives = set()

        # Collect batch operations for single-transaction DB write
        db_inserts = []
        db_deletes = []
        db_updates = []

        with self._lock:
            for drive, record in changes:
                touched_drives.add(drive)
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
                        has_extended_attributes=bool(record.attributes & FILE_ATTRIBUTE_EA),
                    )
                    drive_entries[record.frn] = entry
                    added += 1
                    path = entry.get_path(self)
                    db_inserts.append((entry, path))

                elif record.is_rename and (record.reason & USN_REASON_RENAME_NEW_NAME) and record.is_close:
                    # File renamed - update name
                    existing = drive_entries.get(record.frn)
                    if existing:
                        was_dir = existing.is_dir
                        existing.name = record.name
                        existing.parent_frn = record.parent_frn
                        existing.invalidate_path()
                        # A renamed/moved directory changes the resolved path of
                        # every descendant; clear their cached paths so they
                        # re-resolve through the (now-updated) parent chain.
                        if was_dir:
                            self._invalidate_subtree_paths(drive_entries, record.frn)
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
                            has_extended_attributes=bool(record.attributes & FILE_ATTRIBUTE_EA),
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
                        existing.has_extended_attributes = bool(record.attributes & FILE_ATTRIBUTE_EA)
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
        db_success = True
        if db_inserts or db_deletes or db_updates:
            db_success = db_batch_apply(db_inserts, db_deletes, db_updates)

        if db_success:
            self._persist_usn_checkpoints(touched_drives)

        total_changes = added + removed + modified
        if total_changes > 0:
            self._stats.last_update = datetime.now()
            self.index_updated.emit(total_changes)
            logger.debug(f"Applied {total_changes} changes: +{added} -{removed} ~{modified}")

    def _persist_usn_checkpoints(self, drives: set[str]):
        """Flush current journal positions after a successful USN apply batch."""
        if not drives:
            return
        from core.cache import db_update_usn_position

        for drive in sorted(drives):
            vol = self._volumes.get(drive)
            if vol is None:
                continue
            journal_id = int(getattr(vol, "journal_id", 0) or 0)
            next_usn = int(getattr(vol, "current_usn", 0) or 0)
            if journal_id <= 0 or next_usn <= 0:
                continue
            if db_update_usn_position(drive, journal_id, next_usn):
                logger.debug("Persisted USN checkpoint for %s: %s/%s", drive, journal_id, next_usn)

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


class PlatformWatchThread(QThread):
    """Background native filesystem watcher for POSIX platform roots."""
    roots_changed = pyqtSignal(list)

    def __init__(self, roots: list[PlatformRoot], debounce_seconds: float = 1.0):
        super().__init__()
        self._roots = roots
        self._debounce_seconds = debounce_seconds
        self._running = False
        self._pending: dict[str, float] = {}
        self._pending_lock = threading.Lock()
        self._observer = None

    def stop(self):
        self._running = False
        if self._observer is not None:
            self._observer.stop()

    def notify(self, root_key: str):
        with self._pending_lock:
            self._pending[root_key] = time.monotonic()

    def _pop_due_roots(self) -> list[str]:
        now = time.monotonic()
        due = []
        with self._pending_lock:
            for root_key, last_event in list(self._pending.items()):
                if now - last_event >= self._debounce_seconds:
                    due.append(root_key)
                    del self._pending[root_key]
        return due

    def run(self):
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog is missing; native platform monitoring disabled")
            return

        watch_thread = self

        class Handler(FileSystemEventHandler):
            def __init__(self, root_key: str):
                super().__init__()
                self._root_key = root_key

            def on_any_event(self, _event):
                watch_thread.notify(self._root_key)

        self._observer = Observer()
        scheduled = 0
        for root in self._roots:
            if not os.path.isdir(root.path):
                continue
            try:
                self._observer.schedule(Handler(root.key), root.path, recursive=True)
                scheduled += 1
            except OSError as exc:
                logger.warning("Could not watch platform root %s: %s", root.path, exc)

        if scheduled == 0:
            return

        self._running = True
        self._observer.start()
        logger.info("Native platform watcher scheduled for %s roots", scheduled)
        try:
            while self._running:
                time.sleep(0.25)
                due = self._pop_due_roots()
                if due:
                    self.roots_changed.emit(due)
        finally:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None


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

            # Snapshot under the lock: other threads (catchup, refresh_drive)
            # insert into _volumes, and iterating it live raises "dictionary
            # changed size during iteration", which would kill this thread and
            # silently stop all real-time index updates for the session.
            with self._index._lock:
                volumes = list(self._index._volumes.items())

            for drive, vol in volumes:
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
                 use_cache: bool = True,
                 startup_delay_seconds: int = 0,
                 network_roots: Optional[list[str]] = None):
        super().__init__()
        self._index = index
        self._drives = drives
        self._use_cache = use_cache
        self._startup_delay_seconds = max(0, int(startup_delay_seconds or 0))
        self._network_roots = network_roots or []

    def _wait_for_startup_delay(self):
        if self._startup_delay_seconds <= 0:
            return
        logger.info(
            "Waiting %ss before drive discovery for late-mounted drives",
            self._startup_delay_seconds,
        )
        deadline = time.monotonic() + self._startup_delay_seconds
        while time.monotonic() < deadline:
            if self._index._is_cancelled():
                return
            time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

    def run(self):
        self._wait_for_startup_delay()
        if self._use_cache:
            loaded = self._index.load_from_cache(self._drives)
            if loaded:
                self.cache_loaded.emit()
                # USN catchup happens after UI has displayed cached results
                self._index.usn_catchup()
                if self._network_roots:
                    self._index.index_network_roots(self._network_roots)
                self.finished.emit()
                return
            logger.info("No cache found, performing full MFT scan")

        self._index.index_all_drives(self._drives, network_roots=self._network_roots)
        self.finished.emit()
