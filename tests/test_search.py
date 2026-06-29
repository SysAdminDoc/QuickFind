"""Tests for core.search — query parsing, size/date helpers, smart case."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta
from core.utils import parse_size as _parse_size
from core.search import (
    _parse_date, _fuzzy_match, parse_query, SearchOptions, SearchFilter,
    ParsedQuery, SearchEngine, SortField, SortOrder, ATTRIB_MAP,
    CASE_MODE_INSENSITIVE, CASE_MODE_SENSITIVE,
)
from core.index import FileEntry
from core.ntfs import FILE_ATTRIBUTE_REPARSE_POINT
import core.search as search_module


class TestParseSize:
    def test_bytes(self):
        assert _parse_size("1024") == 1024

    def test_bytes_suffix(self):
        assert _parse_size("512b") == 512

    def test_kilobytes(self):
        assert _parse_size("1kb") == 1024

    def test_kilobytes_short(self):
        assert _parse_size("1k") == 1024

    def test_megabytes(self):
        assert _parse_size("1mb") == 1024 ** 2

    def test_gigabytes(self):
        assert _parse_size("2gb") == 2 * 1024 ** 3

    def test_terabytes(self):
        assert _parse_size("1tb") == 1024 ** 4

    def test_float(self):
        assert _parse_size("1.5mb") == int(1.5 * 1024 ** 2)

    def test_whitespace(self):
        assert _parse_size("  100kb  ") == 100 * 1024

    def test_case_insensitive(self):
        assert _parse_size("1MB") == 1024 ** 2
        assert _parse_size("1Gb") == 1024 ** 3

    def test_empty(self):
        assert _parse_size("") == 0

    def test_invalid(self):
        assert _parse_size("abc") == 0

    def test_zero(self):
        assert _parse_size("0") == 0


class TestParseDate:
    def test_today(self):
        result = _parse_date("today")
        assert result is not None
        now = datetime.now()
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day
        assert result.hour == 0

    def test_yesterday(self):
        result = _parse_date("yesterday")
        expected = datetime.now() - timedelta(days=1)
        assert result is not None
        assert result.day == expected.day

    def test_thisweek(self):
        result = _parse_date("thisweek")
        assert result is not None
        assert result <= datetime.now()

    def test_thismonth(self):
        result = _parse_date("thismonth")
        assert result is not None
        assert result.day == 1

    def test_thisyear(self):
        result = _parse_date("thisyear")
        assert result is not None
        assert result.month == 1
        assert result.day == 1

    def test_iso_format(self):
        result = _parse_date("2024-06-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_slash_format(self):
        result = _parse_date("2024/01/01")
        assert result is not None
        assert result.year == 2024

    def test_invalid(self):
        assert _parse_date("notadate") is None

    def test_empty(self):
        assert _parse_date("") is None


class TestParseQuery:
    def test_empty(self):
        parsed = parse_query("")
        assert parsed.terms == []

    def test_simple_term(self):
        parsed = parse_query("hello")
        assert parsed.terms == ["hello"]

    def test_multiple_terms(self):
        parsed = parse_query("hello world")
        assert parsed.terms == ["hello", "world"]

    def test_quoted_phrase(self):
        parsed = parse_query('"hello world"')
        assert parsed.terms == ["hello world"]

    def test_regex_modifier(self):
        parsed = parse_query("regex:test.*py")
        assert parsed.options.use_regex is True
        assert parsed.terms == ["test.*py"]

    def test_case_modifier(self):
        parsed = parse_query("case:FooBar")
        assert parsed.options.match_case is True
        assert parsed._case_explicit is True

    def test_nocase_modifier(self):
        parsed = parse_query("nocase: hello")
        assert parsed.options.match_case is False
        assert parsed._case_explicit is True

    def test_file_modifier(self):
        parsed = parse_query("file:")
        assert parsed.options.files_only is True

    def test_folder_modifier(self):
        parsed = parse_query("folder:")
        assert parsed.options.folders_only is True

    def test_ext_modifier(self):
        parsed = parse_query("ext:py;js;ts")
        assert parsed.ext_filter == ["py", "js", "ts"]

    def test_ext_with_dots(self):
        parsed = parse_query("ext:.py;.js")
        assert parsed.ext_filter == ["py", "js"]

    def test_size_greater(self):
        parsed = parse_query("size:>1mb")
        assert parsed.size_min == 1024 ** 2

    def test_size_less(self):
        parsed = parse_query("size:<100kb")
        assert parsed.size_max == 100 * 1024

    def test_size_range(self):
        parsed = parse_query("size:1mb..10mb")
        assert parsed.size_min == 1024 ** 2
        assert parsed.size_max == 10 * 1024 ** 2

    def test_date_modified_after(self):
        parsed = parse_query("dm:>2024-01-01")
        assert parsed.date_mod_after is not None
        assert parsed.date_mod_after.year == 2024

    def test_date_modified_shortcut(self):
        parsed = parse_query("dm:today")
        assert parsed.date_mod_after is not None

    def test_date_created(self):
        parsed = parse_query("dc:thisweek")
        assert parsed.date_create_after is not None

    def test_path_modifier(self):
        parsed = parse_query("path:src\\utils")
        assert parsed.options.match_path is True
        assert parsed.path_includes == ["src\\utils"]

    def test_parent_modifier(self):
        parsed = parse_query("parent:node_modules")
        assert parsed.parent_filter == "node_modules"

    def test_len_greater(self):
        parsed = parse_query("len:>20")
        assert parsed.name_len_min == 21

    def test_len_less(self):
        parsed = parse_query("len:<10")
        assert parsed.name_len_max == 9

    def test_len_range(self):
        parsed = parse_query("len:5..15")
        assert parsed.name_len_min == 5
        assert parsed.name_len_max == 15

    def test_len_invalid_value(self):
        parsed = parse_query("len:abc")
        assert parsed.name_len_min == 0
        assert parsed.name_len_max == 0

    def test_len_empty(self):
        parsed = parse_query("len:")
        assert parsed.name_len_min == 0
        assert parsed.name_len_max == 0

    def test_attrib_modifier(self):
        parsed = parse_query("attrib:hs")
        expected = ATTRIB_MAP['h'] | ATTRIB_MAP['s']
        assert parsed.attrib_include == expected

    def test_content_modifier(self):
        parsed = parse_query("content:TODO")
        assert parsed.content_search == "TODO"

    def test_dupe_modifier(self):
        parsed = parse_query("dupe:")
        assert parsed.dupe_mode is True

    def test_duplicate_hash_modifier(self):
        parsed = parse_query("duplicate:hash")
        assert parsed.dupe_mode is True
        assert parsed.dupe_hash_mode is True

    def test_broken_modifiers(self):
        link = parse_query("broken:link")
        shortcut = parse_query("broken:shortcut")

        assert link.broken_link_mode is True
        assert shortcut.broken_shortcut_mode is True

    def test_archive_modifier(self):
        parsed = parse_query("archive:report")
        assert parsed.archive_mode is True
        assert parsed.terms == ["report"]

    def test_exclude_term(self):
        parsed = parse_query("hello !temp")
        assert parsed.terms == ["hello"]
        assert parsed.exclude_terms == ["temp"]

    def test_or_operator(self):
        parsed = parse_query("hello | world")
        assert parsed.or_groups == [["hello", "world"]]
        assert parsed.terms == []
        assert parsed.boolean_expression is not None

    def test_nested_parentheses_create_boolean_expression(self):
        parsed = parse_query("alpha (beta | gamma) !tmp")

        assert parsed.boolean_expression is not None
        assert parsed.terms == []
        assert parsed.exclude_terms == []

    def test_regex_invalid_pattern(self):
        parsed = parse_query("regex:[invalid")
        assert parsed.options.use_regex is True
        assert parsed.terms == ["[invalid"]

    def test_wildcard_autodetect(self):
        parsed = parse_query("*.py")
        assert parsed.options.use_wildcards is True

    def test_wildcards_modifier(self):
        parsed = parse_query("wildcards:test*")
        assert parsed.options.use_wildcards is True

    def test_wholeword_modifier(self):
        parsed = parse_query("wholeword: test")
        assert parsed.options.match_whole_word is True

    def test_wholefilename_modifier(self):
        parsed = parse_query("wholefilename:readme.txt")
        assert parsed.options.match_whole_filename is True

    def test_combined_modifiers(self):
        parsed = parse_query("ext:py size:>1kb dm:today hello")
        assert parsed.ext_filter == ["py"]
        assert parsed.size_min == 1024
        assert parsed.date_mod_after is not None
        assert parsed.terms == ["hello"]

    def test_base_options_preserved(self):
        base = SearchOptions(files_only=True, sort_by=SortField.SIZE)
        parsed = parse_query("test", base)
        assert parsed.options.files_only is True
        assert parsed.options.sort_by == SortField.SIZE

    def test_size_exact(self):
        parsed = parse_query("size:1024")
        assert parsed.size_min == 1024
        assert parsed.size_max == 1024

    def test_date_modified_before(self):
        parsed = parse_query("dm:<2025-01-01")
        assert parsed.date_mod_before is not None
        assert parsed.date_mod_before.year == 2025

    def test_date_created_before(self):
        parsed = parse_query("dc:<2025-06-01")
        assert parsed.date_create_before is not None

    def test_content_modifier_value(self):
        parsed = parse_query("content:class hello")
        assert parsed.content_search == "class"
        assert parsed.terms == ["hello"]

    def test_query_slot_expands_before_modifier_parse(self):
        parsed = parse_query(
            "@logs error",
            query_slots={"logs": "ext:log dm:today"},
        )

        assert parsed.ext_filter == ["log"]
        assert parsed.date_mod_after is not None
        assert parsed.terms == ["error"]


class TestSmartCase:
    def test_lowercase_is_insensitive(self):
        parsed = parse_query("hello")
        assert parsed.options.match_case is False

    def test_uppercase_triggers_sensitive(self):
        parsed = parse_query("Hello")
        assert parsed.options.match_case is True

    def test_mixed_case_triggers_sensitive(self):
        parsed = parse_query("helloWorld")
        assert parsed.options.match_case is True

    def test_all_upper_triggers_sensitive(self):
        parsed = parse_query("README")
        assert parsed.options.match_case is True

    def test_explicit_case_overrides_smart(self):
        parsed = parse_query("case: hello")
        assert parsed.options.match_case is True

    def test_explicit_nocase_overrides_smart(self):
        parsed = parse_query("nocase: Hello")
        assert parsed.options.match_case is False

    def test_smart_case_with_or_groups(self):
        parsed = parse_query("Hello | World")
        assert parsed.options.match_case is True

    def test_smart_case_no_terms(self):
        parsed = parse_query("ext:py")
        assert parsed.options.match_case is False

    def test_modifier_value_not_counted(self):
        parsed = parse_query("ext:PY")
        assert parsed.options.match_case is False

    def test_case_insensitive_index_mode_overrides_smart_case(self):
        parsed = parse_query(
            "Hello",
            SearchOptions(case_mode=CASE_MODE_INSENSITIVE),
        )
        assert parsed.options.match_case is False

    def test_case_sensitive_index_mode_matches_lowercase_case_sensitively(self):
        parsed = parse_query(
            "hello",
            SearchOptions(case_mode=CASE_MODE_SENSITIVE),
        )
        assert parsed.options.match_case is True

    def test_explicit_case_modifiers_override_index_case_mode(self):
        sensitive = parse_query(
            "case: hello",
            SearchOptions(case_mode=CASE_MODE_INSENSITIVE),
        )
        insensitive = parse_query(
            "nocase: Hello",
            SearchOptions(case_mode=CASE_MODE_SENSITIVE),
        )

        assert sensitive.options.match_case is True
        assert insensitive.options.match_case is False


class TestSearchFilter:
    def test_audio_filter(self):
        f = SearchFilter.audio()
        assert f.name == "Audio"
        assert "mp3" in f.extensions
        assert f.files_only is True

    def test_video_filter(self):
        f = SearchFilter.video()
        assert "mp4" in f.extensions

    def test_image_filter(self):
        f = SearchFilter.image()
        assert "png" in f.extensions

    def test_document_filter(self):
        f = SearchFilter.document()
        assert "pdf" in f.extensions

    def test_executable_filter(self):
        f = SearchFilter.executable()
        assert "exe" in f.extensions

    def test_compressed_filter(self):
        f = SearchFilter.compressed()
        assert "zip" in f.extensions

    def test_folder_filter(self):
        f = SearchFilter.folder()
        assert f.folders_only is True

    def test_everything_filter(self):
        f = SearchFilter.everything()
        assert "$Recycle.Bin" in f.exclude_paths


class TestFuzzyMatch:
    def test_exact_match(self):
        assert _fuzzy_match("QuickFind", "QuickFind") is True

    def test_subsequence(self):
        assert _fuzzy_match("quickfind", "qckfnd") is True

    def test_typo_pattern(self):
        assert _fuzzy_match("quickfind", "qickfind") is True

    def test_no_match(self):
        assert _fuzzy_match("quickfind", "xyz") is False

    def test_empty_pattern(self):
        assert _fuzzy_match("anything", "") is True

    def test_empty_text(self):
        assert _fuzzy_match("", "abc") is False

    def test_wrong_order(self):
        assert _fuzzy_match("abc", "cba") is False

    def test_fuzzy_modifier(self):
        parsed = parse_query("fuzzy:qickfind")
        assert parsed.options.use_fuzzy is True
        assert parsed.terms == ["qickfind"]

    def test_nofuzzy_modifier(self):
        parsed = parse_query("nofuzzy: test")
        assert parsed.options.use_fuzzy is False


class TestSearchOptions:
    def test_defaults(self):
        opts = SearchOptions()
        assert opts.match_case is False
        assert opts.use_regex is False
        assert opts.files_only is False
        assert opts.folders_only is False
        assert opts.max_results == 0
        assert opts.sort_by == SortField.DATE_MODIFIED
        assert opts.sort_order == SortOrder.DESCENDING


class FakeIndex:
    def __init__(self, entries):
        self.all_entries = entries

    def resolve_path(self, drive: str, frn: int) -> str:
        return f"{drive}:\\fake\\{frn}"

    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        return f"{drive}:\\fake"


class PathIndex(FakeIndex):
    def __init__(self, entries, paths):
        super().__init__(entries)
        self._paths = paths

    def resolve_path(self, drive: str, frn: int) -> str:
        return str(self._paths[frn])

    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        return str(next(iter(self._paths.values())).parent)


def _entry(name: str, frn: int, attributes: int = 0) -> FileEntry:
    return FileEntry(frn=frn, parent_frn=5, name=name, drive="C", attributes=attributes)


class TestDupeSearch:
    def test_dupe_modifier_returns_duplicate_filenames(self):
        entries = [
            _entry("report.txt", 1),
            _entry("report.txt", 2),
            _entry("unique.txt", 3),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search("dupe:")

        assert [entry.frn for entry in results] == [1, 2]

    def test_dupe_modifier_respects_terms_before_grouping(self):
        entries = [
            _entry("report.txt", 1),
            _entry("report.txt", 2),
            _entry("budget.txt", 3),
            _entry("budget.txt", 4),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search("dupe: report")

        assert [entry.frn for entry in results] == [1, 2]

    def test_dupe_modifier_respects_extension_filter(self):
        entries = [
            _entry("report.txt", 1),
            _entry("report.txt", 2),
            _entry("report.md", 3),
            _entry("report.md", 4),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search("dupe: ext:txt")

        assert [entry.frn for entry in results] == [1, 2]

    def test_dupe_modifier_applies_limit_after_duplicate_filtering(self):
        entries = [
            _entry("alpha.txt", 1),
            _entry("alpha.txt", 2),
            _entry("beta.txt", 3),
            _entry("beta.txt", 4),
        ]
        engine = SearchEngine(FakeIndex(entries))
        options = SearchOptions(
            max_results=1,
            sort_by=SortField.NAME,
            sort_order=SortOrder.ASCENDING,
        )

        results = engine.search("dupe:", base_options=options)

        assert len(results) == 1
        assert results[0].name == "alpha.txt"

    def test_duplicate_hash_returns_same_content_with_different_names(self, tmp_path):
        first = tmp_path / "alpha.txt"
        second = tmp_path / "beta.txt"
        third = tmp_path / "same-size.txt"
        first.write_bytes(b"same content")
        second.write_bytes(b"same content")
        third.write_bytes(b"other bytes!")
        entries = [
            _entry(first.name, 1),
            _entry(second.name, 2),
            _entry(third.name, 3),
        ]
        engine = SearchEngine(PathIndex(entries, {
            1: first,
            2: second,
            3: third,
        }))

        results = engine.search(
            "duplicate:hash ext:txt",
            base_options=SearchOptions(
                sort_by=SortField.NAME,
                sort_order=SortOrder.ASCENDING,
            ),
        )

        assert [entry.name for entry in results] == ["alpha.txt", "beta.txt"]


class TestQuerySlotSearch:
    def test_search_expands_query_slots_before_matching(self):
        entries = [
            _entry("app.log", 1),
            _entry("app.txt", 2),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search(
            "@logs app",
            base_options=SearchOptions(match_case=True),
            query_slots={"logs": "ext:log"},
        )

        assert [entry.name for entry in results] == ["app.log"]


class TestBooleanExpressionSearch:
    def test_nested_parentheses_apply_implicit_and(self):
        entries = [
            _entry("alpha-beta.txt", 1),
            _entry("alpha-gamma.txt", 2),
            _entry("beta-only.txt", 3),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search(
            "alpha (beta | gamma)",
            base_options=SearchOptions(match_case=True),
        )

        assert [entry.name for entry in results] == ["alpha-beta.txt", "alpha-gamma.txt"]

    def test_and_precedence_beats_or(self):
        entries = [
            _entry("alpha.txt", 1),
            _entry("beta-gamma.txt", 2),
            _entry("beta.txt", 3),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search(
            "alpha | beta gamma",
            base_options=SearchOptions(match_case=True),
        )

        assert [entry.name for entry in results] == ["alpha.txt", "beta-gamma.txt"]

    def test_not_excludes_parenthesized_group(self):
        entries = [
            _entry("alpha-report.txt", 1),
            _entry("alpha-temp.txt", 2),
            _entry("alpha-cache.txt", 3),
        ]
        engine = SearchEngine(FakeIndex(entries))

        results = engine.search(
            "alpha !(temp | cache)",
            base_options=SearchOptions(match_case=True),
        )

        assert [entry.name for entry in results] == ["alpha-report.txt"]


class TestBrokenTargetSearch:
    def test_broken_link_modifier_returns_reparse_points_with_missing_targets(self, monkeypatch):
        broken = _entry("broken-link", 1, FILE_ATTRIBUTE_REPARSE_POINT)
        healthy = _entry("healthy-link", 2, FILE_ATTRIBUTE_REPARSE_POINT)
        broken._path = "C:\\links\\broken-link"
        healthy._path = "C:\\links\\healthy-link"
        engine = SearchEngine(FakeIndex([broken, healthy]))

        monkeypatch.setattr(search_module.os.path, "lexists", lambda path: True)
        monkeypatch.setattr(search_module.os.path, "exists", lambda path: path != broken._path)

        results = engine.search("broken:link")

        assert [entry.name for entry in results] == ["broken-link"]

    def test_broken_shortcut_modifier_returns_lnk_files_with_missing_targets(self, monkeypatch):
        broken = _entry("missing-target.lnk", 1)
        healthy = _entry("healthy-target.lnk", 2)
        plain = _entry("notes.txt", 3)
        broken._path = "C:\\shortcuts\\missing-target.lnk"
        healthy._path = "C:\\shortcuts\\healthy-target.lnk"
        plain._path = "C:\\shortcuts\\notes.txt"
        engine = SearchEngine(FakeIndex([broken, healthy, plain]))

        def shortcut_target(_self, path):
            if path == broken._path:
                return "C:\\missing\\target.txt"
            return "C:\\live\\target.txt"

        monkeypatch.setattr(SearchEngine, "_shortcut_target_path", shortcut_target)
        monkeypatch.setattr(
            search_module.os.path,
            "exists",
            lambda path: path != "C:\\missing\\target.txt",
        )

        results = engine.search("broken:shortcut")

        assert [entry.name for entry in results] == ["missing-target.lnk"]
