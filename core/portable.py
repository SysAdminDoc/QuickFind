"""Portable/cloud-profile mode with machine-scoped caches.

When portable mode is active, settings and caches live beside the executable
(or in a user-chosen root) instead of ~/.quickfind. Cache databases include
a machine identity stamp to prevent stale-path conflicts when profiles sync
via OneDrive/Dropbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class MachineIdentity:
    hostname: str
    platform: str
    node_hash: str

    def cache_tag(self) -> str:
        return self.node_hash[:8]


@dataclass(frozen=True)
class ProfilePaths:
    settings_dir: Path
    cache_dir: Path
    plugins_dir: Path
    portable: bool = False
    machine_tag: str = ""


def machine_identity() -> MachineIdentity:
    """Generate a stable machine identity for cache scoping."""
    hostname = platform.node()
    plat = platform.platform()
    node_hash = hashlib.sha256(
        f"{hostname}:{plat}:{os.getenv('COMPUTERNAME', '')}".encode()
    ).hexdigest()
    return MachineIdentity(hostname=hostname, platform=plat, node_hash=node_hash)


def _exe_dir() -> Path:
    """Return the directory containing the running executable or script."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def detect_portable_marker() -> Path | None:
    """Check for a .quickfind-portable marker file beside the executable."""
    marker = _exe_dir() / ".quickfind-portable"
    if marker.exists():
        return marker
    return None


def resolve_profile_paths(
    portable_root: str | None = None,
    force_portable: bool = False,
) -> ProfilePaths:
    """Resolve settings/cache/plugin directories based on mode."""
    marker = detect_portable_marker()
    is_portable = force_portable or marker is not None

    if is_portable:
        root = Path(portable_root) if portable_root else _exe_dir()
        identity = machine_identity()
        tag = identity.cache_tag()
        return ProfilePaths(
            settings_dir=root / "config",
            cache_dir=root / "cache" / tag,
            plugins_dir=root / "plugins",
            portable=True,
            machine_tag=tag,
        )

    default = Path.home() / ".quickfind"
    return ProfilePaths(
        settings_dir=default,
        cache_dir=default,
        plugins_dir=default / "plugins",
        portable=False,
    )


def is_cache_compatible(cache_dir: Path, expected_tag: str) -> bool:
    """Check if a cache directory belongs to the current machine."""
    if not expected_tag:
        return True
    stamp_file = cache_dir / ".machine_tag"
    if not stamp_file.exists():
        return True
    try:
        stored = stamp_file.read_text(encoding="utf-8").strip()
        return stored == expected_tag
    except OSError:
        return False


def stamp_cache(cache_dir: Path, tag: str) -> None:
    """Write the machine identity stamp to a cache directory."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp_file = cache_dir / ".machine_tag"
    stamp_file.write_text(tag, encoding="utf-8")


def profile_diagnostics(paths: ProfilePaths) -> dict:
    """Return diagnostic info for the active profile."""
    return {
        "portable": paths.portable,
        "settings_dir": str(paths.settings_dir),
        "cache_dir": str(paths.cache_dir),
        "plugins_dir": str(paths.plugins_dir),
        "machine_tag": paths.machine_tag,
        "settings_exists": paths.settings_dir.exists(),
        "cache_exists": paths.cache_dir.exists(),
    }
