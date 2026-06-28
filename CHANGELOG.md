# Changelog

All notable changes to QuickFind will be documented in this file.

## [v0.8.7] - 2026-06-28

- Locked the tested top-level runtime, build, and test dependencies in `requirements.txt`.
- Added build/runtime matrix reporting to `build.py` for Python, SQLite, PyQt6, PyInstaller, pywin32, and content/archive adapters.
- Removed build-time PyInstaller auto-install and documented the supported runtime matrix in README.
- Added build metadata tests and expanded the passing suite to 205 tests.

## [v0.8.6] - 2026-06-28

- Hardened Everything filter/bookmark imports with CSV header/row validation and explicit status-bar failure feedback.
- Replaced direct imported JSON writes with validated atomic temp-and-replace saves that leave existing files intact on malformed input.
- Added importer regression tests and expanded the passing suite to 203 tests.

## [v0.8.5] - 2026-06-28

- Added cancellable background content indexing jobs with per-root and per-extension settings.
- Added content cache quota enforcement, max-file-size controls, cache stats, and adapter diagnostics/failure counts.
- Added content-index status UI and expanded the passing suite to 197 tests.

## [v0.8.4] - 2026-06-28

- Hardened remote search authentication by removing query-string token acceptance.
- Added Bearer-token API auth plus same-origin browser session cookies for the web UI.
- Removed wildcard CORS from authenticated search API responses and expanded the passing suite to 192 tests.

## [v0.8.3] - 2026-06-28

- Added a SQLite/FTS5 runtime gate that disables FTS5 on SQLite versions below the patched 3.53.2 minimum.
- Logged SQLite runtime gate status during app startup and PyInstaller builds.
- Added SQLite compatibility tests and expanded the passing suite to 187 tests.

## [v0.8.2] - 2026-06-28

- Removed the runtime PyQt6 auto-install path from app startup.
- Added explicit source-run and frozen-build dependency errors instead of invoking pip from the application.
- Added startup dependency tests and expanded the passing suite to 183 tests.

## [v0.8.1] - 2026-06-28

- Added Windows service mode commands for installing, starting, stopping, removing, and running the background index service.
- Added a localhost JSON status socket so the GUI can report service indexing state and entry count.
- Added service IPC/install tests and expanded the passing suite to 179 tests.

## [v0.8.0] - 2026-06-28

- Replaced synchronous text-only `content:` reads with a content adapter pipeline for TXT, PDF, DOCX, and PPTX extraction.
- Added an on-disk SQLite content cache with FTS5 indexing for faster repeated `content:` searches.
- Preview pane text results now show matched-line context for active `content:` queries.
- Added content adapter/cache tests and expanded the passing suite to 175 tests.

## [v0.7.9] - 2026-06-28

- Added opt-in `archive:` search for filenames inside ZIP and 7z archives, returning virtual paths like `archive.zip\folder\file.txt`.
- Added `py7zr` packaging support and archive-search tests, expanding the passing suite to 169 tests.

## [v0.7.8] - 2026-06-27

- Bounded the native file icon cache with least-recently-used eviction to prevent unbounded growth while browsing many file types.
- Added results-view icon cache tests and expanded the passing suite to 163 tests.

## [v0.7.7] - 2026-06-27

- Implemented the `dupe:` search modifier for duplicate filename detection in in-memory searches.
- `dupe:` now respects normal query terms, extension filters, and applies max-result limits after duplicate grouping.
- Added duplicate-search tests and expanded the passing suite to 161 tests.

## [v0.7.6] - 2026-06-27

- Added settings sanitization for invalid ports, numeric ranges, blank bind addresses, missing TLS files, and missing EFU file lists.
- Dialog apply/export now warns and keeps invalid settings from silently reaching startup/server code.
- Added settings validation tests and expanded the passing suite to 157 tests.

## [v0.7.5] - 2026-06-27

- Added a persistent status-bar badge when QuickFind falls back to non-admin `os.scandir` indexing.
- Reset index mode at the start of each full scan so the fallback badge clears after a later successful MFT scan.
- Added index-mode indicator tests and expanded the passing suite to 152 tests.

## [v0.7.4] - 2026-06-27

- Disabled `SeBackupPrivilege` after direct MFT scans using a reference-counted guard that is safe for parallel drive indexing.
- Added NTFS privilege lifecycle tests and expanded the passing suite to 148 tests.

## [v0.7.3] - 2026-06-16

- Added optional HTTPS/TLS support for the remote search server with configurable certificate and private key paths.
- Fixed remote server settings so enabling the server from the UI starts/stops the background server and reports the active URL.
- Centralized application version metadata in `core.version` so runtime, build, and UI version strings cannot drift.
- Added server/version tests and expanded the passing suite to 145 tests.

## [v0.7.2] - 2026-06-15

### Premium polish pass
- Theme: Added border-radius to inputs, combos, spinboxes, text edits (was flat 0px — felt dated)
- Theme: Rounded menu items and dropdown popups with proper spacing for modern feel
- Theme: Added focus states to buttons, combos, spinboxes, and text edits (accessibility)
- Theme: Transparent scrollbar tracks instead of mantle-colored (cleaner)
- Theme: Splitter handle hover state for better discoverability
- Theme: Improved padding and spacing throughout — menu items, buttons, tabs, headers
- Theme: Added hover:!selected state to tabs for visual hierarchy
- Theme: Rounded tab corners (border-top-left/right-radius)
- Theme: Dialog button min-width for consistent button sizing
- Theme: Selected+hover state for table items to avoid flash on hover
- Launcher: Drop shadow and refined container border for depth and presence
- Launcher: Result count + keyboard hints shown below results ("10+ results · Enter to open · Esc to close")
- Launcher: Empty state message ("No files found") instead of just hiding results
- Launcher: Refined spacing, border-radius, and padding throughout
- Launcher: Slightly narrower (640px) with better vertical position (28% vs 25%)
- Main window: Search row height increased from 26px to 30px for less cramped feel
- Main window: Search input and filter combo height 24px (was 22px)
- Main window: Improved tab bar styling — accent underline on selected, rounded close button hover
- Main window: Status bar result count uses font-weight 500 for better visual hierarchy
- Main window: Consistent status bar label padding (8px)
- Preview pane: File info uses label-above-value layout instead of "Key: Value" pattern for scannability
- Preview pane: Header styling refined — uppercase feel with letter-spacing
- Preview pane: Empty state has more padding for breathing room
- Preview pane: Attributes only shown when non-empty (no blank "Attributes:" line)
- HTTP server: Sticky header that stays visible during scroll
- HTTP server: "Searching…" loading state in result count while typing
- HTTP server: Error handling for failed fetch requests
- HTTP server: Proper empty state message ("Type a query to search your files")
- HTTP server: Tabular-nums for size and date columns for perfect alignment
- HTTP server: ARIA label on search input
- HTTP server: Refined typography — uppercase table headers, proper letter-spacing
- Microcopy: Ellipsis character (…) replaces three dots (...) in placeholder text

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
- Fixed: Date filters (`dm:today`, `dc:>2024-01-01`) now exclude entries with no date (previously passed through)
- Fixed: Size filters (`size:>1mb`) now work in in-memory search path (previously only worked via DB)
- Fixed: Deferred path resolution queue flushed on shutdown (entries queued right before exit now resolve)

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
