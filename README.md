# QuickFind v0.8.8

Lightning-fast file search for Windows, powered by NTFS MFT + USN Journal.

An open-source alternative to [Voidtools Everything](https://www.voidtools.com/), built with Python and PyQt6 for extensibility and customization.

![Version](https://img.shields.io/badge/Version-v0.8.8-blueviolet)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![Tests](https://img.shields.io/badge/Tests-212%20passing-brightgreen)

## Features

### Core Engine
- **Instant indexing** via NTFS Master File Table (MFT) direct read with parallel scanning
- **FAT32/exFAT/ReFS support** for external drives and Dev Drives via recursive `os.scandir` walk
- **USN Journal V2/V3/V4** support — V3/V4 with 128-bit file IDs for ReFS compatibility
- **Real-time updates** via USN Change Journal monitoring (NTFS) and configurable periodic rescan (FAT/exFAT/ReFS)
- **Non-admin fallback** — gracefully degrades to `os.scandir` when UAC is declined, with a persistent status-bar indicator
- **SQLite FTS5** full-text search cache with WAL mode and memory-mapped I/O, gated to patched SQLite runtimes with LIKE fallback
- **DB corruption recovery** with automatic integrity checks and rebuild
- **Sub-second search** across millions of files with compiled pattern matching
- **Incremental availability** — search is available as soon as the first drive finishes indexing
- **Minimal footprint** — lightweight in-memory index with `__slots__` optimization

### Search
- Instant-as-you-type results with debounced search
- **Smart case sensitivity** — uppercase in query auto-switches to case-sensitive (fd-style); explicit `case:`/`nocase:` overrides
- **Fuzzy matching** via `fuzzy:` modifier — subsequence matching for typo-tolerant search
- **Search history** with autocomplete suggestions
- **Result highlighting** — match substrings painted in accent color
- **Inline column filtering** — per-column filter row below headers
- **Regex** support (`regex:pattern`)
- **Wildcards** (`*.py`, `test?.log`)
- **Boolean logic** — AND (spaces), OR (`|`), NOT (`!term`)
- **Content search** — `content:keyword` searches cached TXT/PDF/DOCX/PPTX extracted text through adapters, with cancellable background indexing, root/type filters, quotas, and adapter diagnostics
- **Archive search** — `archive:` searches filenames inside ZIP and 7z archives without extracting them
- **Usage-based ranking** — frequently opened files rank higher with Relevance sort
- **17 search modifiers**: `case:`, `path:`, `file:`, `folder:`, `wholeword:`, `ext:`, `size:`, `dm:`, `dc:`, `len:`, `attrib:`, `content:`, `parent:`, `dupe:`, `archive:`, `fuzzy:`, `regex:`
- **Search syntax help** panel accessible from Help menu

### GUI
- **Launcher popup** — `Ctrl+Shift+F` summons a floating search bar (Wox/Flow Launcher style) with keyboard hints and empty-state feedback
- **Catppuccin Mocha** dark theme — premium polished aesthetic with rounded inputs, focus rings, and consistent spacing
- **Details view** with sortable columns (Name, Path, Size, Date Modified, Date Created, Type, Attributes)
- **Bounded native icon cache** keeps file-type icons responsive without unbounded memory growth
- **Column visibility** — right-click header to show/hide columns, persisted in settings
- **Keyboard navigation** — `Enter` open, `Delete` recycle, `F2` rename, `Ctrl+Enter` open folder
- **Thumbnail view** for visual browsing
- **Preview pane** for text files, images, and file info with matched-line context for `content:` searches
- **Filter bar** with built-in filters (Audio, Video, Image, Document, Executable, Compressed, Folder) + custom filters
- **Bookmarks** — save/restore search + filter state
- **Context menu** — Open, Open Path, Copy Name/Path, Terminal Here (CMD/PowerShell/WT), Delete to Recycle Bin, Properties
- **System tray** with minimize-to-tray and close-to-tray
- **Index diagnostics** from the Tools menu with cache integrity, per-drive mode/USN state, service heartbeat, content cache size, and recovery buttons
- **Dark title bar** via DwmSetWindowAttribute on Windows 10/11
- **Accessibility** — `accessibleName`/`accessibleDescription` on key widgets; focus-visible states on all interactive elements

### Advanced
- **HTTP/HTTPS server** for remote web browser access with TLS certificate support, Bearer/session-cookie authentication, per-IP rate limiting (60 req/min), XSS protection (CSP headers + `html.escape`), and sticky-header web UI
- **Windows service mode** for background indexing/monitoring with GUI status heartbeat over localhost IPC
- **`.quickfindignore`** files — place in any directory with glob patterns to exclude files/folders from indexing (like `.gitignore`)
- **EFU file lists** for indexing non-NTFS and network drives
- **CLI tool** (`es.py`) with full search syntax, CSV/JSON output, and DB cache for instant results
- **Per-drive rescan intervals** — configure different rescan frequencies for SSD vs NAS drives
- **Export/import settings** — save and restore configuration as validated JSON
- **Everything import hardening** — malformed CSV rows and invalid JSON are rejected before atomic filter/bookmark replacement
- **Log rotation** — `RotatingFileHandler` with 5 MB max and 3 backups
- **212 automated tests** covering startup dependency handling, build/runtime matrix reporting, SQLite/FTS5 version gates, remote auth/CORS hardening, Everything import validation, index/cache/service diagnostics, content indexing jobs/quotas/diagnostics, search parsing, archive search, content adapters/cache, service IPC, duplicate detection, MFT record parsing, privilege lifecycle, settings validation, index mode UI state, results-view cache bounds, cache helpers, remote server configuration, and ignore patterns
- **PyInstaller build script** for single-file or single-folder distribution

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges recommended (for NTFS MFT access; falls back to `os.scandir` without admin)

## Supported Runtime Matrix

| Component | Supported | Tested in v0.8.8 |
|-----------|-----------|------------------|
| OS | Windows 10/11 | Windows 10.0.26100 |
| Python | 3.10+ | 3.11.9 |
| SQLite | LIKE fallback on older runtimes; FTS5 enabled on patched SQLite 3.53.2+ | 3.45.1 with FTS5 disabled |
| PyQt6 / Qt6 / sip | pinned in `requirements.txt` | 6.11.0 / 6.11.1 / 13.11.1 |
| pywin32 | pinned in `requirements.txt` | 312 |
| Content/archive adapters | pinned in `requirements.txt` | pdfplumber 0.11.10, py7zr 1.1.3, python-docx 1.2.0, python-pptx 1.0.2 |
| Build tooling | pinned in `requirements.txt`; no build-time auto-install | PyInstaller 6.21.0 |

## Quick Start

```bash
# Clone the repo
git clone https://github.com/SysAdminDoc/QuickFind.git
cd QuickFind

# Install dependencies
pip install -r requirements.txt

# Run (attempts admin elevation, falls back gracefully)
python quickfind.py
```

QuickFind never installs dependencies at startup. Source runs require the dependencies above to be installed first; frozen builds must bundle them through `build.py`.

SQLite FTS5 is enabled only on SQLite 3.53.2 or newer. Older runtimes keep working through LIKE-based entry and content search fallback.

## CLI Usage

```bash
# Basic search (uses DB cache for instant results)
python cli/es.py "*.py"

# Force reindex (bypass cache)
python cli/es.py --reindex "*.py"

# Regex search for log files
python cli/es.py -r "error.*\.log$"

# Find large MP4 files, output as JSON
python cli/es.py --json "size:>100mb ext:mp4"

# Files only, sorted by date modified
python cli/es.py -f -s dm "report"

# Search specific drives
python cli/es.py --drives C,D "*.docx"
```

## Service Mode

```bash
# Install the background index service
python quickfind.py --install-service

# Start/stop/remove the service
python quickfind.py --start-service
python quickfind.py --stop-service
python quickfind.py --remove-service
```

## Build

```bash
# Build single-folder distribution
python build.py

# Build single-file exe
python build.py --onefile

# Clean build artifacts
python build.py --clean
```

Build output prints the tested runtime matrix before invoking PyInstaller. If PyInstaller is missing, install the pinned requirements instead of relying on an automatic build-time install.

## Search Syntax

| Syntax | Description |
|--------|-------------|
| `foo bar` | Files containing both "foo" AND "bar" |
| `foo \| bar` | Files containing "foo" OR "bar" |
| `!temp` | Exclude files containing "temp" |
| `"exact phrase"` | Match exact phrase |
| `*.py` | Wildcard matching |
| `regex:^test\d+` | Regex matching |
| `fuzzy:qickfind` | Fuzzy subsequence matching |
| `case:FooBar` | Case-sensitive match |
| `path:src\utils` | Match in full path |
| `file:` / `folder:` | Files or folders only |
| `ext:py;js;ts` | Filter by extension |
| `size:>1mb` | Size greater than 1 MB |
| `size:100kb..5mb` | Size range |
| `dm:today` | Modified today |
| `dm:>2024-01-01` | Modified after date |
| `dc:thisweek` | Created this week |
| `content:TODO` | Search inside cached TXT/PDF/DOCX/PPTX content |
| `len:>20` | Filename length > 20 chars |
| `attrib:rh` | Read-only + hidden |
| `parent:node_modules` | Parent directory filter |
| `dupe:` | Find duplicate filenames |
| `archive:report` | Find files named report inside ZIP/7z archives |

**Smart case:** Queries with uppercase letters automatically use case-sensitive matching. All-lowercase queries match case-insensitively. Override with `case:` or `nocase:`.

## .quickfindignore

Place a `.quickfindignore` file in any directory to exclude matching files and folders from indexing. Uses glob patterns, one per line (like `.gitignore`):

```
node_modules
*.pyc
.git
__pycache__
.venv
```

Lines starting with `#` are treated as comments.

## Architecture

```
QuickFind/
  quickfind.py              # Entry point (bootstrap + admin elevation + fallback)
  build.py                  # PyInstaller packaging script
  requirements.txt          # pip dependencies
  core/
    ntfs.py                 # NTFS MFT/USN via ctypes + ReFS/Dev Drive support
    index.py                # In-memory index + USN monitor + deferred path resolution
    cache.py                # SQLite FTS5 cache + integrity check + search history + content cache
    search.py               # Search engine with modifiers + fuzzy/content matching
    archives.py             # ZIP/7z member enumeration for archive: searches
    content/                # TXT/PDF/DOCX/PPTX extraction adapters + content indexing jobs
    utils.py                # Shared utilities (size parsing)
    file_list.py            # EFU file list import/export
    hidden_paths.py         # Per-filter hidden path management
    everything_import.py    # Validated Everything config file import
  gui/
    main_window.py          # Main window (menus, toolbar, layout, multi-tab search)
    launcher_popup.py       # Floating launcher search bar (Ctrl+Shift+F)
    results_view.py         # Table model + highlight delegate + column filters
    preview_pane.py         # Text/image/info preview
    filters.py              # Filter bar + custom filter editor
    bookmarks.py            # Bookmark manager + panel
    context_menu.py         # Right-click menu with shell integration
    tray.py                 # System tray + global hotkey + app icon
    settings_dialog.py      # Settings dialog with tabs + export/import
    diagnostics_dialog.py   # Index/cache/service diagnostics and recovery actions
    hidden_paths_dialog.py  # Hidden paths management dialog
    theme.py                # Catppuccin Mocha theme system
  server/
    http_server.py          # Remote web search server + token auth + rate limiting
  service/
    windows_service.py      # pywin32 background index service
    ipc.py                  # localhost JSON status socket
  cli/
    es.py                   # Command-line search tool + DB cache
  tests/
    test_search.py          # Search parsing, modifiers, smart case, fuzzy matching
    test_archive_search.py  # ZIP/7z archive member search
    test_content_search.py  # Content extraction, cache, and preview context
    test_everything_import.py # Everything CSV/JSON import validation
    test_service.py         # Service status socket and install wiring
    test_ntfs.py            # MFT record parsing, FILETIME conversion, USA fixup
    test_cache.py           # Datetime conversion, FTS5 detection
    test_index.py           # .quickfindignore pattern matching
    test_file_list.py       # EFU file loading and FILETIME parsing
  assets/
    quickfind.ico           # App icon (auto-generated on first run)
```

## How It Works

1. **MFT Scan** (NTFS): Reads the NTFS Master File Table directly to enumerate all file/folder records in ~1-2 seconds per drive (parallel scanning across drives)
2. **Directory Walk** (FAT/exFAT/ReFS): Uses recursive `os.scandir` for non-NTFS drives (external USB, SD cards, Dev Drives)
3. **Non-Admin Fallback**: If UAC elevation is declined, falls back to `os.scandir` for all drives
4. **Incremental Availability**: Search is available as soon as the first drive finishes indexing — no waiting for all drives to complete
5. **Path Resolution**: Builds parent-child FRN tree to resolve full paths on demand with deferred batch resolution
6. **USN Journal** (NTFS): Polls the NTFS Change Journal (V2/V3/V4) every second for creates/deletes/renames/modifications
7. **Periodic Rescan** (FAT/exFAT/ReFS): Re-walks non-NTFS drives at configurable intervals for change detection
8. **Search**: Parses query modifiers, compiles matchers (regex/wildcard/substring/fuzzy/content), and filters the in-memory index — falls back to SQLite FTS5 for simple queries
9. **Content Cache**: TXT/PDF/DOCX/PPTX adapters extract text into an on-disk SQLite FTS5 cache for faster repeated `content:` searches
10. **DB Cache**: SQLite FTS5 database persists the index for instant CLI searches and fast startup recovery
11. **Service Mode**: Optional Windows service keeps the index warm in the background and exposes localhost JSON status for the GUI
12. **Usage Tracking**: Files opened via QuickFind have their open counts tracked in SQLite for relevance-based ranking

## Testing

```bash
# Run the test suite (212 tests)
python -m pytest tests/ -v
```

Tests cover startup dependency handling, build/runtime matrix reporting, SQLite/FTS5 version gates, remote auth/CORS hardening, Everything import validation, index/cache/service diagnostics, content indexing jobs/quotas/diagnostics, search query parsing (all modifiers), archive member search, content extraction/cache, service IPC, size/date helpers, smart case sensitivity, fuzzy matching, MFT record parsing, USA fixup, USN records, cache datetime round-trip, FTS5 detection, results-view cache bounds, `.quickfindignore` pattern matching, and EFU file loading.

## Security

- **XSS protection**: HTTP server uses `html.escape()` for all user-derived content with `Content-Security-Policy` and `X-Content-Type-Options` headers
- **Rate limiting**: Per-IP rate limiter (60 requests/minute) on the HTTP server with `429 Too Many Requests` response
- **HTTPS support**: Optional TLS certificate/key configuration for encrypted remote search access
- **Token authentication**: Optional Bearer API tokens plus same-origin browser session cookies; tokens are not accepted in URLs
- **Safe Win32 calls**: All ctypes DLL loads use `WinDLL(use_last_error=True)` with complete `argtypes` declarations
- **Atomic config saves**: Settings, bookmarks, filters, hidden paths, and Everything imports use validated atomic writes to prevent corruption on crash
- **Privilege scoping**: `SeBackupPrivilege` enabled only when needed for NTFS MFT access

## License

MIT License
