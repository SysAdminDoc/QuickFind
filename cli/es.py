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
    python es.py @logs error
    python es.py --csv size:>1mb ext:mp4
"""

import sys
import os
import csv
import json
import argparse
import multiprocessing
import shlex
import subprocess
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ntfs import get_all_drives
from core.index import FileIndex, FileEntry
from core.query_slots import load_saved_query_slots
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
    parser.add_argument('-R', '--reverse', action='store_true',
                        help='Reverse the sort order (default is ascending)')
    parser.add_argument('-n', '--max', type=int, default=100, help='Max results')
    parser.add_argument('-o', '--offset', type=int, default=0, help='Skip N results')
    parser.add_argument('--csv', action='store_true', help='CSV output')
    parser.add_argument('--tsv', action='store_true', help='Tab-separated output')
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--no-header', action='store_true', help='Omit the header row in CSV/TSV output')
    parser.add_argument('--export-efu', metavar='PATH', help='Write results to an EFU file list at PATH')
    parser.add_argument('--format', dest='format_template', metavar='TEMPLATE',
                        help='Format each result with placeholders: '
                             '{path} {name} {dir} {size} {ext} {dm} {dc}')
    parser.add_argument('--hyperlink', action='store_true',
                        help='Emit OSC-8 clickable file:// hyperlinks (TTY only)')
    parser.add_argument('--count', action='store_true',
                        help='Print only the number of results')
    parser.add_argument('--total-size', action='store_true',
                        help='Print only the summed size of results in bytes')
    parser.add_argument('-x', '--exec', dest='exec_cmd', metavar='CMD',
                        help='Run CMD once per result. Placeholders: {} {/} {//} {.} {/.} '
                             '(a bare {} is appended if none are present)')
    parser.add_argument('-X', '--exec-batch', dest='exec_batch', metavar='CMD',
                        help='Run CMD once with all result paths (substituted for {} or appended)')
    parser.add_argument('--drives', type=str, help='Comma-separated drive letters (e.g., C,D)')
    parser.add_argument('--no-index-time', action='store_true', help='Hide indexing time')
    parser.add_argument('--reindex', action='store_true', help='Force full reindex (ignore cache)')
    parser.add_argument('--explain', action='store_true',
                        help='Print how the query parses (terms, modifiers, filters) and exit')

    return parser.parse_args()


def main():
    args = parse_args()
    query = ' '.join(args.query) if args.query else ''

    if not query:
        print("Usage: es <search-query>", file=sys.stderr)
        print("Try 'es --help' for more information.", file=sys.stderr)
        sys.exit(1)

    if args.explain:
        # Parsing needs no index, so answer immediately.
        from core.search import explain_query
        info = explain_query(query, query_slots=load_saved_query_slots())
        json.dump(info, sys.stdout, indent=2)
        print()
        return

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
        sort_order=SortOrder.DESCENDING if args.reverse else SortOrder.ASCENDING,
    )

    engine = SearchEngine(file_index)
    results = engine.search(
        query,
        base_options=options,
        query_slots=load_saved_query_slots(),
    )

    # Apply offset
    if args.offset:
        results = results[args.offset:]

    exit_code = 0
    try:
        # Aggregate outputs suppress the result listing.
        if args.count:
            print(len(results))
        elif args.total_size:
            print(sum(int(e.size or 0) for e in results))
        elif args.export_efu:
            from core.file_list import save_efu
            save_efu(results, args.export_efu, file_index)
            print(f"Wrote {len(results)} entries to {args.export_efu}", file=sys.stderr)
        elif args.exec_cmd:
            exit_code = _exec_per_result(args.exec_cmd, results, file_index)
        elif args.exec_batch:
            exit_code = _exec_batch(args.exec_batch, results, file_index)
        elif args.json:
            _output_json(results, file_index)
        elif args.csv or args.tsv:
            _output_csv(results, file_index, delimiter='\t' if args.tsv else ',',
                        header=not args.no_header)
        elif args.format_template:
            _output_format(results, file_index, args.format_template)
        else:
            _output_text(results, file_index, hyperlink=args.hyperlink)
    finally:
        file_index.shutdown()
        close_all_connections()
    sys.exit(exit_code)


def _osc8(path: str, text: str) -> str:
    """Wrap text in an OSC-8 hyperlink pointing at file://<abs path>."""
    uri = 'file:///' + os.path.abspath(path).replace('\\', '/').lstrip('/')
    return f"\x1b]8;;{uri}\x1b\\{text}\x1b]8;;\x1b\\"


def _output_text(results, index, hyperlink=False):
    """Plain text output - one path per line."""
    use_links = hyperlink and sys.stdout.isatty()
    for entry in results:
        path = entry.get_path(index)
        print(_osc8(path, path) if use_links else path)


def _placeholders(path: str) -> dict:
    """fd-style path placeholder substitutions."""
    base = os.path.basename(path)
    return {
        '{}': path,
        '{/}': base,
        '{//}': os.path.dirname(path),
        '{.}': os.path.splitext(path)[0],
        '{/.}': os.path.splitext(base)[0],
    }


def _apply_placeholders(token: str, subs: dict) -> str:
    for key, value in subs.items():
        token = token.replace(key, value)
    return token


def _exec_per_result(template: str, results, index) -> int:
    """Run the command once per result, substituting fd-style placeholders.

    Runs sequentially so child exit codes and output are not interleaved; the
    returned code is the highest child exit code seen.
    """
    tokens = shlex.split(template, posix=(os.name != 'nt'))
    has_placeholder = any('{' in t for t in tokens)
    worst = 0
    for entry in results:
        subs = _placeholders(entry.get_path(index))
        cmd = [_apply_placeholders(t, subs) for t in tokens]
        if not has_placeholder:
            cmd.append(subs['{}'])
        try:
            worst = max(worst, subprocess.run(cmd).returncode)
        except OSError as exc:
            print(f"exec failed: {exc}", file=sys.stderr)
            worst = max(worst, 1)
    return worst


def _exec_batch(template: str, results, index) -> int:
    """Run the command once with all result paths substituted for {} or appended."""
    paths = [e.get_path(index) for e in results]
    if not paths:
        return 0
    tokens = shlex.split(template, posix=(os.name != 'nt'))
    cmd = []
    substituted = False
    for token in tokens:
        if '{}' in token:
            cmd.extend(paths)
            substituted = True
        else:
            cmd.append(token)
    if not substituted:
        cmd.extend(paths)
    try:
        return subprocess.run(cmd).returncode
    except OSError as exc:
        print(f"exec failed: {exc}", file=sys.stderr)
        return 1


def _output_format(results, index, template):
    """Render each result with a {field} template."""
    for entry in results:
        path = entry.get_path(index)
        fields = {
            'path': path,
            'name': entry.name,
            'dir': index.resolve_parent_path(entry.drive, entry.parent_frn),
            'size': entry.size,
            'ext': entry.extension,
            'dm': entry.date_modified.isoformat() if entry.date_modified else '',
            'dc': entry.date_created.isoformat() if entry.date_created else '',
        }
        try:
            print(template.format(**fields))
        except (KeyError, IndexError, ValueError):
            # Unknown placeholder — emit the template literally rather than crash.
            print(template)


_CSV_INJECTION_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value):
    """Neutralize spreadsheet formula/DDE injection from attacker-controlled
    filenames by prefixing risky leading characters with a single quote."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def _output_csv(results, index, delimiter=',', header=True):
    """CSV/TSV output, optionally with a header row."""
    writer = csv.writer(sys.stdout, delimiter=delimiter)
    if header:
        writer.writerow(['Name', 'Path', 'Size', 'Date Modified', 'Type', 'Attributes'])

    for entry in results:
        path = index.resolve_parent_path(entry.drive, entry.parent_frn)
        dm = entry.date_modified.isoformat() if entry.date_modified else ''
        ext = entry.extension
        ftype = 'Folder' if entry.is_dir else (f'{ext.upper()} File' if ext else 'File')

        writer.writerow([
            _csv_safe(entry.name), _csv_safe(path), entry.size, dm,
            _csv_safe(ftype), _format_attrs(entry.attributes)
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
    multiprocessing.freeze_support()
    main()
