# QuickFind v0.7.1

Lightning-fast file search for Windows, powered by NTFS MFT + USN Journal.

An open-source alternative to Voidtools Everything, built with Python and PyQt6 for extensibility and customization.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

## Features

### Core Engine
- **Instant indexing** via NTFS Master File Table (MFT) direct read with parallel scanning
- **FAT32/exFAT/ReFS support** for external drives and Dev Drives via recursive `os.scandir` walk
- **USN Journal V2/V3/V4** support - V3/V4 with 128-bit file IDs for ReFS compatibility
- **Real-time updates** via USN Change Journal monitoring (NTFS) and periodic rescan (FAT/exFAT/ReFS)
- **Batch incremental DB writes** - USN changes applied in single transactions for performance
- **Non-admin fallback** - gracefully degrades to `os.scandir` when UAC is declined
- **Thread-safe USN change application** with lock-protected flat list rebuild
- **Cancel support** during indexing with cooperative cancellation
- **SQLite FTS5** full-text search cache with WAL mode and memory-mapped I/O
- **DB corruption recovery** with automatic integrity checks and rebuild
- **Sub-second search** across millions of files with compiled pattern matching
- **Minimal footprint** - lightweight in-memory index with `__slots__` optimization

### Search
- Instant-as-you-type results with debounced search
- **Search history** with autocomplete suggestions
- **Result highlighting** - match substrings painted in accent color
- **Inline column filtering** - per-column filter row below headers
- **Regex** support (`regex:pattern`)
- **Wildcards** (`*.py`, `test?.log`)
- **Boolean logic** - AND (spaces), OR (`|`), NOT (`!term`)
- **Search modifiers**: `case:`, `path:`, `file:`, `folder:`, `wholeword:`, `ext:`, `size:`, `dm:`, `dc:`, `len:`, `attrib:`, `content:`, `parent:`, `dupe:`
- Size filters: `size:>1mb`, `size:100kb..5mb`
- Date filters: `dm:today`, `dm:>2024-01-01`, `dc:thisweek`
- Attribute filters: `attrib:hs` (hidden + system)
- Content search: `content:searchterm` (reads file content, slower)
- **Search syntax help** panel accessible from menu

### GUI
- **Catppuccin Mocha** dark theme - premium paid-software aesthetic
- **Details view** with sortable columns (Name, Path, Size, Date Modified, Date Created, Type, Attributes)
- **Column visibility** - right-click header to show/hide columns, persisted in settings
- **Keyboard navigation** - Enter=open, Delete=recycle, F2=rename, Ctrl+Enter=open folder
- **Thumbnail view** for visual browsing
- **Preview pane** for text files, images, and file info
- **Filter bar** with built-in filters (Audio, Video, Image, Document, Executable, Compressed, Folder) + custom filters
- **Bookmarks** - save/restore search + filter state, organized in folders
- **Context menu** - Open, Open Path, Copy Name/Path, Terminal Here (CMD/PowerShell/WT), Delete to Recycle Bin, Properties
- **System tray** with minimize-to-tray and close-to-tray
- **Global hotkey** (Ctrl+Shift+F) to show/activate from anywhere
- **Startup performance metrics** - entries/sec displayed in status bar
- **Proper app icon** (.ico) for window, taskbar, and tray
- **Dark title bar** via DwmSetWindowAttribute on Windows 10/11
- **Regex validation** with inline error highlighting
- **Result count in tab titles** for multi-tab awareness
- **Index progress in tray tooltip** shows live indexing status

### Advanced
- **HTTP server** for remote web browser access with optional **token-based authentication**
- **EFU file lists** for indexing non-NTFS and network drives
- **CLI tool** (`es.py`) with full search syntax, CSV/JSON output, and **DB cache** for instant results
- **Export/import settings** - save and restore configuration as JSON
- **Settings** for indexing, search, UI, drives, columns, and server configuration
- **PyInstaller build script** for single-file or single-folder distribution
- **Multiple instance** support

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges recommended (for NTFS MFT access; falls back to os.scandir without admin)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/SysAdminDoc/QuickFind.git
cd QuickFind

# Run (auto-installs PyQt6, attempts admin elevation, falls back gracefully)
python quickfind.py
```

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

## Build

```bash
# Build single-folder distribution
python build.py

# Build single-file exe
python build.py --onefile

# Clean build artifacts
python build.py --clean
```

## Search Syntax

| Syntax | Description |
|--------|-------------|
| `foo bar` | Files containing both "foo" AND "bar" |
| `foo \| bar` | Files containing "foo" OR "bar" |
| `!temp` | Exclude files containing "temp" |
| `"exact phrase"` | Match exact phrase |
| `*.py` | Wildcard matching |
| `regex:^test\d+` | Regex matching |
| `case:FooBar` | Case-sensitive match |
| `path:src\utils` | Match in full path |
| `file:` / `folder:` | Files or folders only |
| `ext:py;js;ts` | Filter by extension |
| `size:>1mb` | Size greater than 1MB |
| `size:100kb..5mb` | Size range |
| `dm:today` | Modified today |
| `dm:>2024-01-01` | Modified after date |
| `dc:thisweek` | Created this week |
| `len:>20` | Filename length > 20 chars |
| `attrib:rh` | Read-only + hidden |
| `content:TODO` | Search file content |
| `parent:node_modules` | Parent directory filter |
| `dupe:` | Find duplicate filenames |

## Architecture

```
QuickFind/
  quickfind.py          # Entry point (bootstrap + admin elevation + fallback)
  build.py              # PyInstaller packaging script
  core/
    ntfs.py             # NTFS MFT/USN via ctypes + ReFS/Dev Drive support
    index.py            # In-memory index + USN monitor + deferred path resolution
    cache.py            # SQLite FTS5 cache + integrity check + search history
    search.py           # Search engine with modifiers
    file_list.py        # EFU file list import/export
  gui/
    main_window.py      # Main window (menus, toolbar, layout, syntax help)
    results_view.py     # Table model + highlight delegate + column filters
    preview_pane.py     # Text/image/info preview
    filters.py          # Filter bar + custom filter editor
    bookmarks.py        # Bookmark manager + panel
    context_menu.py     # Right-click menu with shell integration
    tray.py             # System tray + global hotkey + app icon
    settings_dialog.py  # Settings dialog with tabs + export/import
    theme.py            # Catppuccin Mocha stylesheet
  server/
    http_server.py      # Remote web search server + token auth
  cli/
    es.py               # Command-line search tool + DB cache
  assets/
    quickfind.ico       # App icon (auto-generated on first run)
```

## How It Works

1. **MFT Scan** (NTFS): Reads the NTFS Master File Table directly to enumerate all file/folder records in ~1-2 seconds per drive (parallel scanning across drives)
2. **Directory Walk** (FAT/exFAT/ReFS): Uses recursive `os.scandir` for non-NTFS drives (external USB, SD cards, Dev Drives)
3. **Non-Admin Fallback**: If UAC elevation is declined, falls back to `os.scandir` for all drives
4. **Path Resolution**: Builds parent-child FRN tree to resolve full paths on demand with deferred batch resolution
5. **USN Journal** (NTFS): Polls the NTFS Change Journal (V2/V3/V4) every second for creates/deletes/renames/modifications
6. **Batch DB Writes**: USN changes are collected and applied in single SQLite transactions for efficiency
7. **Periodic Rescan** (FAT/exFAT/ReFS): Re-walks non-NTFS drives every 60 seconds for change detection
8. **Search**: Parses query modifiers, compiles matchers (regex/wildcard/substring), and filters the in-memory index
9. **DB Cache**: SQLite FTS5 database persists the index for instant CLI searches and fast startup recovery

## License

MIT License
