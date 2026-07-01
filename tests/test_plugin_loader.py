"""Tests for plugin discovery, validation, loading, and quarantine."""

import json

import pytest

from core.plugin_loader import (
    PluginManifest,
    _sha256_file,
    _validate_manifest,
    discover_plugins,
    load_allowed_hashes,
    load_plugins,
    plugin_summary,
    read_manifest,
)
from core.search import clear_modifier_plugins, registered_modifier_plugins


@pytest.fixture(autouse=True)
def _clean_plugins():
    clear_modifier_plugins()
    yield
    clear_modifier_plugins()


def _write_manifest(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_allowlist(plugin_dir, hashes):
    path = plugin_dir / "allowed_hashes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"hashes": list(hashes)}), encoding="utf-8")


def test_read_manifest_from_valid_json(tmp_path):
    manifest_path = tmp_path / "plugin.json"
    _write_manifest(manifest_path, {
        "name": "hello",
        "version": "1.0",
        "description": "Says hello",
        "modifiers": ["hello", "hi"],
        "entry_point": "main.py",
    })
    m = read_manifest(manifest_path)
    assert m is not None
    assert m.name == "hello"
    assert m.modifiers == ("hello", "hi")
    assert m.entry_point == "main.py"


def test_read_manifest_missing_name(tmp_path):
    manifest_path = tmp_path / "plugin.json"
    _write_manifest(manifest_path, {"modifiers": ["x"]})
    assert read_manifest(manifest_path) is None


def test_read_manifest_invalid_json(tmp_path):
    manifest_path = tmp_path / "plugin.json"
    manifest_path.write_text("{bad", encoding="utf-8")
    assert read_manifest(manifest_path) is None


def test_discover_plugins_finds_subdirectory_manifests(tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_manifest(plugin_dir / "alpha" / "plugin.json", {
        "name": "alpha",
        "modifiers": ["alpha"],
    })
    _write_manifest(plugin_dir / "beta" / "plugin.json", {
        "name": "beta",
        "modifiers": ["beta"],
    })
    manifests = discover_plugins(plugin_dir)
    names = [m.name for m in manifests]
    assert "alpha" in names
    assert "beta" in names


def test_discover_plugins_handles_missing_directory(tmp_path):
    assert discover_plugins(tmp_path / "nonexistent") == []


def test_validate_manifest_rejects_missing_modifiers():
    m = PluginManifest(name="bad", modifiers=())
    error = _validate_manifest(m)
    assert error is not None
    assert "No modifiers" in error


def test_validate_manifest_rejects_invalid_modifier_name():
    m = PluginManifest(name="bad", modifiers=("has space",))
    error = _validate_manifest(m)
    assert error is not None
    assert "Invalid" in error


def test_validate_manifest_accepts_valid():
    m = PluginManifest(name="good", modifiers=("myplugin",))
    assert _validate_manifest(m) is None


def test_load_plugins_registers_manifest_only_plugins(tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_manifest(plugin_dir / "simple" / "plugin.json", {
        "name": "simple",
        "modifiers": ["simple"],
        "description": "A simple plugin",
    })
    result = load_plugins(plugin_dir)
    assert len(result.loaded) == 1
    assert result.loaded[0].manifest.name == "simple"
    plugins = registered_modifier_plugins()
    assert any(p.canonical_name == "simple" for p in plugins)


def test_load_plugins_skips_disabled(tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_manifest(plugin_dir / "skip" / "plugin.json", {
        "name": "skip",
        "modifiers": ["skip"],
    })
    result = load_plugins(plugin_dir, disabled=frozenset({"skip"}))
    assert len(result.skipped) == 1
    assert result.skipped[0].quarantined is True
    assert len(result.loaded) == 0


def test_load_plugins_quarantines_invalid_entry_point(tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_manifest(plugin_dir / "broken" / "plugin.json", {
        "name": "broken",
        "modifiers": ["broken"],
        "entry_point": "nonexistent.py",
    })
    result = load_plugins(plugin_dir)
    assert len(result.failed) == 1
    assert "not found" in result.failed[0].error


def test_load_plugins_does_not_break_search_on_failure(tmp_path):
    plugin_dir = tmp_path / "plugins"
    _write_manifest(plugin_dir / "bad" / "plugin.json", {
        "name": "bad",
        "modifiers": [],
    })
    _write_manifest(plugin_dir / "good" / "plugin.json", {
        "name": "good",
        "modifiers": ["goodmod"],
    })
    result = load_plugins(plugin_dir)
    assert len(result.loaded) == 1
    assert len(result.failed) == 1


def test_plugin_summary_lists_registered():
    from core.search import SearchModifierPlugin, register_modifier_plugin
    register_modifier_plugin(SearchModifierPlugin(
        names=("testmod", "tm"),
        description="Test modifier",
    ))
    summary = plugin_summary()
    assert len(summary) == 1
    assert summary[0]["name"] == "testmod"
    assert "tm" in summary[0]["aliases"]


def test_load_plugin_with_python_entry_point(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_path = plugin_dir / "pyplug"
    plugin_path.mkdir(parents=True)
    _write_manifest(plugin_path / "plugin.json", {
        "name": "pyplug",
        "modifiers": ["pymod"],
        "entry_point": "main.py",
        "description": "Python plugin",
    })
    main_py = plugin_path / "main.py"
    main_py.write_text(
        "def parse(value, parsed):\n    pass\n"
        "def match(entry, index, value, parsed):\n    return True\n",
        encoding="utf-8",
    )
    _write_allowlist(plugin_dir, [_sha256_file(main_py)])
    result = load_plugins(plugin_dir)
    assert len(result.loaded) == 1
    plugins = registered_modifier_plugins()
    assert any(p.canonical_name == "pymod" for p in plugins)


def test_path_traversal_in_entry_point_is_blocked(tmp_path):
    plugin_dir = tmp_path / "plugins"
    evil_script = tmp_path / "evil.py"
    evil_script.write_text("EXPLOITED = True\n", encoding="utf-8")
    _write_manifest(plugin_dir / "evil" / "plugin.json", {
        "name": "evil",
        "modifiers": ["evil"],
        "entry_point": "../../evil.py",
    })
    result = load_plugins(plugin_dir)
    assert len(result.loaded) == 0
    assert len(result.failed) == 1


def test_plugin_blocked_when_hash_not_in_allowlist(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_path = plugin_dir / "untrusted"
    plugin_path.mkdir(parents=True)
    _write_manifest(plugin_path / "plugin.json", {
        "name": "untrusted",
        "modifiers": ["untrusted"],
        "entry_point": "main.py",
    })
    (plugin_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    _write_allowlist(plugin_dir, ["0000000000000000000000000000000000000000000000000000000000000000"])
    result = load_plugins(plugin_dir)
    assert len(result.loaded) == 0
    assert len(result.failed) == 1
    assert "hash" in result.failed[0].error.lower() or "allowlist" in result.failed[0].error.lower()


def test_plugin_loads_when_hash_allowlist_disabled(tmp_path):
    plugin_dir = tmp_path / "plugins"
    plugin_path = plugin_dir / "nocheck"
    plugin_path.mkdir(parents=True)
    _write_manifest(plugin_path / "plugin.json", {
        "name": "nocheck",
        "modifiers": ["nocheckmod"],
        "entry_point": "main.py",
    })
    (plugin_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    result = load_plugins(plugin_dir, require_hash_allowlist=False)
    assert len(result.loaded) == 1


def test_load_allowed_hashes_parses_file(tmp_path):
    _write_allowlist(tmp_path, ["abc123", "DEF456"])
    hashes = load_allowed_hashes(tmp_path)
    assert "abc123" in hashes
    assert "def456" in hashes


def test_load_allowed_hashes_empty_without_file(tmp_path):
    assert load_allowed_hashes(tmp_path) == set()
