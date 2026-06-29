"""
Import Everything configuration files (Bookmarks.csv, Filters.csv) into QuickFind format.
"""

import csv
import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Any

from core.query_slots import normalize_query_slot_name
from core.utils import parse_size as _parse_size_str

logger = logging.getLogger('QuickFind.EverythingImport')

CONFIG_DIR = Path.home() / '.quickfind'
BOOKMARKS_FILE = CONFIG_DIR / 'bookmarks.json'
FILTERS_FILE = CONFIG_DIR / 'filters.json'


class EverythingImportError(ValueError):
    """Raised when an Everything import file or destination JSON is invalid."""


def _csv_value(row: dict[str | None, Any], key: str) -> str:
    value = row.get(key, "")
    if value is None:
        return ""
    return str(value).strip().strip('"')


def _row_has_values(row: dict[str | None, Any]) -> bool:
    return any(str(value).strip() for key, value in row.items() if key is not None and value is not None)


def _require_headers(reader: csv.DictReader, required: set[str], label: str) -> None:
    headers = set(reader.fieldnames or [])
    if not headers:
        raise EverythingImportError(f"{label} CSV has no header row")
    missing = sorted(required - headers)
    if missing:
        raise EverythingImportError(f"{label} CSV missing required columns: {', '.join(missing)}")


def _assert_well_formed_row(row: dict[str | None, Any], line_num: int, label: str) -> None:
    if None in row:
        raise EverythingImportError(f"{label} CSV row {line_num} has too many columns")
    if _row_has_values(row) and not _csv_value(row, "Name"):
        raise EverythingImportError(f"{label} CSV row {line_num} is missing Name")


def _non_negative_int(value: Any, field: str, label: str) -> int:
    if isinstance(value, bool):
        raise EverythingImportError(f"{label} has invalid {field}")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EverythingImportError(f"{label} has invalid {field}") from exc
    if parsed < 0:
        raise EverythingImportError(f"{label} has invalid {field}")
    return parsed


def _bool_value(value: Any) -> bool:
    return value if isinstance(value, bool) else bool(value)


def _normalize_extensions(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EverythingImportError(f"{label} has invalid extensions")
    extensions = []
    for item in value:
        if not isinstance(item, str):
            raise EverythingImportError(f"{label} has invalid extensions")
        ext = item.strip().lstrip(".").lower()
        if ext and ext not in extensions:
            extensions.append(ext)
    return extensions


def _normalize_filter_record(item: Any, label: str) -> dict:
    if not isinstance(item, dict):
        raise EverythingImportError(f"{label} is not an object")
    name = str(item.get("name", "")).strip()
    if not name:
        raise EverythingImportError(f"{label} is missing name")
    files_only = _bool_value(item.get("files_only", False))
    folders_only = _bool_value(item.get("folders_only", False))
    if files_only and folders_only:
        raise EverythingImportError(f"{label} cannot be both files_only and folders_only")
    return {
        "name": name,
        "extensions": _normalize_extensions(item.get("extensions", []), label),
        "min_size": _non_negative_int(item.get("min_size", 0), "min_size", label),
        "max_size": _non_negative_int(item.get("max_size", 0), "max_size", label),
        "files_only": files_only,
        "folders_only": folders_only,
        "macro": str(item.get("macro", "")),
        "exclude_paths": _normalize_string_list(item.get("exclude_paths", []), "exclude_paths", label),
    }


def _normalize_string_list(value: Any, field: str, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise EverythingImportError(f"{label} has invalid {field}")
    normalized = []
    for item in value:
        if not isinstance(item, str):
            raise EverythingImportError(f"{label} has invalid {field}")
        text = item.strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_bookmark_record(item: Any, label: str) -> dict:
    if not isinstance(item, dict):
        raise EverythingImportError(f"{label} is not an object")
    name = str(item.get("name", "")).strip()
    if not name:
        raise EverythingImportError(f"{label} is missing name")
    return {
        "name": name,
        "query": str(item.get("query", "")),
        "slot": normalize_query_slot_name(str(item.get("slot", ""))),
        "filter_name": str(item.get("filter_name", "Everything") or "Everything"),
        "sort_column": _non_negative_int(item.get("sort_column", 0), "sort_column", label),
        "sort_ascending": _bool_value(item.get("sort_ascending", True)),
        "match_case": _bool_value(item.get("match_case", False)),
        "use_regex": _bool_value(item.get("use_regex", False)),
        "folder": str(item.get("folder", "")),
        "created": str(item.get("created", "")),
    }


def _load_existing_records(path: Path, normalizer, label: str) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise EverythingImportError(f"Existing {label} file is not valid JSON") from exc
    if not isinstance(data, list):
        raise EverythingImportError(f"Existing {label} file must contain a list")
    return [normalizer(item, f"existing {label} #{idx + 1}") for idx, item in enumerate(data)]


def _atomic_write_json(path: Path, data: list[dict], label: str) -> None:
    path.parent.mkdir(exist_ok=True)
    try:
        payload = json.dumps(data, indent=2)
    except (TypeError, ValueError) as exc:
        raise EverythingImportError(f"Could not serialize {label}") from exc

    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise EverythingImportError(f"Could not save {label}") from exc


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
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            _require_headers(reader, {"Name", "Search"}, "Filters")
            for row in reader:
                _assert_well_formed_row(row, reader.line_num, "Filters")
                name = _csv_value(row, 'Name')
                if not name or name in builtin_names:
                    continue

                search = _csv_value(row, 'Search')
                macro = _csv_value(row, 'Macro')

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

    except EverythingImportError:
        raise
    except Exception as e:
        logger.error(f"Failed to import Everything filters: {e}")
        raise EverythingImportError(f"Failed to import Everything filters: {e}") from e

    return [_normalize_filter_record(filt, f"imported filter #{idx + 1}") for idx, filt in enumerate(filters)]


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
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            _require_headers(reader, {"Name", "Search"}, "Bookmarks")
            for row in reader:
                _assert_well_formed_row(row, reader.line_num, "Bookmarks")
                name = _csv_value(row, 'Name')
                if not name:
                    continue

                search = _csv_value(row, 'Search')
                case_val = _csv_value(row, 'Case') or '0'
                regex_val = _csv_value(row, 'Regex') or '0'
                sort_field = _csv_value(row, 'Sort')
                descending = _csv_value(row, 'Descending') or '0'

                match_case = case_val == '1'
                use_regex = regex_val == '1'

                # Detect folder entries (no search query, acts as category)
                if not search and not _csv_value(row, 'Macro'):
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

    except EverythingImportError:
        raise
    except Exception as e:
        logger.error(f"Failed to import Everything bookmarks: {e}")
        raise EverythingImportError(f"Failed to import Everything bookmarks: {e}") from e

    return [_normalize_bookmark_record(bm, f"imported bookmark #{idx + 1}") for idx, bm in enumerate(bookmarks)]


def save_imported_filters(filters: list[dict], merge: bool = True):
    """Save imported filters to QuickFind filters.json."""
    incoming = [_normalize_filter_record(filt, f"imported filter #{idx + 1}") for idx, filt in enumerate(filters)]
    existing = _load_existing_records(FILTERS_FILE, _normalize_filter_record, "filters") if merge else []

    # Merge: skip filters that already exist by name
    existing_names = {f['name'] for f in existing}
    for filt in incoming:
        if filt['name'] not in existing_names:
            existing.append(filt)
            existing_names.add(filt['name'])

    _atomic_write_json(FILTERS_FILE, existing, "filters")

    logger.info(f"Saved {len(existing)} filters to {FILTERS_FILE}")
    return len(existing)


def save_imported_bookmarks(bookmarks: list[dict], merge: bool = True):
    """Save imported bookmarks to QuickFind bookmarks.json."""
    incoming = [_normalize_bookmark_record(bm, f"imported bookmark #{idx + 1}") for idx, bm in enumerate(bookmarks)]
    existing = _load_existing_records(BOOKMARKS_FILE, _normalize_bookmark_record, "bookmarks") if merge else []

    # Merge: skip bookmarks that already exist by name+query
    existing_keys = {(b['name'], b.get('query', '')) for b in existing}
    for bm in incoming:
        if (bm['name'], bm.get('query', '')) not in existing_keys:
            existing.append(bm)
            existing_keys.add((bm['name'], bm.get('query', '')))

    _atomic_write_json(BOOKMARKS_FILE, existing, "bookmarks")

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


