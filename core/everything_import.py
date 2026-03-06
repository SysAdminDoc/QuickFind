"""
Import Everything configuration files (Bookmarks.csv, Filters.csv) into QuickFind format.
"""

import csv
import json
import logging
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger('QuickFind.EverythingImport')

CONFIG_DIR = Path.home() / '.quickfind'
BOOKMARKS_FILE = CONFIG_DIR / 'bookmarks.json'
FILTERS_FILE = CONFIG_DIR / 'filters.json'


def import_everything_filters(csv_path: str) -> list[dict]:
    """
    Import Everything Filters.csv into QuickFind custom filters format.
    Returns list of filter dicts ready for filters.json.

    Everything Filters.csv columns:
    Name, Case, Whole Word, Path, Diacritics, Prefix, Suffix,
    Ignore Punctuation, Ignore Whitespace, Regex, Search,
    Columns, Sort, Descending, View, Macro, Key
    """
    filters = []
    builtin_names = {'Everything', 'Everything -all', 'Audio', 'Video',
                     'Image', 'Document', 'Executable', 'Compressed', 'Folder'}

    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip().strip('"')
                if not name or name in builtin_names:
                    continue

                search = row.get('Search', '').strip().strip('"')
                macro = row.get('Macro', '').strip().strip('"')

                # Parse extensions from search field (ext:xxx;yyy pattern)
                extensions = []
                remaining_search = search
                if search.lower().startswith('ext:'):
                    # Pure extension filter
                    ext_part = search[4:].split(' ')[0]
                    extensions = [e.strip().lower() for e in ext_part.split(';') if e.strip()]
                    remaining_search = search[4 + len(ext_part):].strip()

                # Detect folder-only filter
                folders_only = search.strip().lower() == 'folder:'
                files_only = bool(extensions)

                # Parse size filter
                min_size = 0
                max_size = 0
                if 'size:>' in search.lower():
                    import re
                    m = re.search(r'size:>(\d+\w+)', search, re.IGNORECASE)
                    if m:
                        min_size = _parse_size_str(m.group(1))

                filters.append({
                    'name': name,
                    'extensions': extensions,
                    'min_size': min_size,
                    'max_size': max_size,
                    'files_only': files_only,
                    'folders_only': folders_only,
                    'macro': macro or remaining_search,
                })

    except Exception as e:
        logger.error(f"Failed to import Everything filters: {e}")
        return []

    return filters


def import_everything_bookmarks(csv_path: str) -> list[dict]:
    """
    Import Everything Bookmarks.csv into QuickFind bookmarks format.
    Returns list of bookmark dicts ready for bookmarks.json.

    Everything Bookmarks.csv columns:
    Name, Case, Whole Word, Path, Diacritics, Prefix, Suffix,
    Ignore Punctuation, Ignore Whitespace, Regex, Search,
    Columns, Sort, Descending, View, Macro, Key
    """
    bookmarks = []
    current_folder = ""

    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('Name', '').strip().strip('"')
                if not name:
                    continue

                search = row.get('Search', '').strip().strip('"')
                case_val = row.get('Case', '0').strip()
                regex_val = row.get('Regex', '0').strip()
                sort_field = row.get('Sort', '').strip().strip('"')
                descending = row.get('Descending', '0').strip()

                match_case = case_val == '1'
                use_regex = regex_val == '1'

                # Detect folder entries (no search query, acts as category)
                if not search and not row.get('Macro', '').strip():
                    current_folder = name
                    continue

                # Map sort field
                sort_col = 0
                if sort_field:
                    sort_map = {
                        'Name': 0, 'Path': 1, 'Size': 2,
                        'Date Modified': 3, 'Date Created': 4,
                        'Extension': 5, 'Attributes': 6,
                        'Date Recently Changed': 3,
                    }
                    sort_col = sort_map.get(sort_field, 0)

                bookmarks.append({
                    'name': name,
                    'query': search,
                    'filter_name': 'Everything',
                    'sort_column': sort_col,
                    'sort_ascending': descending != '1',
                    'match_case': match_case,
                    'use_regex': use_regex,
                    'folder': current_folder,
                    'created': datetime.now().isoformat(),
                })

    except Exception as e:
        logger.error(f"Failed to import Everything bookmarks: {e}")
        return []

    return bookmarks


def save_imported_filters(filters: list[dict], merge: bool = True):
    """Save imported filters to QuickFind filters.json."""
    CONFIG_DIR.mkdir(exist_ok=True)
    existing = []
    if merge and FILTERS_FILE.exists():
        try:
            with open(FILTERS_FILE, 'r') as f:
                existing = json.load(f)
        except Exception:
            pass

    # Merge: skip filters that already exist by name
    existing_names = {f['name'] for f in existing}
    for filt in filters:
        if filt['name'] not in existing_names:
            existing.append(filt)

    with open(FILTERS_FILE, 'w') as f:
        json.dump(existing, f, indent=2)

    logger.info(f"Saved {len(existing)} filters to {FILTERS_FILE}")
    return len(existing)


def save_imported_bookmarks(bookmarks: list[dict], merge: bool = True):
    """Save imported bookmarks to QuickFind bookmarks.json."""
    CONFIG_DIR.mkdir(exist_ok=True)
    existing = []
    if merge and BOOKMARKS_FILE.exists():
        try:
            with open(BOOKMARKS_FILE, 'r') as f:
                existing = json.load(f)
        except Exception:
            pass

    # Merge: skip bookmarks that already exist by name+query
    existing_keys = {(b['name'], b.get('query', '')) for b in existing}
    for bm in bookmarks:
        if (bm['name'], bm.get('query', '')) not in existing_keys:
            existing.append(bm)

    with open(BOOKMARKS_FILE, 'w') as f:
        json.dump(existing, f, indent=2)

    logger.info(f"Saved {len(existing)} bookmarks to {BOOKMARKS_FILE}")
    return len(existing)


def import_all(filters_csv: str = None, bookmarks_csv: str = None) -> tuple[int, int]:
    """
    Import both Everything filters and bookmarks.
    Returns (filter_count, bookmark_count).
    """
    filter_count = 0
    bookmark_count = 0

    if filters_csv and os.path.exists(filters_csv):
        filters = import_everything_filters(filters_csv)
        if filters:
            filter_count = save_imported_filters(filters)
            logger.info(f"Imported {len(filters)} filters from {filters_csv}")

    if bookmarks_csv and os.path.exists(bookmarks_csv):
        bookmarks = import_everything_bookmarks(bookmarks_csv)
        if bookmarks:
            bookmark_count = save_imported_bookmarks(bookmarks)
            logger.info(f"Imported {len(bookmarks)} bookmarks from {bookmarks_csv}")

    return filter_count, bookmark_count


def _parse_size_str(size_str: str) -> int:
    """Parse a size string like '1GB', '500KB' into bytes."""
    size_str = size_str.strip().lower()
    multipliers = {
        'b': 1, 'kb': 1024, 'mb': 1024**2, 'gb': 1024**3, 'tb': 1024**4,
        'k': 1024, 'm': 1024**2, 'g': 1024**3, 't': 1024**4,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-len(suffix)]) * mult)
            except ValueError:
                return 0
    try:
        return int(size_str)
    except ValueError:
        return 0
