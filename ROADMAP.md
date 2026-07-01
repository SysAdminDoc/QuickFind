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
