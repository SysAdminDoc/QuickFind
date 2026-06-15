"""
SQLite-based index database with FTS5 search, incremental updates, and path caching.

Features:
- FTS5 full-text search on filenames and paths (trigram tokenizer for substring matching)
- Pre-resolved paths stored in DB for instant path-based search
- Batch incremental insert/delete/update (single transaction for USN changes)
- WAL mode for concurrent reads during writes
- Per-drive USN journal positions for differential updates
- Search history with autocomplete support
- DB corruption recovery (auto-detect and rebuild)

v0.6.0: Batch writes, corruption recovery, search history.
"""

import os
import sqlite3
import logging
import time
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.index import FileEntry, FileIndex, NTFS_ROOT_FRN
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY

logger = logging.getLogger('QuickFind.Cache')

CONFIG_DIR = Path.home() / '.quickfind'
DB_FILE = CONFIG_DIR / 'index.db'
OLD_CACHE_FILE = CONFIG_DIR / 'index_cache.bin'

DB_VERSION = 3

# Thread-local connections for safe multi-threaded access
import threading
_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Get a thread-local connection with WAL mode and performance pragmas."""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except Exception:
            conn = None

    CONFIG_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_FILE), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-16000")  # 16MB cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
    _local.conn = conn
    return conn


def _close_connection():
    """Close the thread-local connection."""
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None


def _has_fts5() -> bool:
    """Check if FTS5 is available in this SQLite build."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _test USING fts5(x)")
        conn.execute("DROP TABLE _test")
        conn.close()
        return True
    except Exception:
        return False


def _has_trigram() -> bool:
    """Check if the FTS5 trigram tokenizer is available."""
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE _test USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE _test")
        conn.close()
        return True
    except Exception:
        return False


# Detect capabilities at import time
_FTS5_AVAILABLE = _has_fts5()
_TRIGRAM_AVAILABLE = _has_trigram() if _FTS5_AVAILABLE else False

if _FTS5_AVAILABLE:
    if _TRIGRAM_AVAILABLE:
        logger.info("SQLite FTS5 with trigram tokenizer available")
    else:
        logger.info("SQLite FTS5 available (no trigram — using unicode61)")
else:
    logger.warning("SQLite FTS5 not available — falling back to LIKE queries")


def _init_schema(conn: sqlite3.Connection):
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS drives (
            letter TEXT PRIMARY KEY,
            flags INTEGER DEFAULT 0,
            journal_id INTEGER DEFAULT 0,
            next_usn INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS entries (
            frn INTEGER NOT NULL,
            drive TEXT NOT NULL,
            parent_frn INTEGER NOT NULL,
            name TEXT NOT NULL,
            path TEXT DEFAULT '',
            attributes INTEGER DEFAULT 0,
            size INTEGER DEFAULT 0,
            date_modified_ms INTEGER DEFAULT 0,
            date_created_ms INTEGER DEFAULT 0,
            PRIMARY KEY (drive, frn)
        );

        CREATE INDEX IF NOT EXISTS idx_entries_name ON entries(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_entries_drive ON entries(drive);
        CREATE INDEX IF NOT EXISTS idx_entries_ext ON entries(
            CASE WHEN instr(name, '.') > 0
                 THEN lower(substr(name, length(name) - instr(substr(name || '.', 1), '.') + 2))
                 ELSE '' END
        );
        CREATE INDEX IF NOT EXISTS idx_entries_size ON entries(size);
        CREATE INDEX IF NOT EXISTS idx_entries_date_mod ON entries(date_modified_ms);

        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            result_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_history_query ON search_history(query);
        CREATE INDEX IF NOT EXISTS idx_history_ts ON search_history(timestamp DESC);

        CREATE TABLE IF NOT EXISTS usage_stats (
            path TEXT PRIMARY KEY,
            open_count INTEGER DEFAULT 0,
            last_opened_ms INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_usage_count ON usage_stats(open_count DESC);
    """)

    # FTS5 table for fast substring search
    if _FTS5_AVAILABLE:
        tokenizer = 'trigram' if _TRIGRAM_AVAILABLE else 'unicode61'
        try:
            conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts
                USING fts5(name, path, tokenize='{tokenizer}',
                           content='entries', content_rowid='rowid')
            """)
        except Exception as e:
            logger.warning(f"Failed to create FTS5 table: {e}")

    # Set/update version
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)",
        (str(DB_VERSION),)
    )
    conn.commit()


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


# Drive flags
DRIVE_FLAG_WALKED = 0x01


_fts_pending_changes = 0
_FTS_REBUILD_THRESHOLD = 1000


def _rebuild_fts(conn: sqlite3.Connection):
    """Rebuild the FTS5 index from the entries table."""
    global _fts_pending_changes
    if not _FTS5_AVAILABLE:
        return
    try:
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
        _fts_pending_changes = 0
    except Exception as e:
        logger.warning(f"FTS rebuild failed: {e}")


# ── DB Integrity / Corruption Recovery ────────────────────

def check_db_integrity() -> bool:
    """Run PRAGMA integrity_check on the database. Returns True if OK."""
    if not DB_FILE.exists():
        return True
    try:
        conn = _get_connection()
        result = conn.execute("PRAGMA integrity_check").fetchone()
        ok = result and result[0] == 'ok'
        if not ok:
            logger.error(f"DB integrity check failed: {result}")
        return ok
    except Exception as e:
        logger.error(f"DB integrity check error: {e}")
        return False


def recover_db() -> bool:
    """Attempt to recover a corrupt database by deleting and allowing rebuild."""
    logger.warning("Attempting DB recovery — deleting corrupt database")
    _close_connection()
    try:
        if DB_FILE.exists():
            # Try to backup first
            backup = DB_FILE.with_suffix('.db.corrupt')
            try:
                if backup.exists():
                    backup.unlink()
                DB_FILE.rename(backup)
                logger.info(f"Corrupt DB backed up to {backup}")
            except Exception:
                DB_FILE.unlink()
                logger.info("Corrupt DB deleted")

        # Also remove WAL/SHM files
        for suffix in ('.db-wal', '.db-shm'):
            wal_file = DB_FILE.parent / (DB_FILE.stem + suffix)
            if wal_file.exists():
                try:
                    wal_file.unlink()
                except Exception:
                    pass

        return True
    except Exception as e:
        logger.error(f"DB recovery failed: {e}")
        return False


def ensure_db_healthy() -> bool:
    """Check DB integrity and recover if needed. Returns True if DB is usable."""
    if not DB_FILE.exists():
        return True
    if check_db_integrity():
        return True
    return recover_db()


# ── Search History ──────────────────────────────────────

def add_search_history(query: str, result_count: int = 0):
    """Add a search query to the history table."""
    if not query or not query.strip():
        return
    try:
        conn = _get_connection()
        ts = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO search_history (query, timestamp, result_count) VALUES (?, ?, ?)",
            (query.strip(), ts, result_count)
        )
        conn.commit()

        # Prune old entries (keep last 500)
        conn.execute("""
            DELETE FROM search_history WHERE id NOT IN (
                SELECT id FROM search_history ORDER BY timestamp DESC LIMIT 500
            )
        """)
        conn.commit()
    except Exception as e:
        logger.debug(f"add_search_history failed: {e}")


def get_search_history(prefix: str = "", limit: int = 20) -> list[str]:
    """Get recent unique search queries matching a prefix (for autocomplete)."""
    try:
        conn = _get_connection()
        if prefix:
            rows = conn.execute(
                """SELECT DISTINCT query FROM search_history
                   WHERE query LIKE ? COLLATE NOCASE
                   ORDER BY MAX(timestamp) DESC LIMIT ?""",
                (f"{prefix}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT query FROM (
                       SELECT DISTINCT query, MAX(timestamp) as ts
                       FROM search_history GROUP BY query ORDER BY ts DESC LIMIT ?
                   )""",
                (limit,)
            ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def clear_search_history():
    """Clear all search history."""
    try:
        conn = _get_connection()
        conn.execute("DELETE FROM search_history")
        conn.commit()
    except Exception:
        pass


# ── Usage Tracking ─────────────────────────────────────

def record_file_open(path: str):
    """Increment the open count for a file path."""
    try:
        conn = _get_connection()
        ts = int(time.time() * 1000)
        conn.execute(
            "INSERT INTO usage_stats (path, open_count, last_opened_ms) "
            "VALUES (?, 1, ?) "
            "ON CONFLICT(path) DO UPDATE SET "
            "open_count = open_count + 1, last_opened_ms = ?",
            (path, ts, ts)
        )
        conn.commit()
    except Exception as e:
        logger.debug(f"record_file_open failed: {e}")


def get_usage_scores(paths: list[str]) -> dict[str, int]:
    """Get open counts for a list of paths."""
    if not paths:
        return {}
    try:
        conn = _get_connection()
        placeholders = ','.join('?' * len(paths))
        rows = conn.execute(
            f"SELECT path, open_count FROM usage_stats WHERE path IN ({placeholders})",
            paths
        ).fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception:
        return {}


# ── Batch DB Operations ──────────────────────────────────

def db_batch_apply(inserts: list[tuple], deletes: list[tuple],
                   updates: list[tuple], fts_dirty: bool = True):
    """
    Apply a batch of incremental changes in a single transaction.

    Args:
        inserts: list of (FileEntry, path) tuples
        deletes: list of (drive, frn) tuples
        updates: list of (FileEntry, path) tuples (path="" means skip path update)
        fts_dirty: if True, rebuild FTS after changes
    """
    if not inserts and not deletes and not updates:
        return

    try:
        conn = _get_connection()
        conn.execute("BEGIN")

        for entry, path in inserts:
            mtime_ms = _dt_to_ms(entry.date_modified)
            ctime_ms = _dt_to_ms(entry.date_created)
            conn.execute(
                "INSERT OR REPLACE INTO entries "
                "(frn, drive, parent_frn, name, path, attributes, size, "
                "date_modified_ms, date_created_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.frn, entry.drive, entry.parent_frn, entry.name, path,
                 entry.attributes, entry.size, mtime_ms, ctime_ms)
            )

        for drive, frn in deletes:
            conn.execute("DELETE FROM entries WHERE drive=? AND frn=?", (drive, frn))

        for entry, path in updates:
            mtime_ms = _dt_to_ms(entry.date_modified)
            ctime_ms = _dt_to_ms(entry.date_created)
            if path:
                conn.execute(
                    "UPDATE entries SET parent_frn=?, name=?, path=?, attributes=?, "
                    "size=?, date_modified_ms=?, date_created_ms=? "
                    "WHERE drive=? AND frn=?",
                    (entry.parent_frn, entry.name, path, entry.attributes,
                     entry.size, mtime_ms, ctime_ms, entry.drive, entry.frn)
                )
            else:
                conn.execute(
                    "UPDATE entries SET parent_frn=?, name=?, attributes=?, "
                    "size=?, date_modified_ms=?, date_created_ms=? "
                    "WHERE drive=? AND frn=?",
                    (entry.parent_frn, entry.name, entry.attributes,
                     entry.size, mtime_ms, ctime_ms, entry.drive, entry.frn)
                )

        conn.commit()

        total = len(inserts) + len(deletes) + len(updates)
        if fts_dirty and _FTS5_AVAILABLE:
            global _fts_pending_changes
            _fts_pending_changes += total
            if _fts_pending_changes >= _FTS_REBUILD_THRESHOLD:
                _rebuild_fts(conn)

        logger.debug(f"Batch applied: +{len(inserts)} -{len(deletes)} ~{len(updates)} ({total} ops)")

    except Exception as e:
        logger.error(f"db_batch_apply failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def save_cache(index: FileIndex, usn_positions: dict[str, tuple[int, int]]):
    """Save the file index to the SQLite database with pre-resolved paths."""
    start = time.perf_counter()

    try:
        conn = _get_connection()
        _init_schema(conn)

        conn.execute("BEGIN")
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM drives")

        drives = list(index._entries.keys())
        total = 0

        for drive in drives:
            drive_entries = index._entries[drive]
            journal_id, next_usn = usn_positions.get(drive, (0, 0))
            flags = DRIVE_FLAG_WALKED if drive in index._walked_drives else 0

            conn.execute(
                "INSERT INTO drives (letter, flags, journal_id, next_usn) VALUES (?, ?, ?, ?)",
                (drive, flags, journal_id, next_usn)
            )

            batch = []
            for frn, entry in drive_entries.items():
                if frn == NTFS_ROOT_FRN:
                    continue

                # Pre-resolve full path for DB storage
                path = entry.get_path(index)
                mtime_ms = _dt_to_ms(entry.date_modified) if entry._stat_loaded else 0
                ctime_ms = _dt_to_ms(entry.date_created) if entry._stat_loaded else 0
                size = entry.size if entry._stat_loaded else 0

                batch.append((
                    entry.frn, drive, entry.parent_frn, entry.name, path,
                    entry.attributes, size, mtime_ms, ctime_ms
                ))

            conn.executemany(
                "INSERT INTO entries (frn, drive, parent_frn, name, path, "
                "attributes, size, date_modified_ms, date_created_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch
            )
            total += len(batch)

        now_str = datetime.now().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_saved', ?)",
            (now_str,)
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('total_entries', ?)",
            (str(total),)
        )

        conn.commit()

        # Rebuild FTS index after bulk insert
        _rebuild_fts(conn)

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"Cache saved: {total:,} entries in {elapsed:.0f}ms (SQLite + FTS5)")

        if OLD_CACHE_FILE.exists():
            try:
                OLD_CACHE_FILE.unlink()
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Failed to save cache: {e}")


def load_cache(index: FileIndex) -> Optional[dict[str, tuple[int, int]]]:
    """Load the file index from the SQLite database."""
    if not DB_FILE.exists():
        return None

    # Check DB health before loading
    if not ensure_db_healthy():
        logger.warning("DB was corrupt and has been removed — will rebuild from scratch")
        return None

    start = time.perf_counter()
    usn_positions = {}

    try:
        conn = _get_connection()
        _init_schema(conn)

        row = conn.execute("SELECT value FROM meta WHERE key='version'").fetchone()
        if row:
            ver = int(row[0])
            if ver < DB_VERSION:
                logger.info(f"DB version {ver} < {DB_VERSION}, will upgrade on next save")
            elif ver > DB_VERSION:
                logger.warning(f"DB version {ver} > {DB_VERSION}, incompatible")
                return None

        drive_rows = conn.execute(
            "SELECT letter, flags, journal_id, next_usn FROM drives"
        ).fetchall()

        if not drive_rows:
            return None

        total_loaded = 0
        all_entries = []
        max_synthetic_frn = 0

        for drive, flags, journal_id, next_usn in drive_rows:
            usn_positions[drive] = (journal_id, next_usn)

            if flags & DRIVE_FLAG_WALKED:
                index._walked_drives.add(drive)

            drive_entries = {}
            drive_entries[NTFS_ROOT_FRN] = FileEntry(
                frn=NTFS_ROOT_FRN, parent_frn=0, name="",
                drive=drive, attributes=FILE_ATTRIBUTE_DIRECTORY,
            )

            # Use cursor iteration instead of fetchall() to avoid loading
            # all rows for a drive into memory at once
            cursor = conn.execute(
                "SELECT frn, parent_frn, name, path, attributes, size, "
                "date_modified_ms, date_created_ms "
                "FROM entries WHERE drive=?",
                (drive,)
            )
            drive_count = 0

            for frn, parent_frn, name, path, attrs, size, mtime_ms, ctime_ms in cursor:
                entry = FileEntry(
                    frn=frn, parent_frn=parent_frn, name=name,
                    drive=drive, attributes=attrs,
                )

                # Restore pre-resolved path
                if path:
                    entry._path = path

                if size or mtime_ms or ctime_ms:
                    entry.size = size
                    entry.date_modified = _ms_to_dt(mtime_ms)
                    entry.date_created = _ms_to_dt(ctime_ms)
                    entry._stat_loaded = True

                drive_entries[frn] = entry
                if name:
                    all_entries.append(entry)
                if frn > max_synthetic_frn:
                    max_synthetic_frn = frn
                drive_count += 1

            index._entries[drive] = drive_entries
            total_loaded += drive_count

        index._all_entries = all_entries

        if max_synthetic_frn >= index._SYNTHETIC_FRN_BASE:
            index._next_synthetic_frn = max_synthetic_frn + 1

        elapsed = (time.perf_counter() - start) * 1000
        logger.info(f"Cache loaded: {total_loaded:,} entries in {elapsed:.0f}ms (SQLite)")
        return usn_positions

    except Exception as e:
        logger.error(f"Failed to load cache: {e}")
        return None


# ── Legacy Incremental DB Operations (kept for backwards compat) ────

def db_insert_entry(entry: FileEntry, path: str):
    """Insert a single entry into the DB (for real-time USN updates)."""
    db_batch_apply(inserts=[(entry, path)], deletes=[], updates=[])


def db_delete_entry(drive: str, frn: int):
    """Delete a single entry from the DB."""
    db_batch_apply(inserts=[], deletes=[(drive, frn)], updates=[])


def db_update_entry(entry: FileEntry, path: str = ""):
    """Update an existing entry in the DB."""
    db_batch_apply(inserts=[], deletes=[], updates=[(entry, path)])


def db_update_usn_position(drive: str, journal_id: int, next_usn: int):
    """Update the USN journal position for a drive."""
    try:
        conn = _get_connection()
        conn.execute(
            "UPDATE drives SET journal_id=?, next_usn=? WHERE letter=?",
            (journal_id, next_usn, drive)
        )
        conn.commit()
    except Exception as e:
        logger.debug(f"db_update_usn_position failed: {e}")


# ── Database Search ──────────────────────────────────────

def db_search(query: str, match_path: bool = False,
              extensions: Optional[list[str]] = None,
              files_only: bool = False, folders_only: bool = False,
              size_min: int = 0, size_max: int = 0,
              date_mod_after_ms: int = 0, date_mod_before_ms: int = 0,
              date_create_after_ms: int = 0, date_create_before_ms: int = 0,
              exclude_paths: Optional[list[str]] = None,
              limit: int = 0, offset: int = 0,
              sort_column: str = 'date_modified_ms',
              sort_desc: bool = True) -> tuple[list[tuple], int]:
    """
    Search the database directly. Returns (rows, total_count).

    Each row is: (frn, drive, parent_frn, name, path, attributes, size,
                  date_modified_ms, date_created_ms)

    Returns total_count = -1 if count is not computed (for performance).
    """
    try:
        conn = _get_connection()
    except Exception:
        return [], 0

    conditions = []
    params = []

    # FTS5 search for name/path substring matching
    use_fts = False
    if query and _FTS5_AVAILABLE and _TRIGRAM_AVAILABLE and not any(c in query for c in '%_'):
        use_fts = True

    if query and not use_fts:
        if match_path:
            conditions.append("e.path LIKE ? COLLATE NOCASE")
        else:
            conditions.append("e.name LIKE ? COLLATE NOCASE")
        params.append(f"%{query}%")

    # Extension filter
    if extensions:
        placeholders = ','.join('?' * len(extensions))
        conditions.append(f"""
            CASE WHEN instr(e.name, '.') > 0
                 THEN lower(substr(e.name, length(e.name) - length(substr(e.name, instr(e.name, '.')+1)) + 1))
                 ELSE '' END IN ({placeholders})
        """)
        params.extend(ext.lower() for ext in extensions)

    # File/folder filter
    if files_only:
        conditions.append("NOT (e.attributes & 16)")  # FILE_ATTRIBUTE_DIRECTORY = 0x10
    if folders_only:
        conditions.append("(e.attributes & 16)")

    # Size filter
    if size_min > 0:
        conditions.append("e.size >= ?")
        params.append(size_min)
    if size_max > 0:
        conditions.append("e.size <= ?")
        params.append(size_max)

    # Date filters
    if date_mod_after_ms > 0:
        conditions.append("e.date_modified_ms >= ?")
        params.append(date_mod_after_ms)
    if date_mod_before_ms > 0:
        conditions.append("e.date_modified_ms <= ?")
        params.append(date_mod_before_ms)
    if date_create_after_ms > 0:
        conditions.append("e.date_created_ms >= ?")
        params.append(date_create_after_ms)
    if date_create_before_ms > 0:
        conditions.append("e.date_created_ms <= ?")
        params.append(date_create_before_ms)

    # Exclude paths
    if exclude_paths:
        for ep in exclude_paths:
            conditions.append("e.path NOT LIKE ? COLLATE NOCASE")
            params.append(f"%{ep}%")

    # Build query
    where_clause = " AND ".join(conditions) if conditions else "1=1"

    # Validate sort column
    valid_sorts = {
        'name': 'e.name COLLATE NOCASE',
        'path': 'e.path COLLATE NOCASE',
        'size': 'e.size',
        'date_modified_ms': 'e.date_modified_ms',
        'date_created_ms': 'e.date_created_ms',
        'attributes': 'e.attributes',
    }
    order_col = valid_sorts.get(sort_column, 'e.date_modified_ms')
    order_dir = 'DESC' if sort_desc else 'ASC'

    if use_fts:
        # FTS5 trigram search — join with entries table
        fts_col = 'path' if match_path else 'name'
        escaped_query = query.replace('"', '""')
        sql = f"""
            SELECT e.frn, e.drive, e.parent_frn, e.name, e.path,
                   e.attributes, e.size, e.date_modified_ms, e.date_created_ms
            FROM entries e
            INNER JOIN entries_fts ON entries_fts.rowid = e.rowid
            WHERE entries_fts.{fts_col} MATCH ?
        """
        fts_params = [f'"{escaped_query}"']

        if conditions:
            sql += " AND " + where_clause
            fts_params.extend(params)

        sql += f" ORDER BY {order_col} {order_dir}"

        if limit > 0:
            sql += f" LIMIT {limit}"
            if offset > 0:
                sql += f" OFFSET {offset}"

        try:
            rows = conn.execute(sql, fts_params).fetchall()
            return rows, -1
        except Exception:
            # FTS failed, fall back to LIKE
            use_fts = False
            if query:
                if match_path:
                    conditions.insert(0, "e.path LIKE ? COLLATE NOCASE")
                else:
                    conditions.insert(0, "e.name LIKE ? COLLATE NOCASE")
                params.insert(0, f"%{query}%")
                where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT e.frn, e.drive, e.parent_frn, e.name, e.path,
               e.attributes, e.size, e.date_modified_ms, e.date_created_ms
        FROM entries e
        WHERE {where_clause}
        ORDER BY {order_col} {order_dir}
    """

    if limit > 0:
        sql += f" LIMIT {limit}"
        if offset > 0:
            sql += f" OFFSET {offset}"

    try:
        rows = conn.execute(sql, params).fetchall()
        return rows, -1
    except Exception as e:
        logger.error(f"db_search failed: {e}")
        return [], 0


def db_count() -> int:
    """Get total number of entries in the database."""
    try:
        conn = _get_connection()
        row = conn.execute("SELECT COUNT(*) FROM entries").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def db_size_bytes() -> int:
    """Get the database file size in bytes."""
    try:
        return DB_FILE.stat().st_size if DB_FILE.exists() else 0
    except Exception:
        return 0


def cache_exists() -> bool:
    return DB_FILE.exists() or OLD_CACHE_FILE.exists()


def cache_age_seconds() -> float:
    if DB_FILE.exists():
        return time.time() - DB_FILE.stat().st_mtime
    if OLD_CACHE_FILE.exists():
        return time.time() - OLD_CACHE_FILE.stat().st_mtime
    return float('inf')


def close_all_connections():
    """Close thread-local connection. Call at shutdown to prevent leaks."""
    _close_connection()


def load_entries_from_cache() -> tuple[list, dict]:
    """
    Load entries directly from DB for CLI use (no FileIndex required).
    Returns (entries_list, drive_entries_dict) where:
      - entries_list: list of FileEntry objects
      - drive_entries_dict: dict of drive -> {frn -> FileEntry}
    Returns ([], {}) on failure.
    """
    if not DB_FILE.exists():
        return [], {}

    if not ensure_db_healthy():
        return [], {}

    try:
        conn = _get_connection()
        _init_schema(conn)

        drive_rows = conn.execute(
            "SELECT letter FROM drives"
        ).fetchall()

        if not drive_rows:
            return [], {}

        all_entries = []
        drive_entries = {}

        for (drive,) in drive_rows:
            d_entries = {}
            d_entries[NTFS_ROOT_FRN] = FileEntry(
                frn=NTFS_ROOT_FRN, parent_frn=0, name="",
                drive=drive, attributes=FILE_ATTRIBUTE_DIRECTORY,
            )

            # Use cursor iteration instead of fetchall()
            cursor = conn.execute(
                "SELECT frn, parent_frn, name, path, attributes, size, "
                "date_modified_ms, date_created_ms "
                "FROM entries WHERE drive=?",
                (drive,)
            )

            for frn, parent_frn, name, path, attrs, size, mtime_ms, ctime_ms in cursor:
                entry = FileEntry(
                    frn=frn, parent_frn=parent_frn, name=name,
                    drive=drive, attributes=attrs,
                )
                if path:
                    entry._path = path
                if size or mtime_ms or ctime_ms:
                    entry.size = size
                    entry.date_modified = _ms_to_dt(mtime_ms)
                    entry.date_created = _ms_to_dt(ctime_ms)
                    entry._stat_loaded = True

                d_entries[frn] = entry
                if name:
                    all_entries.append(entry)

            drive_entries[drive] = d_entries

        logger.info(f"load_entries_from_cache: {len(all_entries):,} entries loaded")
        return all_entries, drive_entries

    except Exception as e:
        logger.error(f"load_entries_from_cache failed: {e}")
        return [], {}
