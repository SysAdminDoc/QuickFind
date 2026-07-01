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

- [ ] P3 — Prototype shared read-only search server with explicit ACL boundary
  Why: Commercial and Recoll-style web deployments show demand for shared indexes, but exposing personal filesystem results requires an explicit access-control model before multi-user use.
  Evidence: `server/http_server.py`, `service/windows_service.py`, Recoll web/Python API docs, FileLocator/Copernic enterprise search patterns.
  Touches: `server/http_server.py`, `service/windows_service.py`, `core/index.py`, `gui/settings_dialog.py`, `README.md`, `tests/test_http_server.py`
  Acceptance: A prototype supports named read-only indexes and per-token allowed roots, denies paths outside token roots, logs denied requests, and documents that shared mode is disabled by default.
  Complexity: XL
