# Changelog

All notable changes to QuickFind will be documented in this file.

## [v0.7.2] - 2026-06-15

### Audit fixes (engineering, security, reliability)
- Fixed: Invalid regex pattern in `regex:` modifier no longer crashes (returns no-match instead of None dereference)
- Fixed: `len:` modifier with non-numeric values no longer raises ValueError
- Fixed: Version strings synchronized across quickfind.py, main_window.py, build.py (were diverged)
- Fixed: FTS rebuild counter (`_fts_pending_changes`) now thread-safe with dedicated lock
- Fixed: HTTP server `max` parameter parsing handles non-integer input gracefully
- Fixed: Rate limiter no longer leaks memory for expired IPs (cleaned up defaultdict)
- Fixed: Hidden paths JSON save now atomic (write-to-tmp + rename) to prevent corruption on crash
- Fixed: EFU file entries now set `_stat_loaded` flag so stats survive cache round-trip
- Fixed: EFU FILETIME epoch constant deduplicated into module-level `_FILETIME_EPOCH_DIFF`
- Fixed: CLI `es.py` now closes DB connections on error via try/finally
- Fixed: Launcher popup Up-arrow returns focus to search input from results list
- Security: Removed `--break-system-packages` from pip install commands (bootstrap and build)
- Added: Launcher popup accessibility labels on search input
- Fixed: `content:` search modifier now actually filters by file content (was parsed but ignored)
- Fixed: All JSON config saves (settings, bookmarks, filters) now atomic (tmp+rename)
- Fixed: SHFileOperationW struct moved to module level (no longer recreated per delete call)
- Fixed: SHFileOperationW return code now logged on failure
- Fixed: Image preview rejects files >50MB before loading (prevents memory exhaustion)
- Fixed: Launcher popup Up-arrow key navigates back to search from results

### Previous changes
- Fixed: `recycle_file` import crash — Delete key handler referenced wrong function name
- Fixed: Startup crash on non-admin — `Path` used before import, bogus `setWindowIcon` on Win32 HWND
- Fixed: `requirements.txt` now pip-installable (removed internal module names)
- Security: HTTP server uses `html.escape()` for all user-derived content, adds CSP + X-Content-Type-Options headers
- Fixed: Log rotation — `RotatingFileHandler` with 5MB max and 3 backups replaces unbounded `FileHandler`
- Added: HTTP server per-IP rate limiting (60 req/min, 429 on excess)
- Fixed: ctypes Win32 safety — `WinDLL(use_last_error=True)`, complete `argtypes` for all functions, `ctypes.get_last_error()` everywhere
- Perf: FTS5 rebuilds now deferred until 1000 cumulative changes (was rebuilding on every USN batch)
- Added: Smart case sensitivity — query "Foo" auto-switches to case-sensitive, "foo" stays insensitive; explicit `case:`/`nocase:` overrides
- Added: Test suite — 108 tests covering search parsing, size/date helpers, MFT record parsing, USN records, cache helpers, smart case
- Fixed: File deletion now runs in background thread (no longer blocks UI during large deletes)
- Added: `.quickfindignore` file support — place in any directory to exclude matching files/folders from indexing (glob patterns, like fd/ripgrep)
- Added: Fuzzy matching via `fuzzy:` modifier — subsequence matching so "qickfind" matches "QuickFind"
- Added: Usage-based result ranking — opening files via QuickFind tracks open counts; sort by "Relevance" to surface frequently used files
- Added: Per-drive rescan intervals for non-NTFS drives — configure via `_drive_rescan_intervals` dict (e.g., 30s for SSD, 300s for NAS)
- Perf: Search available after first drive finishes indexing — flat list rebuilt incrementally per drive instead of waiting for all drives
- Added: Launcher popup mode — Ctrl+Shift+F shows a floating search bar (Wox/Flow Launcher style); results appear inline, Enter opens and dismisses
- Added: Accessibility — `accessibleName`/`accessibleDescription` on search input, filter combo, results table, result count, tab widget

## [v0.7.1]

- Fixed: Fix memory leaks during large drive scans
- Changed: Update README.md
- v0.7.1: Reorder menu bar, add filter/bookmark import/export
- Fixed: Fix launch crashes: _result_count_label init order, column visibility key mapping
- QuickFind v0.7.0 — bug fixes, dark title bar, regex validation, tray progress
- QuickFind v0.6.0 — 20 improvements: ReFS/Dev Drive, USN V3/V4, batch DB writes, non-admin fallback, search history, result highlighting, column filters, keyboard nav, token auth, build script
- Initial commit — QuickFind v0.1.0
