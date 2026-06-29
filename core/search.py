"""
Search engine with Everything-compatible modifiers, regex, wildcards, and filters.
Routes simple queries through SQLite for speed, falls back to in-memory for complex queries.

Supports: plain text, regex:, wildcards:, case:, path:, file:, folder:,
wholeword:, wholefilename:, content:, size:, dm: (date modified),
dc: (date created), ext:, attrib:, len:, parent:, dupe:, archive:, @slot
"""

import re
import os
import fnmatch
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Optional, Callable, Mapping

from core.archives import is_supported_archive, iter_archive_entries
from core.index import FileEntry, FileIndex
from core.query_slots import expand_query_slots
from core.utils import parse_size as _parse_size

logger = logging.getLogger('QuickFind.Search')

CASE_MODE_SMART = "smart"
CASE_MODE_INSENSITIVE = "insensitive"
CASE_MODE_SENSITIVE = "sensitive"
CASE_MODES = {CASE_MODE_SMART, CASE_MODE_INSENSITIVE, CASE_MODE_SENSITIVE}


def _fuzzy_match(text: str, pattern: str) -> bool:
    """Subsequence match: all chars of pattern appear in text in order."""
    it = iter(text)
    return all(c in it for c in pattern)


class SortField(Enum):
    NAME = auto()
    PATH = auto()
    SIZE = auto()
    DATE_MODIFIED = auto()
    DATE_CREATED = auto()
    EXTENSION = auto()
    ATTRIBUTES = auto()
    RELEVANCE = auto()


class SortOrder(Enum):
    ASCENDING = auto()
    DESCENDING = auto()


@dataclass
class SearchOptions:
    """Options controlling search behavior."""
    match_case: bool = False
    case_mode: str = CASE_MODE_SMART
    match_whole_word: bool = False
    match_whole_filename: bool = False
    match_path: bool = False
    use_regex: bool = False
    use_wildcards: bool = False
    use_fuzzy: bool = False
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


@dataclass(frozen=True)
class BooleanExpression:
    """Boolean term expression for parenthesized search syntax."""
    op: str
    term: str = ""
    children: tuple['BooleanExpression', ...] = ()


BOOL_TERM = "TERM"
BOOL_AND = "AND"
BOOL_OR = "OR"
BOOL_NOT = "NOT"


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
    archive_mode: bool = False
    boolean_expression: Optional[BooleanExpression] = None
    or_groups: list[list[str]] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)
    _case_explicit: bool = False


ATTRIB_MAP = {
    'r': 0x01, 'h': 0x02, 's': 0x04, 'd': 0x10, 'a': 0x20,
    'v': 0x40, 'n': 0x80, 't': 0x100, 'p': 0x200, 'l': 0x400,
    'c': 0x800, 'o': 0x1000, 'i': 0x2000, 'e': 0x4000,
}


def _tokenize_boolean_terms(terms: list[str], quoted_parts: list[str]) -> list[str]:
    placeholder_re = re.compile(r'\x00QUOTED(\d+)\x00')
    tokens: list[str] = []

    def flush(buffer: list[str]):
        if buffer:
            tokens.append(''.join(buffer))
            buffer.clear()

    for term in terms:
        buffer: list[str] = []
        i = 0
        while i < len(term):
            placeholder = placeholder_re.match(term, i)
            if placeholder:
                flush(buffer)
                quoted_index = int(placeholder.group(1))
                tokens.append(quoted_parts[quoted_index])
                i = placeholder.end()
                continue

            ch = term[i]
            if ch in '()|':
                flush(buffer)
                tokens.append(ch)
            elif ch == '!' and not buffer:
                flush(buffer)
                tokens.append(ch)
            else:
                buffer.append(ch)
            i += 1
        flush(buffer)
    return [token for token in tokens if token]


def _parse_boolean_expression(tokens: list[str]) -> Optional[BooleanExpression]:
    if not any(token in {'|', '!', '(', ')'} for token in tokens):
        return None

    parser = _BooleanParser(tokens)
    expression = parser.parse()
    return expression


class _BooleanParser:
    def __init__(self, tokens: list[str]):
        self._tokens = tokens
        self._pos = 0

    def parse(self) -> Optional[BooleanExpression]:
        return self._parse_or()

    def _parse_or(self) -> Optional[BooleanExpression]:
        nodes = [self._parse_and()]
        while self._peek() == '|':
            self._pos += 1
            nodes.append(self._parse_and())
        nodes = [node for node in nodes if node is not None]
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
        return BooleanExpression(BOOL_OR, children=tuple(nodes))

    def _parse_and(self) -> Optional[BooleanExpression]:
        nodes = []
        while self._peek() is not None and self._peek() not in {')', '|'}:
            node = self._parse_not()
            if node is not None:
                nodes.append(node)
        if not nodes:
            return None
        if len(nodes) == 1:
            return nodes[0]
        return BooleanExpression(BOOL_AND, children=tuple(nodes))

    def _parse_not(self) -> Optional[BooleanExpression]:
        if self._peek() == '!':
            self._pos += 1
            node = self._parse_not()
            if node is None:
                return BooleanExpression(BOOL_TERM, term='!')
            return BooleanExpression(BOOL_NOT, children=(node,))
        return self._parse_primary()

    def _parse_primary(self) -> Optional[BooleanExpression]:
        token = self._peek()
        if token is None:
            return None
        if token == '(':
            self._pos += 1
            node = self._parse_or()
            if self._peek() == ')':
                self._pos += 1
            return node
        if token == ')':
            return None
        self._pos += 1
        return BooleanExpression(BOOL_TERM, term=token)

    def _peek(self) -> Optional[str]:
        if self._pos >= len(self._tokens):
            return None
        return self._tokens[self._pos]


def _boolean_expression_terms(expression: Optional[BooleanExpression]) -> list[str]:
    if expression is None:
        return []
    if expression.op == BOOL_TERM:
        return [expression.term]
    terms: list[str] = []
    for child in expression.children:
        terms.extend(_boolean_expression_terms(child))
    return terms


def _legacy_boolean_fields(expression: Optional[BooleanExpression]) -> tuple[list[str], list[str], list[list[str]]]:
    if expression is None:
        return [], [], []

    positives: list[str] = []
    excludes: list[str] = []

    def collect_and_terms(node: BooleanExpression) -> bool:
        if node.op == BOOL_TERM:
            positives.append(node.term)
            return True
        if node.op == BOOL_NOT and len(node.children) == 1 and node.children[0].op == BOOL_TERM:
            excludes.append(node.children[0].term)
            return True
        if node.op == BOOL_AND:
            return all(collect_and_terms(child) for child in node.children)
        return False

    if collect_and_terms(expression):
        return positives, excludes, []

    or_group = _legacy_or_group(expression)
    if or_group:
        return [], [], [or_group]
    return [], [], []


def _legacy_or_group(expression: BooleanExpression) -> list[str]:
    if expression.op == BOOL_TERM:
        return [expression.term]
    if expression.op == BOOL_OR:
        terms: list[str] = []
        for child in expression.children:
            child_terms = _legacy_or_group(child)
            if not child_terms:
                return []
            terms.extend(child_terms)
        return terms
    return []


def parse_query(raw_query: str, base_options: Optional[SearchOptions] = None,
                query_slots: Optional[Mapping[str, str]] = None) -> ParsedQuery:
    """Parse a search query string into a ParsedQuery with modifiers extracted."""
    if query_slots:
        raw_query = expand_query_slots(raw_query, query_slots).expanded_query

    parsed = ParsedQuery()
    if base_options:
        parsed.options = SearchOptions(
            match_case=base_options.match_case,
            case_mode=base_options.case_mode if base_options.case_mode in CASE_MODES else CASE_MODE_SMART,
            match_whole_word=base_options.match_whole_word,
            match_whole_filename=base_options.match_whole_filename,
            match_path=base_options.match_path,
            use_regex=base_options.use_regex,
            use_wildcards=base_options.use_wildcards,
            use_fuzzy=base_options.use_fuzzy,
            files_only=base_options.files_only,
            folders_only=base_options.folders_only,
            max_results=base_options.max_results,
            sort_by=base_options.sort_by,
            sort_order=base_options.sort_order,
        )

    if not raw_query or not raw_query.strip():
        return parsed

    query = raw_query.strip()

    quoted_parts = []
    def replace_quoted(m):
        quoted_parts.append(m.group(1))
        return f'\x00QUOTED{len(quoted_parts) - 1}\x00'

    query = re.sub(r'"([^"]*)"', replace_quoted, query)

    tokens = query.split()
    remaining_terms = []

    i = 0
    while i < len(tokens):
        token = tokens[i]
        lower = token.lower()

        if ':' in token:
            mod, _, val = token.partition(':')
            mod_lower = mod.lower()

            for j, qp in enumerate(quoted_parts):
                val = val.replace(f'\x00QUOTED{j}\x00', qp)

            if mod_lower in ('case', 'matchcase'):
                parsed.options.match_case = True
                parsed._case_explicit = True
                i += 1; continue
            elif mod_lower in ('nocase', 'nomatchcase'):
                parsed.options.match_case = False
                parsed._case_explicit = True
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
            elif mod_lower == 'fuzzy':
                parsed.options.use_fuzzy = True
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            elif mod_lower == 'nofuzzy':
                parsed.options.use_fuzzy = False
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
                try:
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
                except (ValueError, IndexError):
                    pass
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
            elif mod_lower == 'archive':
                parsed.archive_mode = True
                if val:
                    remaining_terms.append(val)
                i += 1; continue
            remaining_terms.append(token)
            i += 1; continue

        elif token.startswith('!') and len(token) > 1:
            remaining_terms.append(token)
            i += 1; continue

        else:
            remaining_terms.append(token)
            i += 1

    boolean_tokens = _tokenize_boolean_terms(remaining_terms, quoted_parts)
    boolean_expression = _parse_boolean_expression(boolean_tokens)

    if boolean_expression is not None:
        parsed.boolean_expression = boolean_expression
        parsed.terms, parsed.exclude_terms, parsed.or_groups = _legacy_boolean_fields(boolean_expression)
    else:
        for j, qp in enumerate(quoted_parts):
            remaining_terms = [t.replace(f'\x00QUOTED{j}\x00', qp) for t in remaining_terms]
        parsed.terms = remaining_terms

    if not parsed.options.use_regex:
        for term in parsed.terms:
            if '*' in term or '?' in term:
                parsed.options.use_wildcards = True
                break

    if not parsed._case_explicit:
        if parsed.options.case_mode == CASE_MODE_SENSITIVE:
            parsed.options.match_case = True
        elif parsed.options.case_mode == CASE_MODE_INSENSITIVE:
            parsed.options.match_case = False
        elif not parsed.options.match_case:
            all_text = ' '.join(
                parsed.terms
                + [t for g in parsed.or_groups for t in g]
                + _boolean_expression_terms(parsed.boolean_expression)
            )
            if any(c.isupper() for c in all_text):
                parsed.options.match_case = True

    return parsed


# ── Sort field mapping for DB queries ────────────────────

_SORT_FIELD_TO_DB = {
    SortField.NAME: 'name',
    SortField.PATH: 'path',
    SortField.SIZE: 'size',
    SortField.DATE_MODIFIED: 'date_modified_ms',
    SortField.DATE_CREATED: 'date_created_ms',
    SortField.EXTENSION: 'name',
    SortField.ATTRIBUTES: 'attributes',
}


def _dt_to_ms(dt: Optional[datetime]) -> int:
    if dt is None:
        return 0
    try:
        return int(dt.timestamp() * 1000)
    except (OSError, OverflowError, ValueError):
        return 0


def _ms_to_dt(ms: int) -> Optional[datetime]:
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0)
    except (OSError, OverflowError, ValueError):
        return None


class SearchEngine:
    """
    Executes searches against the FileIndex.
    Routes simple queries through SQLite DB for speed.
    Falls back to in-memory iteration for complex queries.
    """

    def __init__(self, index: FileIndex):
        self._index = index

    def _can_use_db(self, parsed: ParsedQuery) -> bool:
        """Check if the query can be executed via DB search."""
        # These features require in-memory processing
        if parsed.options.use_regex:
            return False
        if parsed.options.match_case:
            return False
        if parsed.options.match_whole_word:
            return False
        if parsed.options.match_whole_filename:
            return False
        if parsed.options.use_wildcards:
            return False
        if parsed.options.use_fuzzy:
            return False
        if parsed.content_search:
            return False
        if parsed.dupe_mode:
            return False
        if parsed.archive_mode:
            return False
        if parsed.boolean_expression:
            return False
        if parsed.or_groups:
            return False
        if parsed.attrib_include:
            return False
        if parsed.name_len_min or parsed.name_len_max:
            return False
        if parsed.parent_filter:
            return False

        # Multiple search terms need AND logic — DB can handle one
        if len(parsed.terms) > 1:
            return False

        from core.cache import cache_exists
        return cache_exists()

    def _db_search(self, parsed: ParsedQuery,
                   active_filter: Optional[SearchFilter],
                   limit: int = 0, offset: int = 0) -> list[FileEntry]:
        """Execute search via SQLite database."""
        from core.cache import db_search

        query_text = parsed.terms[0] if parsed.terms else ""

        extensions = parsed.ext_filter
        if active_filter and active_filter.extensions:
            extensions = active_filter.extensions

        files_only = parsed.options.files_only or (active_filter and active_filter.files_only)
        folders_only = parsed.options.folders_only or (active_filter and active_filter.folders_only)

        size_min = parsed.size_min or (active_filter.min_size if active_filter else 0)
        size_max = parsed.size_max or (active_filter.max_size if active_filter else 0)

        exclude_paths = []
        if active_filter and active_filter.exclude_paths:
            exclude_paths = active_filter.exclude_paths

        # Path includes
        match_path = parsed.options.match_path
        if parsed.path_includes:
            match_path = True
            if not query_text and parsed.path_includes:
                query_text = parsed.path_includes[0]

        sort_col = _SORT_FIELD_TO_DB.get(parsed.options.sort_by, 'date_modified_ms')
        sort_desc = parsed.options.sort_order == SortOrder.DESCENDING

        rows, _ = db_search(
            query=query_text,
            match_path=match_path,
            extensions=extensions if extensions else None,
            files_only=files_only,
            folders_only=folders_only,
            size_min=size_min,
            size_max=size_max,
            date_mod_after_ms=_dt_to_ms(parsed.date_mod_after),
            date_mod_before_ms=_dt_to_ms(parsed.date_mod_before),
            date_create_after_ms=_dt_to_ms(parsed.date_create_after),
            date_create_before_ms=_dt_to_ms(parsed.date_create_before),
            exclude_paths=exclude_paths if exclude_paths else None,
            limit=limit,
            offset=offset,
            sort_column=sort_col,
            sort_desc=sort_desc,
        )

        # Convert DB rows to FileEntry objects
        results = []
        for row in rows:
            frn, drive, parent_frn, name, path, attrs, size, mtime_ms, ctime_ms = row[:9]
            reparse_tag = row[9] if len(row) > 9 else 0
            has_ea = row[10] if len(row) > 10 else 0
            # Try to get from in-memory index first (has full state)
            existing = self._index.get_entry(drive, frn)
            if existing:
                results.append(existing)
            else:
                entry = FileEntry(
                    frn=frn, parent_frn=parent_frn, name=name,
                    drive=drive, attributes=attrs, reparse_tag=reparse_tag,
                    has_extended_attributes=bool(has_ea),
                )
                if path:
                    entry._path = path
                if size or mtime_ms or ctime_ms:
                    entry.size = size
                    entry.date_modified = _ms_to_dt(mtime_ms)
                    entry.date_created = _ms_to_dt(ctime_ms)
                    entry._stat_loaded = True
                results.append(entry)

        # Apply exclude terms in Python (simple post-filter)
        if parsed.exclude_terms:
            exclude_matchers = self._compile_exclude_matchers(parsed)
            results = [e for e in results if not any(m(e.name) for m in exclude_matchers)]

        return results

    def search(self, query: str, active_filter: Optional[SearchFilter] = None,
               base_options: Optional[SearchOptions] = None,
               cancel_check: Optional[Callable[[], bool]] = None,
               max_results: int = 0,
               query_slots: Optional[Mapping[str, str]] = None) -> list[FileEntry]:
        """Execute a search and return matching FileEntry results."""
        parsed = parse_query(query, base_options, query_slots=query_slots)
        if max_results:
            parsed.options.max_results = max_results

        # Apply active filter
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

        # Try DB search first for simple queries
        if self._can_use_db(parsed):
            try:
                limit = parsed.options.max_results or 0
                results = self._db_search(parsed, active_filter, limit=limit)
                if results is not None:
                    logger.debug(f"DB search returned {len(results)} results")
                    return results
            except Exception as e:
                logger.debug(f"DB search failed, falling back to in-memory: {e}")

        # Fall back to in-memory search
        return self._memory_search(parsed, active_filter, cancel_check)

    def _memory_search(self, parsed: ParsedQuery,
                       active_filter: Optional[SearchFilter],
                       cancel_check: Optional[Callable[[], bool]] = None) -> list[FileEntry]:
        """In-memory search (original implementation)."""
        filter_exclude_paths = []
        if active_filter and active_filter.exclude_paths:
            filter_exclude_paths = [p.lower() for p in active_filter.exclude_paths]

        term_matchers = self._compile_term_matchers(parsed)
        exclude_matchers = self._compile_exclude_matchers(parsed)
        or_matchers = self._compile_or_matchers(parsed)
        boolean_matcher = self._compile_boolean_matcher(parsed)

        if parsed.archive_mode:
            return self._archive_search(
                parsed, term_matchers, exclude_matchers, or_matchers,
                filter_exclude_paths, cancel_check, boolean_matcher,
            )

        results = []
        entries = self._index.all_entries
        limit = parsed.options.max_results or 0
        content_cache = self._content_cache_filter(parsed)
        parsed_without_content = replace(parsed, content_search="") if content_cache else parsed

        for entry in entries:
            if cancel_check and cancel_check():
                break

            if limit and not parsed.dupe_mode and len(results) >= limit:
                break

            entry_parsed = parsed
            if content_cache:
                entry.content_snippet = ""
                entry.content_rank = 0.0
                path_key = self._content_path_key(entry)
                freshness = content_cache['freshness'].get(path_key)
                if freshness and self._content_entry_cache_is_fresh(entry, freshness):
                    hit = content_cache['hits'].get(path_key)
                    if hit is None:
                        continue
                    entry.content_snippet = hit.snippet
                    entry.content_rank = hit.rank
                    entry_parsed = parsed_without_content
            else:
                entry.content_snippet = ""
                entry.content_rank = 0.0

            if self._matches(
                entry, entry_parsed, term_matchers, exclude_matchers,
                or_matchers, filter_exclude_paths, boolean_matcher,
            ):
                results.append(entry)

        if cancel_check and cancel_check():
            return results

        if parsed.dupe_mode:
            results = self._filter_duplicate_results(results)

        results = self._sort_results(results, parsed.options, cancel_check)
        if content_cache:
            results.sort(key=lambda entry: entry.content_rank, reverse=True)
        if parsed.dupe_mode and limit:
            results = results[:limit]

        return results

    def _content_cache_filter(self, parsed: ParsedQuery) -> Optional[dict]:
        if not parsed.content_search:
            return None
        try:
            from core.cache import get_content_cache_freshness, search_content_cache_hits
            freshness = get_content_cache_freshness()
            if not freshness:
                return None
            hits = search_content_cache_hits(
                parsed.content_search,
                parsed.options.match_case,
            )
            return {
                'freshness': {
                    self._normalize_path_key(path): meta
                    for path, meta in freshness.items()
                },
                'hits': {
                    self._normalize_path_key(hit.path): hit
                    for hit in hits
                },
            }
        except Exception as exc:
            logger.debug(f"Content cache filter unavailable: {exc}")
            return None

    def _content_entry_cache_is_fresh(self, entry: FileEntry,
                                      freshness: tuple[int, int]) -> bool:
        try:
            path = entry.get_path(self._index)
            st = os.stat(path)
            return freshness == (st.st_size, int(st.st_mtime * 1000))
        except (OSError, PermissionError):
            return False

    def _content_path_key(self, entry: FileEntry) -> str:
        try:
            return self._normalize_path_key(entry.get_path(self._index))
        except Exception:
            return ""

    @staticmethod
    def _normalize_path_key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def _archive_search(self, parsed: ParsedQuery,
                        term_matchers: list,
                        exclude_matchers: list,
                        or_matchers: list,
                        filter_exclude_paths: list[str],
                        cancel_check: Optional[Callable[[], bool]] = None,
                        boolean_matcher: Optional[Callable[[str], bool]] = None) -> list[FileEntry]:
        results = []
        limit = parsed.options.max_results or 0

        for archive_entry in self._index.all_entries:
            if cancel_check and cancel_check():
                break

            if limit and not parsed.dupe_mode and len(results) >= limit:
                break

            if not is_supported_archive(archive_entry):
                continue

            if filter_exclude_paths:
                archive_path = archive_entry.get_path(self._index).lower()
                if any(excluded in archive_path for excluded in filter_exclude_paths):
                    continue

            for entry in iter_archive_entries(archive_entry, self._index):
                if cancel_check and cancel_check():
                    break

                if limit and not parsed.dupe_mode and len(results) >= limit:
                    break

                if self._matches(
                    entry, parsed, term_matchers, exclude_matchers,
                    or_matchers, [], boolean_matcher,
                ):
                    results.append(entry)

        if cancel_check and cancel_check():
            return results

        if parsed.dupe_mode:
            results = self._filter_duplicate_results(results)

        results = self._sort_results(results, parsed.options, cancel_check)
        if parsed.dupe_mode and limit:
            results = results[:limit]

        return results

    def _filter_duplicate_results(self, entries: list[FileEntry]) -> list[FileEntry]:
        duplicates = self.find_duplicates(entries)
        if not duplicates:
            return []
        duplicate_names = set(duplicates)
        return [
            entry for entry in entries
            if not entry.is_dir and entry.name.lower() in duplicate_names
        ]

    def _compile_term_matchers(self, parsed: ParsedQuery) -> list:
        matchers = []
        for term in parsed.terms:
            matchers.append(self._make_matcher(term, parsed.options))
        return matchers

    def _compile_exclude_matchers(self, parsed: ParsedQuery) -> list:
        matchers = []
        for term in parsed.exclude_terms:
            matchers.append(self._make_matcher(term, parsed.options))
        return matchers

    def _compile_or_matchers(self, parsed: ParsedQuery) -> list:
        groups = []
        for group in parsed.or_groups:
            group_matchers = []
            for term in group:
                if term.strip():
                    group_matchers.append(self._make_matcher(term.strip(), parsed.options))
            if group_matchers:
                groups.append(group_matchers)
        return groups

    def _compile_boolean_matcher(self, parsed: ParsedQuery) -> Optional[Callable[[str], bool]]:
        if parsed.boolean_expression is None:
            return None
        return self._compile_boolean_node(parsed.boolean_expression, parsed.options)

    def _compile_boolean_node(self, expression: BooleanExpression,
                              options: SearchOptions) -> Callable[[str], bool]:
        if expression.op == BOOL_TERM:
            return self._make_matcher(expression.term, options)
        if expression.op == BOOL_NOT:
            child = self._compile_boolean_node(expression.children[0], options)
            return lambda text, child=child: not child(text)
        if expression.op == BOOL_OR:
            children = [
                self._compile_boolean_node(child, options)
                for child in expression.children
            ]
            return lambda text, children=children: any(child(text) for child in children)

        children = [
            self._compile_boolean_node(child, options)
            for child in expression.children
        ]
        return lambda text, children=children: all(child(text) for child in children)

    def _make_matcher(self, term: str, options: SearchOptions):
        if options.use_regex:
            flags = 0 if options.match_case else re.IGNORECASE
            try:
                pattern = re.compile(term, flags)
                return lambda text, p=pattern: p.search(text) is not None
            except re.error:
                return lambda text: False

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

        if options.use_fuzzy:
            if options.match_case:
                return lambda text, t=term: _fuzzy_match(text, t)
            else:
                t_lower = term.lower()
                return lambda text, t=t_lower: _fuzzy_match(text.lower(), t)

        if options.match_case:
            return lambda text, t=term: t in text
        else:
            t_lower = term.lower()
            return lambda text, t=t_lower: t in text.lower()

    def _matches(self, entry: FileEntry, parsed: ParsedQuery,
                 term_matchers: list, exclude_matchers: list,
                 or_matchers: list,
                 filter_exclude_paths: list[str] = None,
                 boolean_matcher: Optional[Callable[[str], bool]] = None) -> bool:

        if filter_exclude_paths:
            path = entry.get_path(self._index).lower()
            for ep in filter_exclude_paths:
                if ep in path:
                    return False

        if parsed.options.files_only and entry.is_dir:
            return False
        if parsed.options.folders_only and not entry.is_dir:
            return False

        if parsed.ext_filter:
            if entry.is_dir:
                return False
            if entry.extension not in parsed.ext_filter:
                return False

        if parsed.size_min or parsed.size_max:
            entry.ensure_stat(self._index)
            if parsed.size_min and entry.size < parsed.size_min:
                return False
            if parsed.size_max and entry.size > parsed.size_max:
                return False

        if parsed.attrib_include:
            if not (entry.attributes & parsed.attrib_include):
                return False

        name_len = len(entry.name)
        if parsed.name_len_min and name_len < parsed.name_len_min:
            return False
        if parsed.name_len_max and name_len > parsed.name_len_max:
            return False

        if parsed.date_mod_after:
            if not entry.date_modified or entry.date_modified < parsed.date_mod_after:
                return False
        if parsed.date_mod_before:
            if not entry.date_modified or entry.date_modified > parsed.date_mod_before:
                return False
        if parsed.date_create_after:
            if not entry.date_created or entry.date_created < parsed.date_create_after:
                return False
        if parsed.date_create_before:
            if not entry.date_created or entry.date_created > parsed.date_create_before:
                return False

        if parsed.options.match_path or parsed.path_includes:
            target = entry.get_path(self._index)
        else:
            target = entry.name

        if parsed.path_includes:
            path_text = target.lower()
            for pi in parsed.path_includes:
                if pi.lower() not in path_text:
                    return False

        if parsed.parent_filter:
            parent_path = os.path.dirname(entry.get_path(self._index))
            if parsed.parent_filter.lower() not in parent_path.lower():
                return False

        if boolean_matcher is not None:
            if not boolean_matcher(target):
                return False
        else:
            for matcher in exclude_matchers:
                if matcher(target):
                    return False

            for group in or_matchers:
                if not any(matcher(target) for matcher in group):
                    return False

            for matcher in term_matchers:
                if not matcher(target):
                    return False

        if parsed.content_search and not entry.is_dir:
            if not self.content_search(entry, parsed.content_search, parsed.options.match_case):
                return False

        return True

    def _sort_results(self, results: list[FileEntry],
                      options: SearchOptions,
                      cancel_check: Optional[Callable[[], bool]] = None) -> list[FileEntry]:
        reverse = options.sort_order == SortOrder.DESCENDING
        sort_field = options.sort_by

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

        if sort_field == SortField.RELEVANCE:
            from core.cache import get_usage_scores
            paths = [e.get_path(self._index) for e in results]
            scores = get_usage_scores(paths)
            results.sort(key=lambda e: scores.get(e.get_path(self._index), 0), reverse=True)
            return results

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
        try:
            path = entry.get_path(self._index)
            from core.content import extract_text, is_supported_content_path
            from core.cache import get_content_cache, upsert_content_cache

            if not is_supported_content_path(path):
                return False

            st = os.stat(path)
            size = st.st_size
            modified_ms = int(st.st_mtime * 1000)
            content = get_content_cache(path, size, modified_ms)
            if content is None:
                extracted = extract_text(path)
                if extracted is None:
                    return False
                content = extracted.text
                upsert_content_cache(
                    path=path,
                    size=size,
                    modified_ms=modified_ms,
                    extractor=extracted.extractor,
                    text=content,
                )

            if case_sensitive:
                return search_text in content
            return search_text.lower() in content.lower()
        except (OSError, PermissionError, UnicodeDecodeError):
            return False
