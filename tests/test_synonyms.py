"""Tests for query-time synonym expansion."""

import json

from core.synonyms import load_synonyms, expand_query_terms
from core.search import SearchEngine
from core.index import FileEntry


class _FakeIndex:
    def __init__(self, entries):
        self.all_entries = entries

    def resolve_path(self, drive, frn):
        return f"C:\\fake\\{frn}"

    def resolve_parent_path(self, drive, parent_frn):
        return "C:\\fake"


def _entry(name, frn):
    return FileEntry(frn=frn, parent_frn=5, name=name, drive="C")


def test_load_synonyms_absent_or_malformed(tmp_path):
    assert load_synonyms(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert load_synonyms(bad) == {}
    not_dict = tmp_path / "list.json"
    not_dict.write_text("[1,2,3]", encoding="utf-8")
    assert load_synonyms(not_dict) == {}


def test_load_synonyms_normalizes(tmp_path):
    f = tmp_path / "syn.json"
    f.write_text(json.dumps({"Car": ["automobile", " vehicle ", ""], "empty": []}), encoding="utf-8")
    data = load_synonyms(f)
    assert data == {"car": ["automobile", "vehicle"]}  # lowercased key, blanks dropped, empty list ignored


def test_expand_query_terms():
    remaining, groups = expand_query_terms(["car", "house"], {"car": ["automobile", "vehicle"]})
    assert remaining == ["house"]
    assert groups == [["car", "automobile", "vehicle"]]


def test_no_synonyms_leaves_query_unchanged():
    remaining, groups = expand_query_terms(["car"], {})
    assert remaining == ["car"]
    assert groups == []


def test_engine_expands_term_to_synonyms(tmp_path, monkeypatch):
    import core.synonyms as syn
    syn_file = tmp_path / "synonyms.json"
    syn_file.write_text(json.dumps({"car": ["automobile"]}), encoding="utf-8")
    monkeypatch.setattr(syn, "SYNONYMS_FILE", syn_file)

    entries = [_entry("automobile.txt", 1), _entry("bicycle.txt", 2)]
    engine = SearchEngine(_FakeIndex(entries))

    # "car" alone would not substring-match "automobile.txt", but the synonym does.
    results = engine.search("car")
    assert [e.frn for e in results] == [1]


def test_engine_no_expansion_without_file(tmp_path, monkeypatch):
    import core.synonyms as syn
    monkeypatch.setattr(syn, "SYNONYMS_FILE", tmp_path / "absent.json")

    entries = [_entry("automobile.txt", 1)]
    engine = SearchEngine(_FakeIndex(entries))
    assert engine.search("car") == []
