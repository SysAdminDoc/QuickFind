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

- [ ] P2 — Incrementally reindex content from file-change events
  Why: Content indexing is a manual/background pass over all entries; changed files should enqueue targeted content refreshes from USN/watchdog updates.
  Evidence: `gui/main_window.py:137`, `core/content/indexer.py`, `core/index.py:1732`, Recoll/FSearch update workflows.
  Touches: `core/index.py`, `core/content/indexer.py`, `gui/main_window.py`, `core/cache.py`, `tests/test_content_search.py`, `tests/test_index.py`
  Acceptance: Creates/renames/modifies/deletes enqueue bounded content-cache refresh/removal work for supported files, diagnostics show queue status/failures, and tests prove stale snippets disappear after file changes.
  Complexity: L

- [ ] P2 — Add duplicate review workflow with safe remediation
  Why: `dupe:` and `dupe:hash` identify duplicates, but there is no grouped review surface, keep-rule preview, or safe batch action.
  Evidence: `core/search.py:1142`, `gui/results_view.py`, UltraSearch/WizFile duplicate and hardlink features.
  Touches: `core/search.py`, `gui/main_window.py`, `gui/results_view.py`, `gui/context_menu.py`, `tests/test_search.py`, `tests/test_main_window.py`
  Acceptance: Duplicate results can be grouped by duplicate set/hash, users can preview keep/delete candidates, safe actions move only selected duplicates to Recycle Bin with feedback, and tests cover folders, hardlinks, and missing files.
  Complexity: L

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
