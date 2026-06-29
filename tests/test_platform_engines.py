"""Tests for cross-platform index engine selection."""

from pathlib import Path
from unittest.mock import MagicMock

from core.platform_engines import (
    LinuxPlatformEngine,
    MacOSPlatformEngine,
    platform_source_key,
    select_platform_engine,
)


def test_select_platform_engine_uses_native_backends():
    assert select_platform_engine("Windows").watcher == "NTFS USN"
    assert select_platform_engine("Linux").watcher == "inotify"
    assert select_platform_engine("Darwin").watcher == "FSEvents"


def test_linux_engine_discovers_configured_roots(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()

    roots = LinuxPlatformEngine().discover_roots([str(root)])

    assert roots[0].key == platform_source_key(root)
    assert roots[0].path == str(root.resolve())
    assert roots[0].watcher == "inotify"


def test_macos_spotlight_fallback_reads_null_delimited_paths(monkeypatch, tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    engine = MacOSPlatformEngine()
    platform_root = engine.discover_roots([str(root)])[0]
    result = MagicMock(returncode=0, stdout=b"/Users/me/a.txt\0/Users/me/b.txt\0")
    monkeypatch.setattr("core.platform_engines.subprocess.run", lambda *a, **k: result)

    paths = engine.spotlight_paths("report", [platform_root], max_results=1)

    assert paths == ["/Users/me/a.txt"]
