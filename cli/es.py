#!/usr/bin/env python3
"""
es.py - QuickFind Command-Line Search Tool

Usage:
    python es.py [options] <search-query>

Options:
    -r, --regex          Enable regex search
    -i, --case           Match case
    -w, --whole-word     Match whole word
    -p, --match-path     Match full path
    -f, --files-only     Show files only
    -d, --folders-only   Show folders only
    -s, --sort <field>   Sort by: name, path, size, dm, dc, ext
    -n, --max <count>    Maximum results (default: 100)
    -o, --offset <n>     Skip first N results
    --csv                Output as CSV
    --json               Output as JSON
    --reindex            Force full reindex (ignore cache)
    -h, --help           Show this help

Examples:
    python es.py "*.py"
    python es.py -r "test.*\\.log$"
    python es.py -f ext:pdf
    python es.py --csv size:>1mb ext:mp4
"""

import sys
import os
import csv
import json
import argparse
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ntfs import get_all_drives
from core.index import FileIndex, FileEntry
from core.search import SearchEngine, SearchOptions, SortField, SortOrder
from core.cache import DB_FILE, load_entries_from_cache, close_all_connections


def parse_args():
    parser = argparse.ArgumentParser(
        prog='es',
        description='QuickFind command-line search tool',
        add_help=True
    )
    parser.add_argument('query', nargs='*', help='Search query')
    parser.add_argument('-r', '--regex', action='store_true', help='Enable regex')
    parser.add_argument('-i', '--case', action='store_true', help='Match case')
    parser.add_argument('-w', '--whole-word', action='store_true', help='Match whole word')
    parser.add_argument('-p', '--match-path', action='store_true', help='Match full path')
    parser.add_argument('-f', '--files-only', action='store_true', help='Files only')
    parser.add_argument('-d', '--folders-only', action='store_true', help='Folders only')
    parser.add_argument('-s', '--sort', default='name',
                        choices=['name', 'path', 'size', 'dm', 'dc', 'ext'],
                        help='Sort field')
    parser.add_argument('-n', '--max', type=int, default=100, help='Max results')
    parser.add_argument('-o', '--offset', type=int, default=0, help='Skip N results')
    parser.add_argument('--csv', action='store_true', help='CSV output')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--drives', type=str, help='Comma-separated drive letters (e.g., C,D)')
    parser.add_argument('--no-index-time', action='store_true', help='Hide indexing time')
    parser.add_argument('--reindex', action='store_true', help='Force full reindex (ignore cache)')

    return parser.parse_args()


def main():
    args = parse_args()
    query = ' '.join(args.query) if args.query else ''

    if not query:
        print("Usage: es <search-query>", file=sys.stderr)
        print("Try 'es --help' for more information.", file=sys.stderr)
        sys.exit(1)

    file_index = FileIndex()

    drives = None
    if args.drives:
        drives = [d.strip().upper() for d in args.drives.split(',')]

    # Try loading from DB cache first for instant results
    cache_loaded = False
    if not args.reindex and DB_FILE.exists():
        if not args.no_index_time:
            print("Loading cache...", file=sys.stderr, end='', flush=True)
        start = time.perf_counter()

        try:
            all_entries, drive_entries = load_entries_from_cache()
            load_time = time.perf_counter() - start

            if all_entries:
                # Populate the FileIndex from cached data
                file_index._entries = drive_entries
                file_index._all_entries = all_entries
                cache_loaded = True
                if not args.no_index_time:
                    print(f" {len(all_entries):,} entries in {load_time:.2f}s (cached)",
                          file=sys.stderr)
            else:
                if not args.no_index_time:
                    print(" empty, will reindex", file=sys.stderr)
        except Exception as e:
            if not args.no_index_time:
                print(f" failed ({e}), will reindex", file=sys.stderr)

    # Fall back to full indexing if cache miss or --reindex
    if not cache_loaded:
        if not args.no_index_time:
            print("Indexing...", file=sys.stderr, end='', flush=True)

        start = time.perf_counter()
        file_index.index_all_drives(drives)
        index_time = time.perf_counter() - start

        if not args.no_index_time:
            stats = file_index.stats
            print(f" {stats.total_files + stats.total_folders:,} entries in {index_time:.1f}s",
                  file=sys.stderr)

    # Search
    sort_map = {
        'name': SortField.NAME,
        'path': SortField.PATH,
        'size': SortField.SIZE,
        'dm': SortField.DATE_MODIFIED,
        'dc': SortField.DATE_CREATED,
        'ext': SortField.EXTENSION,
    }

    options = SearchOptions(
        match_case=args.case,
        use_regex=args.regex,
        match_whole_word=args.whole_word,
        match_path=args.match_path,
        files_only=args.files_only,
        folders_only=args.folders_only,
        max_results=args.max + args.offset,
        sort_by=sort_map.get(args.sort, SortField.NAME),
    )

    engine = SearchEngine(file_index)
    results = engine.search(query, base_options=options)

    # Apply offset
    if args.offset:
        results = results[args.offset:]

    try:
        # Output
        if args.json:
            _output_json(results, file_index)
        elif args.csv:
            _output_csv(results, file_index)
        else:
            _output_text(results, file_index)
    finally:
        file_index.shutdown()
        close_all_connections()


def _output_text(results, index):
    """Plain text output - one path per line."""
    for entry in results:
        print(entry.get_path(index))


def _output_csv(results, index):
    """CSV output with headers."""
    writer = csv.writer(sys.stdout)
    writer.writerow(['Name', 'Path', 'Size', 'Date Modified', 'Type', 'Attributes'])

    for entry in results:
        path = index.resolve_parent_path(entry.drive, entry.parent_frn)
        dm = entry.date_modified.isoformat() if entry.date_modified else ''
        ext = entry.extension
        ftype = 'Folder' if entry.is_dir else (f'{ext.upper()} File' if ext else 'File')

        writer.writerow([
            entry.name, path, entry.size, dm, ftype,
            _format_attrs(entry.attributes)
        ])


def _output_json(results, index):
    """JSON output."""
    items = []
    for entry in results:
        items.append({
            'name': entry.name,
            'path': entry.get_path(index),
            'directory': index.resolve_parent_path(entry.drive, entry.parent_frn),
            'size': entry.size,
            'date_modified': entry.date_modified.isoformat() if entry.date_modified else None,
            'date_created': entry.date_created.isoformat() if entry.date_created else None,
            'is_dir': entry.is_dir,
            'extension': entry.extension,
            'attributes': entry.attributes,
        })

    json.dump(items, sys.stdout, indent=2)
    print()


def _format_attrs(attrs):
    parts = []
    if attrs & 0x01: parts.append('R')
    if attrs & 0x02: parts.append('H')
    if attrs & 0x04: parts.append('S')
    if attrs & 0x10: parts.append('D')
    if attrs & 0x20: parts.append('A')
    if attrs & 0x800: parts.append('C')
    if attrs & 0x4000: parts.append('E')
    return ''.join(parts)


if __name__ == '__main__':
    main()
