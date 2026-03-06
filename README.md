# QuickFind v0.1.0

Lightning-fast file search for Windows, powered by NTFS MFT + USN Journal.

An open-source alternative to Voidtools Everything, built with Python and PyQt6 for extensibility and customization.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)

## Features

### Core Engine
- **Instant indexing** via NTFS Master File Table (MFT) direct read
- **Real-time updates** via USN Change Journal monitoring (1-second polling)
- **Sub-second search** across millions of files with compiled pattern matching
- **Minimal footprint** - lightweight in-memory index

### Search
- Instant-as-you-type results with debounced search
- **Regex** support (`regex:pattern`)
- **Wildcards** (`*.py`, `test?.log`)
- **Boolean logic** - AND (spaces), OR (`|`), NOT (`!term`)
- **Search modifiers**: `case:`, `path:`, `file:`, `folder:`, `wholeword:`, `ext:`, `size:`, `dm:`, `dc:`, `len:`, `attrib:`, `content:`, `parent:`, `dupe:`
- Size filters: `size:>1mb`, `size:100kb..5mb`
- Date filters: `dm:today`, `dm:>2024-01-01`, `dc:thisweek`
- Attribute filters: `attrib:hs` (hidden + system)
- Content search: `content:searchterm` (reads file content, slower)

### GUI
- **Catppuccin Mocha** dark theme - premium paid-software aesthetic
- **Details view** with sortable columns (Name, Path, Size, Date Modified, Date Created, Type, Attributes)
- **Thumbnail view** for visual browsing
- **Preview pane** for text files, images, and file info
- **Filter bar** with built-in filters (Audio, Video, Image, Document, Executable, Compressed, Folder) + custom filters
- **Bookmarks** - save/restore search + filter state, organized in folders
- **Context menu** - Open, Open Path, Copy Name/Path, Terminal Here (CMD/PowerShell/WT), Delete to Recycle Bin, Properties
- **System tray** with minimize-to-tray and close-to-tray
- **Global hotkey** (Ctrl+Shift+F) to show/activate from anywhere

### Advanced
- **HTTP server** for remote web browser access to search
- **EFU file lists** for indexing non-NTFS and network drives
- **CLI tool** (`es.py`) with full search syntax, CSV/JSON output
- **Settings** for indexing, search, UI, drives, and server configuration
- **Multiple instance** support

## Requirements

- Windows 10/11
- Python 3.10+
- Administrator privileges (for NTFS volume access)

## Quick Start

```bash
# Clone the repo
git clone https://github.com/SysAdminDoc/QuickFind.git
cd QuickFind

# Run (auto-installs PyQt6, auto-elevates to admin)
python quickfind.py
```

## CLI Usage

```bash
# Basic search
python cli/es.py "*.py"

# Regex search for log files
python cli/es.py -r "error.*\.log$"

# Find large MP4 files, output as JSON
python cli/es.py --json "size:>100mb ext:mp4"

# Files only, sorted by date modified
python cli/es.py -f -s dm "report"

# Search specific drives
python cli/es.py --drives C,D "*.docx"
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
  quickfind.py          # Entry point (bootstrap + admin elevation)
  core/
    ntfs.py             # NTFS MFT/USN via ctypes + DeviceIoControl
    index.py            # In-memory index + USN monitor thread
    search.py           # Search engine with modifiers
    file_list.py        # EFU file list import/export
  gui/
    main_window.py      # Main window (menus, toolbar, layout)
    results_view.py     # Table model + thumbnail view
    preview_pane.py     # Text/image/info preview
    filters.py          # Filter bar + custom filter editor
    bookmarks.py        # Bookmark manager + panel
    context_menu.py     # Right-click menu with shell integration
    tray.py             # System tray + global hotkey
    settings_dialog.py  # Settings dialog with tabs
    theme.py            # Catppuccin Mocha stylesheet
  server/
    http_server.py      # Remote web search server
  cli/
    es.py               # Command-line search tool
```

## How It Works

1. **MFT Scan**: Reads the NTFS Master File Table via `FSCTL_ENUM_USN_DATA` to enumerate all file/folder records in ~1-2 seconds per drive
2. **Path Resolution**: Builds parent-child FRN tree to resolve full paths on demand
3. **USN Journal**: Polls the NTFS Change Journal every second for creates/deletes/renames/modifications
4. **Search**: Parses query modifiers, compiles matchers (regex/wildcard/substring), and filters the in-memory index

## License

MIT License
