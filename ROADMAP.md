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

- [ ] P2 — Reverse dark title bar for Latte (light) theme
  Why: `_set_dark_title_bar` is called once at init; switching to Latte produces a dark title bar on a light window body. Needs `DwmSetWindowAttribute` with value 0 on theme change.
  Where: `gui/main_window.py` lines 271, 1029-1054

- [ ] P2 — Hardcoded Mocha colors in help_docs HTML and result_export HTML
  Why: `#45475a` border and other hex literals in `help_docs.py:57` and `result_export.py:96-102` are wrong under non-Mocha themes. Needs parameterized theme tokens.
  Where: `gui/help_docs.py`, `core/result_export.py`

- [ ] P2 — Plugin loader has no sandboxing or signature verification
  Why: `exec_module` runs arbitrary Python with full privileges. Path traversal is now blocked, but any plugin in the plugin directory gets unrestricted code execution with no audit hook or hash pinning.
  Where: `core/plugin_loader.py` lines 126-133

- [ ] P3 — PWA manifest icon URLs return 404
  Why: `/icon-192.png` and `/icon-512.png` in `_pwa_manifest()` have no serving route. The PWA install prompt will fail or show a broken icon.
  Where: `server/http_server.py` `_pwa_manifest()`, route handling

