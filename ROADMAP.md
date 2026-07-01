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

- [ ] P2 — HTTP server class-level mutable state shared across all handler instances
  Why: SearchHandler dependencies (file_index, auth_token, session_token) are class attributes overwritten globally. Multiple server instances or sequential creation can corrupt state.
  Where: `server/http_server.py` lines 654-658, 1078-1083

- [ ] P3 — Audit salt regenerated on every restart, preventing cross-restart correlation
  Why: `_AUDIT_SALT` is `secrets.token_bytes(16)` at module load. Same IP hashes differently after restart, reducing audit trail usefulness.
  Where: `server/http_server.py` line 32

### P3 — Larger Features

