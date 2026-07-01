# Changelog

All notable changes to QuickFind will be documented in this file.

## [v0.8.56] - 2026-07-01

- Fixed active search filter silently overwriting user's explicit `ext:` modifier; user's query-level extension now takes precedence over the filter bar.
- Removed ambiguous `d/m/Y` date format from date modifier parsing; use ISO `YYYY-MM-DD` or US `m/d/Y` to avoid silent misinterpretation.
- Added 2 regression tests for filter/modifier precedence, expanding the suite to 526 tests.

## [v0.8.55] - 2026-07-01

- Fixed `ww:` modifier alias collision: `ww:` now correctly enables whole-word mode (matching Everything convention), `wc:` enables wildcards.
- Fixed `thisweek`/`lastweek` date shortcuts not normalized to midnight, causing files modified earlier the same day to be excluded.
- Fixed `size:` with empty value silently filtering to 0-byte files; empty size modifier is now treated as a no-op.
- Fixed query chip validator rejecting valid `size:1mb..10mb` range syntax; regex now accepts range and single-operator forms.
- Fixed export size formatting missing GB/TB tiers, showing unwieldy values like `10737.4 MB` for large files.
- Fixed cache purge functions not rolling back on failure, risking partial deletes committed by later operations.
- Fixed command injection in context menu terminal openers by using proper argument separation instead of string interpolation.
- Fixed ACL `path_within_roots` using brittle string prefix check; now uses `PurePath.relative_to` for safe, case-insensitive path containment.
- Added `wc` to BUILTIN_MODIFIERS for the new wildcards shortcut, preventing it from being captured by plugin registration.
- Added 8 regression tests for modifier aliases, date normalization, size parsing, and chip validation, expanding the suite to 524 tests.
- Fixed CSRF bypass where POST to `/auth` without Origin/Referer headers was accepted; now requires at least one same-origin header.
- Fixed API search `count` field reporting more results than the payload actually contains due to a hard 1000-item cap.
- Fixed plugin loader path containment check using brittle string prefix; now uses `Path.relative_to` for case-insensitive, symlink-safe comparison.
- Fixed settings file I/O not specifying UTF-8 encoding, causing potential data corruption on non-UTF-8 system locales.
- Fixed `group_by_size` treating all 0-byte files as duplicates, producing false-positive groups for empty files like `.gitkeep` and `__init__.py`.
- Fixed dep_audit silently dropping medium/low severity unwaived advisories from the report; they now appear in a separate `unwaived_info` section.
- Removed dead `_build_result_cards` method from HTTP server handler.
- Added 3 regression tests for CSRF, count/payload mismatch, and 0-byte duplicate exclusion, expanding the suite to 519 tests.

## [v0.8.54] - 2026-07-01

- Title bar now switches between dark and light mode when the theme changes, fixing dark title bar on Latte (light) theme.
- Help docs HTML now uses active theme palette colors instead of hardcoded Mocha hex values.
- HTML result export now accepts a theme dict parameter; GUI export passes the active palette for correct Latte/Frappe/Macchiato styling.
- Added `is_dark_theme()` helper to theme module for runtime dark/light detection.
- Plugin loader now requires SHA-256 hash pinning via `allowed_hashes.json` for entry points with code execution; unpinned plugins are blocked by default.
- PWA manifest now uses an inline SVG search icon served at `/icon.svg`, replacing the broken PNG references that returned 404.
- Added 8 tests for theme-aware rendering, hash verification, and PWA icon serving, expanding the suite to 516 tests.

## [v0.8.53] - 2026-07-01

- Fixed path traversal in plugin loader: entry points that escape the plugin directory are now blocked.
- Fixed ACL token comparison to use constant-time `secrets.compare_digest` against timing side-channels.
- Fixed ACL path check to resolve symlinks/junctions via `realpath` instead of `abspath`.
- Fixed HTML export table column misalignment when only some rows have content snippets.
- Fixed content refresh queue counting empty extractions as processed instead of failed.
- Fixed portable cache compatibility to reject existing unstamped directories from synced profiles.
- Fixed `validate_chip` rejecting valueless `broken:` and `dupe:` modifiers that are valid in the search engine.
- Fixed benchmark generating synthetic entries twice wastefully.
- Fixed `_default_recycle` docstring claiming an `os.remove` fallback that didn't exist.
- Fixed machine identity hash to include MAC address for stronger cross-machine uniqueness.
- Removed unused `json` import from portable module.
- Fixed dep_audit severity extraction to parse PyPI `details[].severity` field instead of relying only on alias strings.
- Fixed `_format_size` treating 0 bytes as empty string instead of "0 B".
- Fixed service worker intercepting API calls with HTML fallback, breaking AJAX search when offline.
- Fixed `purge_content_cache_by_root` SQL LIKE pattern matching paths with `%` or `_` characters.
- Fixed settings dialog purge confirmation being immediately overwritten by cache status refresh.
- Fixed stale ACCENT color binding after theme switch: filters, tab bar, and tray icon now read from MOCHA dict at render time.
- Fixed THEME_PACKS storing non-mocha palettes by reference instead of defensive copy, preventing mutation corruption.
- Fixed SQLite connection leak on health-check failure and PRAGMA initialization failure in `_get_connection`.
- Fixed worker isolation catching `BaseException` (swallowing `SystemExit`/`KeyboardInterrupt`) — narrowed to `Exception`.
- Removed unused ACCENT imports from bookmarks, launcher_popup modules.
- Fixed rate limiter unbounded memory growth for stale IP entries by adding periodic cleanup.
- Fixed `format_size` in results_view treating 0-byte files as empty string instead of "0 B".
- Added missing PyInstaller hidden imports for new modules (dep_audit, duplicate_review, plugin_loader, portable, result_export, refresh_queue, acl, query_chips).
- Added 8 regression tests for the above fixes, expanding the suite to 508 tests.

## [v0.8.52] - 2026-07-01

- Added dependency advisory, license, and SBOM release gate via `python build.py --dep-audit` with optional `--sbom` CycloneDX JSON output.
- Advisory checks fail on unwaived high/critical vulnerabilities; waivers support expiry dates via `dep_waivers.json`.
- Added privacy-preserving remote access audit log for auth failures, rate limits, searches, and denied path events with hashed client IPs and query hashes.
- Added content-cache privacy controls with purge-all and purge-by-root actions in Settings, exposing cache path, size, and entry count.
- Purge removes both content_cache rows and FTS entries transactionally; tests prove sensitive text is no longer searchable after purge.
- Expanded Spanish localization to cover settings, diagnostics, help, and result text; added `all_keys()`, `missing_keys()`, pseudo-locale generator, and fallback tests.
- Added repeatable benchmark harness (`python -m tools.benchmark`) with synthetic tree generation, cold/warm search timings, and JSON/CSV export.
- Added report-grade result export from File > Export Results as Report with CSV, JSON, and HTML formats including query metadata, content snippets, and XSS-safe HTML escaping.
- Added visual query builder with modifier chip extraction, composition, validation, and round-trip to raw query strings for all built-in modifiers.
- Added plugin discovery from `~/.quickfind/plugins/` with manifest validation, Python entry-point loading, disabled/quarantine support, and plugin summary for settings/help.
- Added incremental content-cache refresh queue for file-change events with bounded capacity, batch processing, rename/delete handling, and queue diagnostics.
- Added duplicate review workflow with name/size grouping, configurable keep rules, remediation preview, and safe Recycle Bin batch actions with skip/fail tracking.
- Added PWA manifest, service worker with offline shell, and theme-color meta for installable mobile-ready remote search UI.
- Added portable/cloud-profile mode with machine-scoped cache identity stamps, `.quickfind-portable` marker detection, and profile diagnostics.
- Added shared read-only search server prototype with per-token ACL boundaries, path filtering, config validation, and denied-path tracking (disabled by default).
- Added 137 tests across all new features, expanding the passing suite to 500 tests.

## [v0.8.51] - 2026-07-01

- Added status-bar, tray, log, and recovery-hint feedback for Delete-to-Recycle actions from both context menus and keyboard Delete.
- Removed successfully recycled files from visible result rows across open tabs so the current search view updates immediately.
- Added recycle-result and feedback-message coverage, expanding the passing suite to 363 tests.

## [v0.8.50] - 2026-07-01

- Added an optional Windows IFilter/property-handler content adapter through Windows Search COM APIs for installed legacy Office, PDF, email, and metadata extractors.
- Added fallback extraction across adapters for the same extension and surfaced per-extractor content-cache counts/bytes in diagnostics.
- Added fake Windows Search COM adapter coverage, expanding the passing suite to 359 tests.

## [v0.8.49] - 2026-07-01

- Added rendered/offscreen PyQt accessibility smoke tests for the main search flow, settings, results, preview, and diagnostics surfaces.
- Added accessible names and descriptions for diagnostics tables and action buttons.
- Fixed the test PyQt fallback loader so real Qt submodules are used when available, expanding the passing suite to 357 tests.

## [v0.8.48] - 2026-07-01

- Added schema-versioned settings migrations with legacy-profile upgrade, validation, and future-version rejection.
- Added automatic settings backups before persisted profile replacement and rollback behavior for invalid imports.
- Added settings migration coverage, expanding the passing suite to 353 tests.

## [v0.8.47] - 2026-07-01

- Added a redacted diagnostics support bundle export from Tools > Index Diagnostics with runtime, cache, drive, service, content-adapter, settings, and log-tail data.
- Reused the runtime matrix for support diagnostics so support bundles and release checks report the same dependency fingerprints.
- Added support bundle redaction coverage, expanding the passing suite to 347 tests.

## [v0.8.46] - 2026-07-01

- Hardened remote browser authentication with `Secure` HTTPS session cookies and same-origin Origin/Referer checks on `/auth`.
- Added no-store cache and no-referrer headers to remote responses so authenticated search pages and API payloads are not retained by the browser.
- Added remote auth hardening coverage, expanding the passing suite to 343 tests.

## [v0.8.45] - 2026-07-01

- Persisted live USN journal checkpoints after successful monitor batches so restarts do not replay already-applied journal records.
- Kept checkpoint writes behind successful entry batch persistence and added regression coverage for failed DB batches.
- Added USN checkpoint durability coverage, expanding the passing suite to 339 tests.

## [v0.8.44] - 2026-07-01

- Added a local `build.py --release-check` gate for version consistency, MSIX hash/signature status, App Installer feed URLs, winget metadata, and GitHub release asset reachability.
- Hardened `build.py --clean` so read-only artifacts are retried and locked build outputs fail with a clear close-and-retry message instead of a raw traceback.
- Added release-check and locked-clean coverage, expanding the passing suite to 337 tests.

## [v0.8.43] - 2026-07-01

- Added process-isolated worker timeouts for content extraction and archive member probing so stuck parsers fail closed instead of blocking indexing or search.
- Routed background content indexing and cache-miss `content:` searches through the sandboxed extractor while preserving adapter failure diagnostics.
- Added worker timeout and parser-sandbox coverage, expanding the passing suite to 333 tests.

## [v0.8.42] - 2026-06-29

- Added a bundled offline Help menu dialog with search syntax, workflow, and troubleshooting cheat sheets.
- Kept the offline help self-contained for no-network use and added an assistive label for screen readers.
- Added offline help content coverage, expanding the passing suite to 329 tests.

## [v0.8.41] - 2026-06-29

- Added narrator-friendly labels and descriptions for settings controls, result view modes, preview panes, and status surfaces.
- Added explicit keyboard traversal from filter controls to workspace roots, search input, active result tabs, and results.
- Added accessibility helper coverage, expanding the passing suite to 327 tests.

## [v0.8.40] - 2026-06-29

- Added runtime UI localization with English and Spanish language packs for the main menu, search shell, and quick-preview status.
- Persisted the selected language in settings, validated unknown language codes, and applied language state at startup and live settings changes.
- Added localization and language validation coverage, expanding the passing suite to 325 tests.

## [v0.8.39] - 2026-06-29

- Added selectable theme packs for Catppuccin Mocha, Macchiato, Frappe, and Latte.
- Persisted the selected theme in settings and applied it during startup and direct main-window construction.
- Added theme switching and validation coverage, expanding the passing suite to 320 tests.

## [v0.8.38] - 2026-06-29

- Added a programmatic search modifier plugin API with registration, aliases, parser callbacks, and per-entry predicates.
- Routed custom modifier queries through in-memory search so plugin predicates cannot be incorrectly delegated to SQLite.
- Added plugin registry, parser, and search predicate coverage, expanding the passing suite to 316 tests.

## [v0.8.37] - 2026-06-29

- Added a floating quick-preview popover for the selected result, using Space from details, columns, or thumbnail result views.
- Reused the existing async preview loaders in the popover and synced visible quick previews as selection changes.
- Added preview geometry and thumbnail selection coverage, expanding the passing suite to 310 tests.

## [v0.8.36] - 2026-06-29

- Added MSIX packaging with full-trust shell integration, `quickfind://` protocol registration, and `quickfind.exe` app execution alias.
- Added App Installer update-feed generation and winget manifests wired to the packaged MSIX SHA-256 hash.
- Added packaging manifest coverage, expanding the passing suite to 308 tests.

## [v0.8.35] - 2026-06-29

- Added a platform engine boundary that keeps Windows on MFT/USN while routing Linux/macOS through POSIX root indexing.
- Added Watchdog-backed native monitoring for Linux inotify and macOS FSEvents, plus a macOS Spotlight fallback helper.
- Made NTFS and tray hotkey imports safe on non-Windows platforms, and expanded cross-platform coverage to 304 tests.

## [v0.8.34] - 2026-06-29

- Added authenticated `/api/docs` and `/openapi.json` endpoints for the remote search server.
- Extended `/api/search` with structured JSON result metadata while preserving the web UI card payload.
- Added OpenAPI, docs-page, and API bounds coverage, expanding the passing suite to 300 tests.

## [v0.8.33] - 2026-06-29

- Reworked the remote read-only web UI from a table into responsive result cards.
- Added remote web filters for all/files/folders and maximum result count while keeping search read-only.
- Added remote card rendering and filter coverage, expanding the passing suite to 297 tests.

## [v0.8.32] - 2026-06-29

- Added HTTP Basic authentication for remote search, using the existing auth token as the Basic password.
- Added a `WWW-Authenticate` challenge for unauthorized API responses when remote auth is enabled.
- Added Basic auth acceptance/rejection and challenge-header coverage, expanding the passing suite to 294 tests.

## [v0.8.31] - 2026-06-29

- Added a Finder-style Columns results view that splits paths into root/folder/item segments for fast path scanning.
- Added a selectable breadcrumb header that tracks the currently selected result path across result views.
- Added path-segment and column-model coverage, expanding the passing suite to 291 tests.

## [v0.8.30] - 2026-06-29

- Added a result context-menu Open With submenu for VS Code, VSCodium, Notepad++, and Obsidian when installed.
- Added executable discovery across PATH and common Windows install locations with launch status feedback.
- Added Open With discovery/command coverage, expanding the passing suite to 289 tests.

## [v0.8.29] - 2026-06-29

- Added an inline unified-diff dialog for comparing exactly two selected text files from result context menus.
- Added bounded text reads and binary-file rejection for in-app comparisons.
- Added diff helper and context-menu coverage, expanding the passing suite to 287 tests.

## [v0.8.28] - 2026-06-29

- Added bookmark workspaces with semicolon-separated root sets that constrain searches across multiple roots.
- Made workspace roots independent per search tab and restored them when activating saved bookmarks.
- Added workspace root parsing/filtering and bookmark persistence coverage, expanding the passing suite to 283 tests.

## [v0.8.27] - 2026-06-29

- Made search tabs keep independent query, filter, and match-option state.
- Bound background search results to the tab that launched the worker so late completions cannot overwrite the active tab.
- Added a keyboard-navigable tab switcher dialog from the File menu.

## [v0.8.26] - 2026-06-29

- Added `git:dirty` search filtering for files inside Git worktrees with non-empty `git status --porcelain` output.
- Cached Git repo-root discovery and dirty status per search engine to avoid per-file shell-outs.
- Added Git dirty parser/search coverage and expanded the passing suite to 278 tests.

## [v0.8.25] - 2026-06-29

- Added `broken:link` and `broken:shortcut` search predicates for broken reparse points and `.lnk` files with missing targets.
- Added Windows Shell shortcut target resolution with safe fallback when COM resolution is unavailable.
- Added broken target parser/search coverage and expanded the passing suite to 276 tests.

## [v0.8.24] - 2026-06-29

- Added `duplicate:hash` / `dupe:hash` search mode for SHA-256 content duplicate detection after normal filters.
- Preserved existing filename duplicate behavior for `dupe:` and `dupe:name`.
- Added hash duplicate coverage and expanded the passing suite to 273 tests.

## [v0.8.23] - 2026-06-29

- Added nested boolean query parsing with parentheses and NOT > implicit AND > OR precedence.
- Routed grouped `!()` expressions through the boolean matcher instead of the legacy flat exclude path.
- Added boolean parser/search coverage and expanded the passing suite to 271 tests.

## [v0.8.22] - 2026-06-29

- Added saved query slots so bookmark names or explicit slots expand from `@slot` aliases in GUI searches and `es.py`.
- Added nested slot expansion with missing-slot passthrough and cycle protection.
- Added query-slot parser/search/bookmark coverage and expanded the passing suite to 267 tests.

## [v0.8.21] - 2026-06-29

- Highlighted matched `content:` preview context lines with full-width accent styling.
- Added preview helper coverage and expanded the passing suite to 259 tests.

## [v0.8.20] - 2026-06-29

- Added optional Tesseract OCR fallback for PDF pages where `pdfplumber` extracts no text.
- Surfaced OCR adapter availability in content adapter diagnostics without making OCR a required dependency.
- Added OCR fallback coverage and expanded the passing suite to 257 tests.

## [v0.8.19] - 2026-06-29

- Added EML content extraction for message headers and text/plain or HTML bodies.
- Expanded source-code extraction coverage through the plain-text adapter for modern web and language extensions.
- Added EML/source-code adapter coverage and expanded the passing suite to 256 tests.

## [v0.8.18] - 2026-06-29

- Added an external EFU refresh scheduler with a configurable interval in File Lists settings.
- Isolated EFU imports into stable synthetic sources so scheduled refreshes replace stale rows cleanly.
- Added EFU refresh/source-key coverage and expanded the passing suite to 254 tests.

## [v0.8.17] - 2026-06-29

- Added SMB/UNC network-share indexing with stable synthetic index sources.
- Added optional Windows Credential Manager storage for SMB credentials without writing passwords to settings JSON.
- Added UNC/settings/indexing coverage and expanded the passing suite to 252 tests.

## [v0.8.16] - 2026-06-29

- Added persisted global exclude rules for glob, regex, and NTFS attribute-mask filters.
- Wired exclude rules into settings, index rebuilds, directory-walk traversal skips, and flat-result filtering.
- Added exclude-rule validation/indexing coverage and expanded the passing suite to 246 tests.

## [v0.8.15] - 2026-06-29

- Added reparse tag and NTFS extended-attribute metadata to `FileEntry` and cache records.
- Surfaced reparse tags and extended-attribute presence in result tooltips, attribute codes, and preview info.
- Added metadata persistence/formatting coverage and expanded the passing suite to 238 tests.

## [v0.8.14] - 2026-06-29

- Added a persisted index case mode with smart, case-insensitive, and case-sensitive baseline matching.
- Kept `case:` and `nocase:` query modifiers as explicit overrides of the selected mode.
- Added parser/settings validation coverage and expanded the passing suite to 233 tests.

## [v0.8.13] - 2026-06-29

- Added an opt-in symbolic link and junction traversal setting for directory-walk indexing.
- Added visited-target loop protection so followed links cannot recurse into already indexed directories.
- Re-index automatically when the link traversal setting changes and expanded the passing suite to 229 tests.

## [v0.8.12] - 2026-06-29

- Added an opt-in Open/Save dialog Quick Switch prototype for sending selected folders to the active common file dialog.
- Wired Quick Switch through launcher activation and the result context menu without changing normal open behavior when disabled.
- Added dialog-switch helper/context-menu tests and expanded the passing suite to 226 tests.

## [v0.8.11] - 2026-06-29

- Added online/offline/stale drive state tracking for cached and indexed drives.
- Preserved cached removable-drive results when a drive disappears, with status-bar stale badges and per-drive refresh in diagnostics.
- Added a configurable startup drive delay for late-mounted removable or virtual drives.
- Added stale-drive policy regression tests and expanded the passing suite to 222 tests.

## [v0.8.10] - 2026-06-29

- Added ranked content-cache hits with snippets for cached `content:` searches.
- Exposed cached content snippets in result tooltips without loading full indexed text into table rows.
- Added content-search ranking/snippet regression tests and expanded the passing suite to 217 tests.

## [v0.8.9] - 2026-06-28

- Persisted ZIP/7z archive member metadata in SQLite for faster repeated `archive:` searches.
- Added archive cache invalidation by archive size and modified time while preserving stable virtual member paths.
- Added archive cache reuse/invalidation tests and expanded the passing suite to 214 tests.

## [v0.8.8] - 2026-06-28

- Added an Index Diagnostics dialog with cache integrity, per-drive mode/USN state, service heartbeat, content cache size, and recovery buttons.
- Added structured index, cache, and service diagnostic summaries for UI and tests.
- Tracked index source transitions for cache load, USN catchup, full scans, fallback scans, and EFU imports.
- Added diagnostics regression tests and expanded the passing suite to 212 tests.

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
