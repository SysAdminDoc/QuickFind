"""Cross-platform index engine selection and POSIX root discovery."""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOTS_ENV = "QUICKFIND_INDEX_ROOTS"


@dataclass(frozen=True)
class PlatformRoot:
    key: str
    path: str
    label: str
    filesystem: str
    watcher: str
    search_fallback: str = ""


class PlatformEngine:
    system = "generic"
    display_name = "Generic POSIX"
    watcher = "watchdog polling"
    search_fallback = ""
    filesystem = "POSIX"
    is_windows = False

    def discover_roots(self, configured: Iterable[str] | None = None) -> list[PlatformRoot]:
        roots = _configured_roots(configured)
        return [
            PlatformRoot(
                key=platform_source_key(root),
                path=str(root),
                label=root.name or str(root),
                filesystem=self.filesystem,
                watcher=self.watcher,
                search_fallback=self.search_fallback,
            )
            for root in roots
        ]

    def spotlight_paths(self, query: str, roots: Iterable[PlatformRoot],
                        max_results: int = 1000) -> list[str]:
        return []


class WindowsPlatformEngine(PlatformEngine):
    system = "windows"
    display_name = "Windows"
    watcher = "NTFS USN"
    filesystem = "Windows volumes"
    is_windows = True


class LinuxPlatformEngine(PlatformEngine):
    system = "linux"
    display_name = "Linux"
    watcher = "inotify"
    filesystem = "Linux filesystem"


class MacOSPlatformEngine(PlatformEngine):
    system = "darwin"
    display_name = "macOS"
    watcher = "FSEvents"
    filesystem = "APFS/HFS+"
    search_fallback = "Spotlight"

    def spotlight_paths(self, query: str, roots: Iterable[PlatformRoot],
                        max_results: int = 1000) -> list[str]:
        query = (query or "").strip()
        if not query:
            return []

        paths: list[str] = []
        remaining = max(1, int(max_results or 1000))
        for root in roots:
            if remaining <= 0:
                break
            try:
                result = subprocess.run(
                    ["/usr/bin/mdfind", "-0", "-onlyin", root.path, query],
                    check=False,
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode != 0:
                continue
            for raw in result.stdout.split(b"\0"):
                if not raw:
                    continue
                paths.append(raw.decode("utf-8", errors="replace"))
                remaining -= 1
                if remaining <= 0:
                    break
        return paths


def select_platform_engine(system: str | None = None) -> PlatformEngine:
    name = (system or platform.system()).lower()
    if name.startswith("win"):
        return WindowsPlatformEngine()
    if name == "linux":
        return LinuxPlatformEngine()
    if name == "darwin":
        return MacOSPlatformEngine()
    return PlatformEngine()


def platform_source_key(root: Path | str) -> str:
    normalized = os.path.abspath(os.path.expanduser(os.fspath(root)))
    digest = hashlib.sha1(normalized.encode("utf-8", "surrogatepass")).hexdigest()[:12]
    return f"POSIX:{digest.upper()}"


def _configured_roots(configured: Iterable[str] | None = None) -> list[Path]:
    raw_roots = list(configured or [])
    if not raw_roots:
        env_roots = os.environ.get(ROOTS_ENV, "")
        if env_roots:
            raw_roots = [part for part in env_roots.split(os.pathsep) if part]
    if not raw_roots:
        raw_roots = [str(Path.home())]

    roots: list[Path] = []
    seen: set[str] = set()
    for raw in raw_roots:
        try:
            root = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        key = os.path.normcase(str(root))
        if key in seen or not root.exists() or not root.is_dir():
            continue
        seen.add(key)
        roots.append(root)
    return roots
