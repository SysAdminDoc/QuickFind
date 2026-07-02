"""Tests for the es.py CLI argument parser.

Guards against argparse option-string conflicts (e.g. two flags claiming -r),
which raise at parser-build time and crash every invocation of the CLI.
"""

import sys

from cli import es


def test_parse_args_builds_without_option_conflicts(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["es", "report"])
    args = es.parse_args()
    assert args.query == ["report"]
    assert args.regex is False
    assert args.reverse is False


def test_reverse_flag_is_distinct_from_regex(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["es", "-R", "report"])
    args = es.parse_args()
    assert args.reverse is True
    assert args.regex is False


def test_regex_flag_still_uses_short_r(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["es", "-r", "re.*"])
    args = es.parse_args()
    assert args.regex is True
    assert args.reverse is False


def test_new_output_flags_parse(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "es", "q", "--count", "--total-size", "--tsv", "--no-header",
        "--export-efu", "out.efu", "--format", "{path}", "--hyperlink",
        "-x", "echo {}", "-X", "echo {}",
    ])
    args = es.parse_args()
    assert args.count and args.total_size and args.tsv and args.no_header
    assert args.export_efu == "out.efu"
    assert args.format_template == "{path}"
    assert args.hyperlink is True
    assert args.exec_cmd == "echo {}"
    assert args.exec_batch == "echo {}"


def test_placeholder_substitutions():
    subs = es._placeholders(r"C:\dir\file.txt")
    assert subs["{}"] == r"C:\dir\file.txt"
    assert subs["{/}"] == "file.txt"
    assert subs["{//}"] == r"C:\dir"
    assert subs["{.}"] == r"C:\dir\file"
    assert subs["{/.}"] == "file"
    assert es._apply_placeholders("cp {} {/}", subs) == r"cp C:\dir\file.txt file.txt"


class _FakeEntry:
    name = "file.txt"
    size = 123
    extension = "txt"
    date_modified = None
    date_created = None
    drive = "C"
    parent_frn = 5
    attributes = 0x20
    is_dir = False

    def get_path(self, index):
        return r"C:\dir\file.txt"


class _FakeIndex:
    def resolve_parent_path(self, drive, frn):
        return r"C:\dir"


def test_output_format_renders_placeholders(capsys):
    es._output_format([_FakeEntry()], _FakeIndex(), "{name}|{size}|{ext}|{dir}")
    out = capsys.readouterr().out.strip()
    assert out == r"file.txt|123|txt|C:\dir"


def test_output_tsv_uses_tabs_and_optional_header(capsys):
    es._output_csv([_FakeEntry()], _FakeIndex(), delimiter="\t", header=False)
    out = capsys.readouterr().out
    assert "\t" in out
    assert "Name\t" not in out  # header suppressed


def test_osc8_hyperlink_wraps_path():
    link = es._osc8(r"C:\dir\file.txt", "file.txt")
    assert link.startswith("\x1b]8;;file:///")
    assert link.endswith("\x1b]8;;\x1b\\")
