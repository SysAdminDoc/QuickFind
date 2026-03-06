"""
Search engine with Everything-compatible modifiers, regex, wildcards, and filters.

Supports: plain text, regex:, wildcards:, case:, path:, file:, folder:,
wholeword:, wholefilename:, content:, size:, dm: (date modified),
dc: (date created), ext:, attrib:, len:, parent:, dupe:
"""

import re
import os
import fnmatch
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, Callable

from core.index import FileEntry, FileIndex

logger = logging.getLogger('QuickFind.Search')


class SortField(Enum):
    NAME = auto()
    PATH = auto()
    SIZE = auto()
    DATE_MODIFIED = auto()
    DATE_CREATED = auto()
    EXTENSION = auto()
    ATTRIBUTES = auto()


class SortOrder(Enum):
    ASCENDING = auto()
    DESCENDING = auto()


@dataclass
class SearchOptions:
    """Options controlling search behavior."""
    match_case: bool = False
    match_whole_word: bool = False
    match_whole_filename: bool = False
    match_path: bool = False
    use_regex: bool = False
    use_wildcards: bool = False
    files_only: bool = False
    folders_only: bool = False
    max_results: int = 0  # 0 = unlimited
    sort_by: SortField = SortField.DATE_MODIFIED
    sort_order: SortOrder = SortOrder.DESCENDING


@dataclass
class SearchFilter:
    """A named filter that restricts results by extension, size, etc."""
    name: str
    extensions: list[str] = field(default_factory=list)
    min_size: int = 0
    max_size: int = 0  # 0 = no limit
    files_only: bool = False
    folders_only: bool = False
    macro: str = ""  # Search query to apply
    exclude_paths: list[str] = field(default_factory=list)

    # Built-in filters (extension lists matched to Everything defaults)
    @staticmethod
    def audio():
        return SearchFilter("Audio", extensions=[
            'aac', 'ac3', 'adt', 'adts', 'aif', 'aifc', 'aiff', 'amr', 'ape',
            'au', 'cda', 'dts', 'ec3', 'fla', 'flac', 'lpcm', 'm1a', 'm2a',
            'm3u', 'm3u8', 'm4a', 'm4b', 'm4p', 'mid', 'midi', 'mka', 'mp2',
            'mp3', 'mpa', 'mpc', 'oga', 'ogg', 'opus', 'ra', 'rmi', 'snd',
            'wav', 'wax', 'weba', 'wma',
        ], files_only=True)

    @staticmethod
    def video():
        return SearchFilter("Video", extensions=[
            '3g2', '3gp', '3gp2', '3gpp', 'amv', 'asf', 'asx', 'avi', 'bdmv',
            'bik', 'd2v', 'divx', 'drc', 'dsa', 'dsm', 'dss', 'dsv', 'evo',
            'f4v', 'flc', 'fli', 'flic', 'flv', 'hdmov', 'ifo', 'ivf', 'm1v',
            'm2p', 'm2t', 'm2ts', 'm2v', 'm4v', 'mkv', 'mod', 'mov', 'mp2v',
            'mp4', 'mp4v', 'mpe', 'mpeg', 'mpg', 'mpls', 'mpv2', 'mpv4',
            'mts', 'ogm', 'ogv', 'ogx', 'pss', 'pva', 'qt', 'ram', 'ratdvd',
            'rm', 'rmm', 'rmvb', 'roq', 'rpm', 'smil', 'smk', 'swf', 'tod',
            'tp', 'tpr', 'tts', 'uvu', 'vob', 'vp6', 'webm', 'wm', 'wmp',
            'wmv', 'wmx', 'wvx',
        ], files_only=True)

    @staticmethod
    def image():
        return SearchFilter("Image", extensions=[
            'ani', 'apng', 'avif', 'avifs', 'bmp', 'bpg', 'cur', 'dds', 'gif',
            'heic', 'heics', 'heif', 'heifs', 'hif', 'ico', 'jfi', 'jfif',
            'jif', 'jpe', 'jpeg', 'jpg', 'jxl', 'jxr', 'pcx', 'png', 'psb',
            'psd', 'svg', 'tga', 'tif', 'tiff', 'wdp', 'webp', 'wmf',
        ], files_only=True)

    @staticmethod
    def document():
        return SearchFilter("Document", extensions=[
            'asm', 'c', 'cc', 'chm', 'cpp', 'cs', 'css', 'csv', 'cxx', 'doc',
            'docm', 'docx', 'dot', 'dotm', 'dotx', 'efu', 'epub', 'h', 'hpp',
            'htm', 'html', 'hxx', 'ini', 'java', 'js', 'json', 'lua', 'md',
            'mht', 'mhtml', 'mobi', 'odp', 'ods', 'odt', 'ofd', 'pdf', 'php',
            'pl', 'potm', 'potx', 'ppam', 'pps', 'ppsm', 'ppsx', 'ppt',
            'pptm', 'pptx', 'ps1xml', 'pssc', 'pub', 'py', 'rtf', 'sldm',
            'sldx', 'sql', 'tsv', 'txt', 'vb', 'vsd', 'wpd', 'wps', 'wri',
            'xlam', 'xls', 'xlsb', 'xlsm', 'xlsx', 'xltm', 'xltx', 'xml',
            'xsl',
        ], files_only=True)

    @staticmethod
    def executable():
        return SearchFilter("Executable", extensions=[
            'bat', 'cmd', 'exe', 'msi', 'msp', 'msu', 'ps1', 'scr', 'vbs',
        ], files_only=True)

    @staticmethod
    def compressed():
        return SearchFilter("Compressed", extensions=[
            '7z', 'rar', 'zip',
        ], files_only=True)

    @staticmethod
    def folder():
        return SearchFilter("Folder", folders_only=True)

    @staticmethod
    def everything():
        return SearchFilter("Everything", exclude_paths=[
            '$Recycle.Bin',
        ])


# All built-in filters
BUILTIN_FILTERS = {
    'Everything': SearchFilter.everything,
    'Audio': SearchFilter.audio,
    'Compressed': SearchFilter.compressed,
    'Document': SearchFilter.document,
    'Executable': SearchFilter.executable,
    'Folder': SearchFilter.folder,
    'Image': SearchFilter.image,
    'Video': SearchFilter.video,
}


def _parse_size(size_str: str) -> int:
    """Parse a size string like '1mb', '500kb', '2gb' into bytes."""
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


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string like 'today', 'yesterday', 'lastweek', or 'YYYY-MM-DD'."""
    date_str = date_str.strip().lower()
    now = datetime.now()

    shortcuts = {
        'today': now.replace(hour=0, minute=0, second=0, microsecond=0),
        'yesterday': (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
        'thisweek': now - timedelta(days=now.weekday()),
        'lastweek': now - timedelta(days=now.weekday() + 7),
        'thismonth': now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        'lastmonth': (now.replace(day=1) - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        'thisyear': now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
        'lastyear': now.replace(year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
    }

    if date_str in shortcuts:
        return shortcuts[date_str]

    # Try common date formats
    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y'):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


@dataclass
class ParsedQuery:
    """A parsed search query with extracted modifiers."""
    terms: list[str] = field(default_factory=list)
    options: SearchOptions = field(default_factory=SearchOptions)
    # Modifier constraints
    ext_filter: list[str] = field(default_factory=list)
    size_min: int = 0
    size_max: int = 0
    date_mod_after: Optional[datetime] = None
    date_mod_before: Optional[datetime] = None
    date_create_after: Optional[datetime] = None
    date_create_before: Optional[datetime] = None
    path_includes: list[str] = field(default_factory=list)
    parent_filter: str = ""
    name_len_min: int = 0
    name_len_max: int = 0
    attrib_include: int = 0
    attrib_exclude: int = 0
    content_search: str = ""
    dupe_mode: bool = False
    or_groups: list[list[str]] = field(default_factory=list)  # OR-separated terms
    exclude_terms: list[str] = field(default_factory=list)


ATTRIB_MAP = {
    'r': 0x01, 'h': 0x02, 's': 0x04, 'd': 0x10, 'a': 0x20,
    'v': 0x40, 'n': 0x80, 't': 0x100, 'p': 0x200, 'l': 0x400,
    'c': 0x800, 'o': 0x1000, 'i': 0x2000, 'e': 0x4000,
}


def parse_query(raw_query: str, base_options: Optional[SearchOptions] = None) -> ParsedQuery:
    """
    Parse a search query string into a ParsedQuery with modifiers extracted.
    Supports Everything-compatible modifier syntax.
    """
    parsed = ParsedQuery()
    if base_options:
        parsed.options = SearchOptions(
            match_case=base_options.match_case,
            match_whole_word=base_options.match_whole_word,
            match_whole_filename=base_options.match_whole_filename,
            match_path=base_options.match_path,
            use_regex=base_options.use_regex,
            use_wildcards=base_options.use_wildcards,
            files_only=base_options.files_only,
            folders_only=base_options.folders_only,
            max_results=base_options.max_results,
            sort_by=base_options.sort_by,
            sort_order=base_options.sort_order,
        )

    if not raw_query or not raw_query.strip():
        return parsed

    query = raw_query.strip()

    # Extract quoted strings first
    quoted_parts = []
    def replace_quoted(m):
        quoted_parts.append(m.group(1))
        return f'\x00QUOTED{len(quoted_parts) - 1}\x00'

    query = re.sub(r'"([^"]*)"', replace_quoted, query)

    # Split into tokens
    tokens = query.split()
    remaining_terms = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        lower = token.lower()

        # Handle modifiers (modifier:value)
        if ':' in token:
            mod, _, val = token.partition(':')
            mod_lower = mod.lower()

            # Restore quoted values
            for j, qp in enumerate(quoted_parts):
                val = val.replace(f'\x00QUOTED{j}\x00', qp)

            if mod_lower in ('case', 'matchcase'):
                parsed.options.match_case = True
                i += 1; continue
            elif mod_lower in ('nocase', 'nomatchcase'):
                parsed.options.match_case = False
                i += 1; continue
            elif mod_lower == 'regex':
                parsed.options.use_regex = True
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower == 'noregex':
                parsed.options.use_regex = False
                i += 1; continue
            elif mod_lower in ('wildcards', 'ww'):
                parsed.options.use_wildcards = True
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower == 'nowildcards':
                parsed.options.use_wildcards = False
                i += 1; continue
            elif mod_lower in ('wholeword', 'ww'):
                parsed.options.match_whole_word = True
                i += 1; continue
            elif mod_lower == 'nowholeword':
                parsed.options.match_whole_word = False
                i += 1; continue
            elif mod_lower in ('wholefilename', 'wfn'):
                parsed.options.match_whole_filename = True
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower == 'nowholefilename':
                parsed.options.match_whole_filename = False
                i += 1; continue
            elif mod_lower == 'path':
                parsed.options.match_path = True
                if val:
                    parsed.path_includes.append(val)
                i += 1; continue
            elif mod_lower == 'nopath':
                parsed.options.match_path = False
                i += 1; continue
            elif mod_lower == 'file':
                parsed.options.files_only = True
                parsed.options.folders_only = False
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower in ('folder', 'dir'):
                parsed.options.folders_only = True
                parsed.options.files_only = False
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower == 'ext':
                if val:
                    parsed.ext_filter.extend(
                        e.strip().lstrip('.').lower() for e in val.split(';')
                    )
                i += 1; continue
            elif mod_lower == 'size':
                # size:>1mb  size:<500kb  size:100kb..1mb
                if '..' in val:
                    lo, hi = val.split('..', 1)
                    parsed.size_min = _parse_size(lo)
                    parsed.size_max = _parse_size(hi)
                elif val.startswith('>'):
                    parsed.size_min = _parse_size(val[1:])
                elif val.startswith('<'):
                    parsed.size_max = _parse_size(val[1:])
                else:
                    parsed.size_min = _parse_size(val)
                    parsed.size_max = _parse_size(val)
                i += 1; continue
            elif mod_lower in ('dm', 'datemodified'):
                if val.startswith('>'):
                    parsed.date_mod_after = _parse_date(val[1:])
                elif val.startswith('<'):
                    parsed.date_mod_before = _parse_date(val[1:])
                else:
                    parsed.date_mod_after = _parse_date(val)
                i += 1; continue
            elif mod_lower in ('dc', 'datecreated'):
                if val.startswith('>'):
                    parsed.date_create_after = _parse_date(val[1:])
                elif val.startswith('<'):
                    parsed.date_create_before = _parse_date(val[1:])
                else:
                    parsed.date_create_after = _parse_date(val)
                i += 1; continue
            elif mod_lower == 'parent':
                parsed.parent_filter = val
                i += 1; continue
            elif mod_lower == 'len':
                if '..' in val:
                    lo, hi = val.split('..', 1)
                    parsed.name_len_min = int(lo) if lo else 0
                    parsed.name_len_max = int(hi) if hi else 0
                elif val.startswith('>'):
                    parsed.name_len_min = int(val[1:]) + 1
                elif val.startswith('<'):
                    parsed.name_len_max = int(val[1:]) - 1
                else:
                    parsed.name_len_min = int(val)
                    parsed.name_len_max = int(val)
                i += 1; continue
            elif mod_lower in ('attrib', 'attributes'):
                for ch in val.lower():
                    if ch in ATTRIB_MAP:
                        parsed.attrib_include |= ATTRIB_MAP[ch]
                i += 1; continue
            elif mod_lower == 'content':
                parsed.content_search = val
                i += 1; continue
            elif mod_lower == 'dupe':
                parsed.dupe_mode = True
                i += 1; continue
            # Fall through - not a recognized modifier
            remaining_terms.append(token)
            i += 1; continue

        # Handle exclusion with ! prefix
        elif token.startswith('!') and len(token) > 1:
            parsed.exclude_terms.append(token[1:])
            i += 1; continue

        else:
            remaining_terms.append(token)
            i += 1

    # Restore quoted parts in remaining terms
    for j, qp in enumerate(quoted_parts):
        remaining_terms = [t.replace(f'\x00QUOTED{j}\x00', qp) for t in remaining_terms]

    # Process OR groups (terms separated by |)
    final_terms = []
    combined = ' '.join(remaining_terms)

    if '|' in combined:
        parts = [p.strip() for p in combined.split('|')]
        parsed.or_groups.append(parts)
    else:
        final_terms = remaining_terms

    parsed.terms = final_terms

    # Auto-detect wildcards
    if not parsed.options.use_regex:
        for term in parsed.terms:
            if '*' in term or '?' in term:
                parsed.options.use_wildcards = True
                break

    return parsed


class SearchEngine:
    """
    Executes searches against the FileIndex using parsed queries.
    """

    def __init__(self, index: FileIndex):
        self._index = index

    def search(self, query: str, active_filter: Optional[SearchFilter] = None,
               base_options: Optional[SearchOptions] = None,
               cancel_check: Optional[Callable[[], bool]] = None,
               max_results: int = 0) -> list[FileEntry]:  # noqa: C901
        """
        Execute a search and return matching FileEntry results.

        Args:
            query: Raw search query string
            active_filter: Optional active filter to apply
            base_options: Base search options (from UI toggles)
            cancel_check: Optional callable returning True to cancel
            max_results: Override max results (0 = use from options)
        """
        parsed = parse_query(query, base_options)
        if max_results:
            parsed.options.max_results = max_results

        # Apply active filter
        filter_exclude_paths = []
        if active_filter:
            if active_filter.files_only:
                parsed.options.files_only = True
            if active_filter.folders_only:
                parsed.options.folders_only = True
            if active_filter.extensions:
                parsed.ext_filter = active_filter.extensions
            if active_filter.min_size:
                parsed.size_min = active_filter.min_size
            if active_filter.max_size:
                parsed.size_max = active_filter.max_size
            if active_filter.exclude_paths:
                filter_exclude_paths = [p.lower() for p in active_filter.exclude_paths]

        # Empty query with no constraints = show everything
        has_constraints = (
            parsed.terms or parsed.or_groups or parsed.ext_filter or
            parsed.size_min or parsed.size_max or
            parsed.date_mod_after or parsed.date_mod_before or
            parsed.date_create_after or parsed.date_create_before or
            parsed.path_includes or parsed.parent_filter or
            parsed.name_len_min or parsed.name_len_max or
            parsed.attrib_include or parsed.content_search or
            parsed.dupe_mode or parsed.options.files_only or
            parsed.options.folders_only or parsed.exclude_terms
        )

        # Compile matchers
        term_matchers = self._compile_term_matchers(parsed)
        exclude_matchers = self._compile_exclude_matchers(parsed)
        or_matchers = self._compile_or_matchers(parsed)

        results = []
        entries = self._index.all_entries
        limit = parsed.options.max_results or 0

        for entry in entries:
            if cancel_check and cancel_check():
                break

            if limit and len(results) >= limit:
                break

            if self._matches(entry, parsed, term_matchers, exclude_matchers, or_matchers, filter_exclude_paths):
                results.append(entry)

        # Sort results
        if cancel_check and cancel_check():
            return results
        logger.debug(f"Search matched {len(results)} entries, sorting by {parsed.options.sort_by.name} {parsed.options.sort_order.name}")
        results = self._sort_results(results, parsed.options, cancel_check)

        return results

    def _compile_term_matchers(self, parsed: ParsedQuery) -> list:
        """Compile search terms into matcher functions."""
        matchers = []
        for term in parsed.terms:
            matchers.append(self._make_matcher(term, parsed.options))
        return matchers

    def _compile_exclude_matchers(self, parsed: ParsedQuery) -> list:
        """Compile exclusion terms into matcher functions."""
        matchers = []
        for term in parsed.exclude_terms:
            matchers.append(self._make_matcher(term, parsed.options))
        return matchers

    def _compile_or_matchers(self, parsed: ParsedQuery) -> list:
        """Compile OR groups into lists of matcher functions."""
        groups = []
        for group in parsed.or_groups:
            group_matchers = []
            for term in group:
                if term.strip():
                    group_matchers.append(self._make_matcher(term.strip(), parsed.options))
            if group_matchers:
                groups.append(group_matchers)
        return groups

    def _make_matcher(self, term: str, options: SearchOptions):
        """Create a matcher function for a single search term."""
        if options.use_regex:
            flags = 0 if options.match_case else re.IGNORECASE
            try:
                pattern = re.compile(term, flags)
                return lambda text, p=pattern: p.search(text) is not None
            except re.error:
                # Invalid regex, fall back to literal
                pass

        if options.use_wildcards or ('*' in term or '?' in term):
            if options.match_case:
                pattern = fnmatch.translate(term)
                compiled = re.compile(pattern)
                return lambda text, c=compiled: c.search(text) is not None
            else:
                pattern = fnmatch.translate(term)
                compiled = re.compile(pattern, re.IGNORECASE)
                return lambda text, c=compiled: c.search(text) is not None

        if options.match_whole_word:
            flags = 0 if options.match_case else re.IGNORECASE
            pattern = re.compile(r'\b' + re.escape(term) + r'\b', flags)
            return lambda text, p=pattern: p.search(text) is not None

        if options.match_whole_filename:
            if options.match_case:
                return lambda text, t=term: text == t
            else:
                t_lower = term.lower()
                return lambda text, t=t_lower: text.lower() == t

        # Default: case-insensitive substring
        if options.match_case:
            return lambda text, t=term: t in text
        else:
            t_lower = term.lower()
            return lambda text, t=t_lower: t in text.lower()

    def _matches(self, entry: FileEntry, parsed: ParsedQuery,
                 term_matchers: list, exclude_matchers: list,
                 or_matchers: list,
                 filter_exclude_paths: list[str] = None) -> bool:
        """Check if a FileEntry matches the parsed query."""

        # Filter exclude paths (e.g. $Recycle.Bin)
        if filter_exclude_paths:
            path = entry.get_path(self._index).lower()
            for ep in filter_exclude_paths:
                if ep in path:
                    return False

        # File/folder filter
        if parsed.options.files_only and entry.is_dir:
            return False
        if parsed.options.folders_only and not entry.is_dir:
            return False

        # Extension filter
        if parsed.ext_filter:
            if entry.is_dir:
                return False
            if entry.extension not in parsed.ext_filter:
                return False

        # Attribute filter
        if parsed.attrib_include:
            if not (entry.attributes & parsed.attrib_include):
                return False

        # Name length filter
        name_len = len(entry.name)
        if parsed.name_len_min and name_len < parsed.name_len_min:
            return False
        if parsed.name_len_max and name_len > parsed.name_len_max:
            return False

        # Date filters
        if parsed.date_mod_after and entry.date_modified:
            if entry.date_modified < parsed.date_mod_after:
                return False
        if parsed.date_mod_before and entry.date_modified:
            if entry.date_modified > parsed.date_mod_before:
                return False
        if parsed.date_create_after and entry.date_created:
            if entry.date_created < parsed.date_create_after:
                return False
        if parsed.date_create_before and entry.date_created:
            if entry.date_created > parsed.date_create_before:
                return False

        # Get match target (name or full path)
        if parsed.options.match_path or parsed.path_includes:
            target = entry.get_path(self._index)
        else:
            target = entry.name

        # Path includes filter
        if parsed.path_includes:
            path_text = target.lower()
            for pi in parsed.path_includes:
                if pi.lower() not in path_text:
                    return False

        # Parent filter
        if parsed.parent_filter:
            parent_path = self._index.resolve_parent_path(entry.drive, entry.parent_frn)
            if parsed.parent_filter.lower() not in parent_path.lower():
                return False

        # Exclusion terms (must NOT match any)
        for matcher in exclude_matchers:
            if matcher(target):
                return False

        # OR groups (must match at least one term in each group)
        for group in or_matchers:
            if not any(matcher(target) for matcher in group):
                return False

        # AND terms (must match all)
        for matcher in term_matchers:
            if not matcher(target):
                return False

        return True

    def _sort_results(self, results: list[FileEntry],
                      options: SearchOptions,
                      cancel_check: Optional[Callable[[], bool]] = None) -> list[FileEntry]:
        """Sort results by the specified field and order."""
        reverse = options.sort_order == SortOrder.DESCENDING
        sort_field = options.sort_by

        # For stat-dependent sorts, only load stats for entries that need it
        # (and only if there aren't too many — avoid blocking on millions of os.stat calls)
        if sort_field in (SortField.DATE_MODIFIED, SortField.DATE_CREATED, SortField.SIZE):
            needs_stat = sum(1 for e in results if not e._stat_loaded)
            if 0 < needs_stat <= 100_000:
                import time as _time
                t0 = _time.perf_counter()
                for i, entry in enumerate(results):
                    if cancel_check and (i & 0xFFF) == 0 and cancel_check():
                        return results
                    entry.ensure_stat(self._index)
                elapsed = (_time.perf_counter() - t0) * 1000
                logger.debug(f"Loaded stats for {needs_stat} entries (of {len(results)}) in {elapsed:.0f}ms")

        # Use minimal key functions for fast sorting
        _dt_min = datetime.min

        key_funcs = {
            SortField.NAME: lambda e: e.name.lower(),
            SortField.PATH: lambda e: e.get_path(self._index).lower(),
            SortField.SIZE: lambda e: e.size if e._stat_loaded else -1,
            SortField.EXTENSION: lambda e: e.extension,
            SortField.DATE_MODIFIED: lambda e: e.date_modified or _dt_min,
            SortField.DATE_CREATED: lambda e: e.date_created or _dt_min,
            SortField.ATTRIBUTES: lambda e: e.attributes,
        }

        key_func = key_funcs.get(sort_field, key_funcs[SortField.NAME])

        try:
            results.sort(key=key_func, reverse=reverse)
        except Exception as exc:
            logger.error(f"Sort failed: {exc}")

        return results

    def find_duplicates(self, entries: Optional[list[FileEntry]] = None) -> dict[str, list[FileEntry]]:
        """Find files with duplicate names."""
        if entries is None:
            entries = self._index.all_entries

        name_map: dict[str, list[FileEntry]] = {}
        for entry in entries:
            if not entry.is_dir:
                key = entry.name.lower()
                if key not in name_map:
                    name_map[key] = []
                name_map[key].append(entry)

        return {k: v for k, v in name_map.items() if len(v) > 1}

    def content_search(self, entry: FileEntry, search_text: str,
                       case_sensitive: bool = False) -> bool:
        """Search file content (slow - reads file from disk)."""
        try:
            path = entry.get_path(self._index)
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(1024 * 1024)  # Read up to 1MB
                if case_sensitive:
                    return search_text in content
                return search_text.lower() in content.lower()
        except (OSError, PermissionError, UnicodeDecodeError):
            return False
