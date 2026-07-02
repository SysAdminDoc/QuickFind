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
