# QuickFind Roadmap

NTFS-MFT-backed instant file search (PyQt6 + SQLite FTS5). Voidtools Everything alternative with CLI, HTTP server, and Catppuccin theme. Roadmap strengthens content search, network share indexing, and cross-platform reach.

## Planned Features

### Indexing

### Content Search

### Search Syntax

### UX

### Remote

### Cross-platform

### Packaging

## Competitive Research
- **Voidtools Everything** — gold standard; closed source, Windows only, no content search. Lesson: content + remote + Linux are the deficits QuickFind should own.
- **fd + ripgrep** — CLI stars. Lesson: keep CLI fast, ensure `es.py` behaves predictably in scripts.
- **Recoll / DocFetcher** — content indexers. Lesson: don't rebuild Tika; borrow it.
- **Windows Search** — built-in, slow on big MFT. Lesson: explicit "beats Windows Search" metric in README (already present in feeling, make it a benchmark).

## Nice-to-Haves

## Research-Driven Additions

### P0 - Security and Release Blockers

### P1 - Trust, Reliability, and Observability

### P2 - Search Depth and Workflow Expansion

- [ ] P2 — Package and discover modifier plugins safely
  Why: The modifier plugin API is programmatic only, so third-party plugins cannot be installed, disabled, or quarantined without code edits.
  Evidence: `core/search.py:182`, `tests/test_search.py:337`, Flow Launcher plugin store/docs, PowerToys Run plugin model.
  Touches: `core/search.py`, `gui/settings_dialog.py`, `gui/help_docs.py`, `README.md`, `tests/test_search.py`
  Acceptance: QuickFind discovers plugin manifests or Python entry points from a configured plugin directory, validates names/permissions, disables failed plugins without breaking search, lists plugin status in settings/help, and tests conflict/quarantine behavior.
  Complexity: L

- [ ] P2 — Incrementally reindex content from file-change events
  Why: Content indexing is a manual/background pass over all entries; changed files should enqueue targeted content refreshes from USN/watchdog updates.
  Evidence: `gui/main_window.py:137`, `core/content/indexer.py`, `core/index.py:1732`, Recoll/FSearch update workflows.
  Touches: `core/index.py`, `core/content/indexer.py`, `gui/main_window.py`, `core/cache.py`, `tests/test_content_search.py`, `tests/test_index.py`
  Acceptance: Creates/renames/modifies/deletes enqueue bounded content-cache refresh/removal work for supported files, diagnostics show queue status/failures, and tests prove stale snippets disappear after file changes.
  Complexity: L

- [ ] P2 — Add visual query builder and filter chips for advanced modifiers
  Why: QuickFind has rich boolean/modifier syntax, but complex queries are discoverable mainly through offline docs rather than editable UI state.
  Evidence: `core/search.py`, `gui/help_docs.py`, Everything/FSearch filters, Recoll query workflow, FileLocator Pro query UX.
  Touches: `gui/main_window.py`, `gui/filters.py`, `gui/help_docs.py`, `core/search.py`, `tests/test_search.py`, `tests/test_main_window.py`
  Acceptance: Users can compose/edit modifiers as removable chips, chips round-trip to the raw query string, invalid modifiers show inline status, and parser tests cover UI-generated queries.
  Complexity: M

- [ ] P2 — Add duplicate review workflow with safe remediation
  Why: `dupe:` and `dupe:hash` identify duplicates, but there is no grouped review surface, keep-rule preview, or safe batch action.
  Evidence: `core/search.py:1142`, `gui/results_view.py`, UltraSearch/WizFile duplicate and hardlink features.
  Touches: `core/search.py`, `gui/main_window.py`, `gui/results_view.py`, `gui/context_menu.py`, `tests/test_search.py`, `tests/test_main_window.py`
  Acceptance: Duplicate results can be grouped by duplicate set/hash, users can preview keep/delete candidates, safe actions move only selected duplicates to Recycle Bin with feedback, and tests cover folders, hardlinks, and missing files.
  Complexity: L

- [ ] P2 — Add report-grade result export from the GUI
  Why: QuickFind can export EFU file lists and the CLI can emit CSV/JSON, but the GUI cannot save active results with visible columns, query criteria, content snippets, or HTML/CSV/JSON report formats for review and handoff.
  Evidence: `gui/main_window.py:1787`, `cli/es.py:182`, FileLocator Pro result export and commercial report workflows.
  Touches: `gui/main_window.py`, `gui/results_view.py`, `core/file_list.py`, `tests/test_main_window.py`, `tests/test_file_list.py`
  Acceptance: File > Export offers CSV, JSON, and HTML report formats for current results, includes query/filter/sort metadata and optional content snippets, escapes HTML/CSV safely, respects visible columns, and reports success/failure in the status bar.
  Complexity: M

### P3 — Larger Features

- [ ] P3 — Add portable/cloud-profile mode with machine-scoped caches
  Why: Users sync launcher/search profiles through OneDrive/Dropbox, but cache and plugin state need machine-specific identity to avoid stale paths and conflicts.
  Evidence: `gui/settings_dialog.py`, `core/cache.py`, Flow Launcher portable-mode issue signal, Listary portable/profile workflows.
  Touches: `gui/settings_dialog.py`, `core/cache.py`, `core/version.py`, `README.md`, `tests/test_settings_validation.py`
  Acceptance: A portable mode stores settings beside the executable or a chosen root, caches include a machine/source identity, synced profiles do not reuse incompatible cache DBs, and diagnostics report portable/profile paths.
  Complexity: L

- [ ] P3 — Make the remote web UI installable and mobile-tested
  Why: Remote search has cards and OpenAPI, but there is no PWA manifest, offline shell, or mobile viewport verification for phone/tablet lookup flows.
  Evidence: `server/http_server.py`, `tests/test_http_server.py`, Fluent/Copernic remote/search-app expectations.
  Touches: `server/http_server.py`, `tests/test_http_server.py`, `README.md`
  Acceptance: Remote UI includes responsive mobile layout tests, PWA manifest/icons, offline/error shell for disconnected API calls, and no weakening of read-only auth behavior.
  Complexity: M

- [ ] P3 — Prototype shared read-only search server with explicit ACL boundary
  Why: Commercial and Recoll-style web deployments show demand for shared indexes, but exposing personal filesystem results requires an explicit access-control model before multi-user use.
  Evidence: `server/http_server.py`, `service/windows_service.py`, Recoll web/Python API docs, FileLocator/Copernic enterprise search patterns.
  Touches: `server/http_server.py`, `service/windows_service.py`, `core/index.py`, `gui/settings_dialog.py`, `README.md`, `tests/test_http_server.py`
  Acceptance: A prototype supports named read-only indexes and per-token allowed roots, denies paths outside token roots, logs denied requests, and documents that shared mode is disabled by default.
  Complexity: XL
