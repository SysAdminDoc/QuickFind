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
- Content indexing (Tika / textract / pdfplumber) with optional on-disk index
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

## Open-Source Research (Round 2)

### Related OSS Projects
- https://github.com/githubrobbi/Ultra-Fast-File-Search — Python MFT parser with parallel-disk scanning. Same domain, same language.
- https://github.com/ChrisS85/FastFileSearch — NTFS USN journal C++ DLL, exports language-friendly types.
- https://github.com/dwmkerr/fsearch — fd-based CLI (not the GTK one).
- https://github.com/cboxdoerfer/fsearch — GTK Everything-clone for Linux, strongest open alternative.
- https://github.com/omrilotan/everything-toolbar — Windows tray integration, good UX reference.
- https://github.com/shirosaidev/diskover — Elasticsearch-backed crawler for massive filesystems.
- https://github.com/dalance/fd — Fast find replacement; regex engine is best-in-class.
- https://github.com/analyzeMFT/analyzeMFT — Forensics-grade $MFT parser in Python; attribute-level access.

### Features to Borrow
- Parallel-per-disk MFT parsing with bounded worker pool (UFFS).
- analyzeMFT-style deep attribute access — parse $EA, $REPARSE_POINT, $OBJECT_ID for richer filters.
- Everything-Toolbar's taskbar search-box integration (Win10/11 dock pattern).
- FSearch-style tokenized index for sub-50ms type-ahead on millions of files.
- Modifier syntax: `size:>100MB ext:pdf modified:<7d dir:Downloads` (FSearch + fd hybrid).
- ElasticSearch / SQLite FTS5 exporter for multi-machine queries (diskover pattern).
- Saved-search panel with live-updating counts (FSearch).
- Content search hybrid: ripgrep integration for `content:"foo bar"` queries with filter scope.

### Patterns & Architectures Worth Studying
- **USN V3/V4 128-bit FileID handling** (already in project) — essential for ReFS; cross-check against UFFS's approach.
- **Bounded parallel MFT reader with producer/consumer queue** (UFFS) — avoids head-contention on spinning disks.
- **Persistent on-disk index with memory-mapped load** — SQLite or LMDB; skip rescan on restart.
- **Tokenized prefix trie for type-ahead** (FSearch) — sub-millisecond lookup on 10M entries.
- **Change-journal tailer + coalesce window** — batch 100ms of USN records before DB write; already in project, worth tuning window empirically.
