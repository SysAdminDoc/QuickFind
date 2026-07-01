"""Tests for portable/cloud-profile mode with machine-scoped caches."""

from pathlib import Path

from core.portable import (
    MachineIdentity,
    ProfilePaths,
    is_cache_compatible,
    machine_identity,
    profile_diagnostics,
    resolve_profile_paths,
    stamp_cache,
)


def test_machine_identity_is_stable():
    a = machine_identity()
    b = machine_identity()
    assert a == b
    assert len(a.node_hash) == 64
    assert a.hostname
    assert a.cache_tag() == a.node_hash[:8]


def test_resolve_default_profile():
    paths = resolve_profile_paths()
    assert not paths.portable
    assert paths.machine_tag == ""
    assert ".quickfind" in str(paths.settings_dir)


def test_resolve_portable_profile(tmp_path):
    paths = resolve_profile_paths(portable_root=str(tmp_path), force_portable=True)
    assert paths.portable
    assert paths.machine_tag
    assert tmp_path / "config" == paths.settings_dir
    assert paths.machine_tag in str(paths.cache_dir)


def test_cache_compatibility_with_matching_stamp(tmp_path):
    cache_dir = tmp_path / "cache" / "abc12345"
    stamp_cache(cache_dir, "abc12345")
    assert is_cache_compatible(cache_dir, "abc12345")


def test_cache_incompatible_with_different_stamp(tmp_path):
    cache_dir = tmp_path / "cache" / "abc12345"
    stamp_cache(cache_dir, "abc12345")
    assert not is_cache_compatible(cache_dir, "different1")


def test_cache_compatible_without_stamp(tmp_path):
    cache_dir = tmp_path / "cache" / "new"
    cache_dir.mkdir(parents=True)
    assert is_cache_compatible(cache_dir, "abc12345")


def test_cache_compatible_when_no_tag_expected(tmp_path):
    assert is_cache_compatible(tmp_path, "")


def test_stamp_cache_creates_file(tmp_path):
    cache_dir = tmp_path / "new_cache"
    stamp_cache(cache_dir, "test1234")
    stamp_file = cache_dir / ".machine_tag"
    assert stamp_file.exists()
    assert stamp_file.read_text(encoding="utf-8").strip() == "test1234"


def test_profile_diagnostics_reports_state(tmp_path):
    paths = ProfilePaths(
        settings_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
        plugins_dir=tmp_path / "plugins",
        portable=True,
        machine_tag="abc12345",
    )
    diag = profile_diagnostics(paths)
    assert diag["portable"] is True
    assert diag["machine_tag"] == "abc12345"
    assert diag["settings_exists"] is False


def test_portable_paths_separate_machines(tmp_path):
    paths_a = resolve_profile_paths(portable_root=str(tmp_path), force_portable=True)
    assert paths_a.machine_tag
    assert paths_a.portable
    assert paths_a.cache_dir != paths_a.settings_dir
