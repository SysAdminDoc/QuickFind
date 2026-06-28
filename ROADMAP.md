# QuickFind Roadmap

NTFS-MFT-backed instant file search (PyQt6 + SQLite FTS5). Voidtools Everything alternative with CLI, HTTP server, and Catppuccin theme. Roadmap strengthens content search, network share indexing, and cross-platform reach.

## Planned Features

### Indexing
- Symbolic link and junction follow toggle (with loop protection)
- Case-sensitive vs case-insensitive index modes
- Extended attribute + NTFS reparse tag surface
- Exclude rules UI (regex + glob + attribute)
- Network share indexer with credential vault (SMB read-only)
- External EFU refresh scheduler

### Content Search
- Content indexing (pdfplumber / python-docx / python-pptx) with optional on-disk FTS5 index
- PDF / Office / EML / source-code extraction
- OCR'd PDF fallback (Tesseract) optional
- Highlight matched line in preview with context ±3 lines

### Search Syntax
- Saved queries with named slots (`@logs`, `@recent-py`)
- Nested parens + operator precedence
- `duplicate:hash` (content hash dedupe, not just filename)
- `broken:link` / `broken:shortcut` finders
- `git:dirty` (is in a dirty git repo?)

### UX
- Tabs with independent search state + keyboard switcher
- Multi-root bookmark workspaces
- Diff compare two selected files inline
- Quick "open with" submenu (VS Code, VSCodium, Notepad++, Obsidian)
- Finder-style column layout + breadcrumb header

### Remote
- HTTPS + basic auth (current: HTTP + token)
- Read-only web UI polish (result card layout, filters)
- REST API docs + OpenAPI export

### Cross-platform
- Linux: inotify-based indexer + SQLite cache
- macOS: FSEvents + Spotlight fallback
- Common UI layer already PyQt6 — branch engines by OS

### Packaging
- MSIX package (shell integration + auto-update)
- winget manifest

## Competitive Research
- **Voidtools Everything** — gold standard; closed source, Windows only, no content search. Lesson: content + remote + Linux are the deficits QuickFind should own.
- **fd + ripgrep** — CLI stars. Lesson: keep CLI fast, ensure `es.py` behaves predictably in scripts.
- **Recoll / DocFetcher** — content indexers. Lesson: don't rebuild Tika; borrow it.
- **Windows Search** — built-in, slow on big MFT. Lesson: explicit "beats Windows Search" metric in README (already present in feeling, make it a benchmark).

## Nice-to-Haves
- Quicklook-style preview popover on spacebar
- Plugin API (custom modifier parsers)
- Theme packs (not just Mocha)
- Localization
- Accessibility: full keyboard flow, narrator labels
- Offline docs / cheat sheet accessible from Help menu

## Research-Driven Additions

### P0 - Security and Release Blockers

- [ ] P0 - Remove runtime dependency installation from app startup
  Why: `quickfind.py` shells out to `sys.executable -m pip install PyQt6` during startup, which is not normal app behavior and is unsafe in frozen builds.
  Evidence: `quickfind.py:22-36`; PyInstaller bundles app dependencies into distributables.
  Touches: `quickfind.py`, `build.py`, `requirements.txt`, `README.md`, tests
  Acceptance: app startup never invokes pip; missing dependencies fail with a clear source-run error; frozen build path is guarded; tests cover source and frozen-flag behavior.
  Complexity: M

- [ ] P0 - Gate SQLite FTS5 on patched runtime versions
  Why: QuickFind depends on SQLite FTS5 for entry/content search and the local Python runtime reports SQLite 3.49.1, while public advisories flag FTS5 before 3.50.3.
  Evidence: `core/cache.py`; local `py -3` SQLite 3.49.1; Tenable GHSA-v2c8-vqqp-hv3g advisory
  Touches: `core/cache.py`, `quickfind.py`, `build.py`, `requirements.txt`, tests
  Acceptance: startup/build logs the SQLite version; vulnerable FTS5 versions are blocked, disabled, or replaced by a patched bundled SQLite; tests cover the version gate.
  Complexity: M

- [ ] P0 - Harden remote search auth token and CORS handling
  Why: query-string tokens and wildcard CORS expose a file-path search API more broadly than needed.
  Evidence: `server/http_server.py:134-141`, `server/http_server.py:263`; DocFetcher Server and Listary network-search patterns
  Touches: `server/http_server.py`, `gui/settings_dialog.py`, `tests/test_http_server.py`, README security notes
  Acceptance: browser API uses Authorization or same-origin session flow instead of URL tokens; authenticated responses do not emit wildcard CORS; tests cover unauthorized, authorized, and CORS cases.
  Complexity: M

### P1 - Trust, Reliability, and Observability

- [ ] P1 - Add content indexing jobs, quotas, and adapter diagnostics
  Why: PDF/Office extraction is now available but lacks opt-in roots, disk quotas, pause/resume, failure summaries, and visible adapter health.
  Evidence: `core/content/adapters.py`, `core/cache.py`; Recoll helper diagnostics; Everything scoped content-index includes
  Touches: `core/content/`, `core/cache.py`, `gui/settings_dialog.py`, `gui/main_window.py`, tests
  Acceptance: content indexing runs as a cancellable background job with per-root/file-type settings, cache size limits, adapter failure counts, and status UI.
  Complexity: L

- [ ] P1 - Make Everything import saves atomic and validated
  Why: normal settings/bookmark/filter saves are atomic, but imported Everything filters/bookmarks still write JSON directly.
  Evidence: `core/everything_import.py:150-194`, `gui/bookmarks.py`, `gui/filters.py`
  Touches: `core/everything_import.py`, `gui/main_window.py`, tests
  Acceptance: imported filters/bookmarks write through temp-and-replace, reject malformed rows with status feedback, and leave existing JSON intact on failure.
  Complexity: S

- [ ] P1 - Pin application dependencies and document the supported runtime matrix
  Why: release builds need reproducible dependency versions for PyQt6, pywin32, pdfplumber, py7zr, python-docx, python-pptx, and SQLite behavior.
  Evidence: `requirements.txt`; PyInstaller/PyQt/pdfplumber release notes; README build instructions
  Touches: `requirements.txt`, `build.py`, `README.md`, tests
  Acceptance: requirements are version-bounded or locked; build output records Python, SQLite, PyQt6, PyInstaller, and pywin32 versions; README states supported/tested versions.
  Complexity: S

- [ ] P1 - Add cache, service, and index health diagnostics
  Why: users need to see whether results come from MFT, cache, USN catchup, service heartbeat, EFU, or fallback scans before trusting stale/missing results.
  Evidence: `core/index.py`, `core/cache.py`, `service/ipc.py`, `gui/main_window.py`; FSearch offline/removable-drive behavior
  Touches: `gui/status_indicators.py`, `gui/main_window.py`, `core/index.py`, `core/cache.py`, `service/ipc.py`, tests
  Acceptance: diagnostics view shows per-drive mode, last successful scan/update, cache integrity, USN position, service heartbeat, content cache size, and actionable recovery buttons.
  Complexity: M

### P2 - Search Depth and Workflow Expansion

- [ ] P2 - Persist archive member metadata for fast `archive:` searches
  Why: current archive search enumerates supported archives on demand; large ZIP/7z collections need cached member names, sizes, modified dates, and invalidation.
  Evidence: `core/archives.py`, `core/search.py`; DocFetcher Pro archive indexing
  Touches: `core/archives.py`, `core/cache.py`, `core/search.py`, tests
  Acceptance: archive member index persists in SQLite, invalidates when archive size/mtime changes, supports max-result limits, and keeps virtual paths stable.
  Complexity: M

- [ ] P2 - Return content snippets and ranking from the content FTS cache
  Why: content search currently filters paths but does not expose FTS snippets/ranking, making matches harder to inspect.
  Evidence: `core/cache.py:437-499`, `gui/preview_pane.py`; Recoll and DocFetcher result previews
  Touches: `core/cache.py`, `core/search.py`, `gui/results_view.py`, `gui/preview_pane.py`, tests
  Acceptance: `content:` results include matched snippets or line context, sort meaningfully for content hits, and avoid loading full cached text into UI rows.
  Complexity: M

- [ ] P2 - Add removable and virtual drive stale-index policy
  Why: removable, cloud, and virtual drives may appear late or disappear, and stale cached results need clear status rather than silent trust.
  Evidence: `core/index.py:981-1038`; WizFile delayed startup for virtual drives; FSearch removable/offline patterns
  Touches: `core/index.py`, `core/ntfs.py`, `gui/settings_dialog.py`, `gui/status_indicators.py`, tests
  Acceptance: drives have online/offline/stale states, configurable startup delay, stale-result badges, and a one-click refresh per drive.
  Complexity: M

### P3 — Larger Features

- [ ] P3 - Prototype Open/Save dialog Quick Switch integration
  Why: Listary's strongest workflow advantage is jumping file dialogs to a searched folder; QuickFind can test this as an optional Windows-only integration.
  Evidence: Listary Quick Switch docs; `gui/launcher_popup.py`; `gui/context_menu.py`
  Touches: new Windows integration module, `gui/launcher_popup.py`, settings, tests
  Acceptance: when enabled, selected folder results can target the active common file dialog without changing normal search behavior.
  Complexity: XL
