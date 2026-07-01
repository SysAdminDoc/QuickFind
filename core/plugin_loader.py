"""Discover, validate, and load modifier plugins from a configured directory."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.search import (
    SearchModifierPlugin,
    clear_modifier_plugins,
    register_modifier_plugin,
    registered_modifier_plugins,
    unregister_modifier_plugin,
)

logger = logging.getLogger("QuickFind.Plugins")

DEFAULT_PLUGIN_DIR = Path.home() / ".quickfind" / "plugins"


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str = ""
    description: str = ""
    modifiers: tuple[str, ...] = ()
    entry_point: str = ""


@dataclass
class PluginStatus:
    manifest: PluginManifest
    loaded: bool = False
    error: str = ""
    quarantined: bool = False


@dataclass
class PluginLoadResult:
    loaded: list[PluginStatus] = field(default_factory=list)
    skipped: list[PluginStatus] = field(default_factory=list)
    failed: list[PluginStatus] = field(default_factory=list)


def read_manifest(path: Path) -> PluginManifest | None:
    """Read a plugin manifest JSON file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Failed to read manifest %s: %s", path, e)
        return None

    name = data.get("name", "")
    if not name or not isinstance(name, str):
        return None

    modifiers = data.get("modifiers", [])
    if isinstance(modifiers, str):
        modifiers = [modifiers]
    if not isinstance(modifiers, list):
        modifiers = []

    return PluginManifest(
        name=name,
        version=str(data.get("version", "")),
        description=str(data.get("description", "")),
        modifiers=tuple(str(m) for m in modifiers if m),
        entry_point=str(data.get("entry_point", "")),
    )


def discover_plugins(plugin_dir: Path = DEFAULT_PLUGIN_DIR) -> list[PluginManifest]:
    """Scan a directory for plugin manifests."""
    if not plugin_dir.is_dir():
        return []
    manifests = []
    for child in sorted(plugin_dir.iterdir()):
        if child.is_dir():
            manifest_path = child / "plugin.json"
            if manifest_path.exists():
                manifest = read_manifest(manifest_path)
                if manifest:
                    manifests.append(manifest)
        elif child.suffix == ".json" and child.stem != "plugin":
            manifest = read_manifest(child)
            if manifest:
                manifests.append(manifest)
    return manifests


def _validate_manifest(manifest: PluginManifest) -> str | None:
    """Return an error string if the manifest is invalid, else None."""
    if not manifest.name:
        return "Missing plugin name"
    if not manifest.modifiers:
        return "No modifiers declared"
    for mod in manifest.modifiers:
        if ':' in mod or any(ch.isspace() for ch in mod):
            return f"Invalid modifier name: {mod!r}"
    return None


def load_plugin_module(manifest: PluginManifest, plugin_dir: Path) -> SearchModifierPlugin | None:
    """Load a plugin's entry point module and extract the SearchModifierPlugin."""
    if not manifest.entry_point:
        return SearchModifierPlugin(
            names=manifest.modifiers,
            description=manifest.description,
        )

    plugin_path = plugin_dir / manifest.name
    module_path = (plugin_path / manifest.entry_point).resolve()

    if not module_path.exists():
        candidate = (plugin_dir / manifest.entry_point).resolve()
        if candidate.exists():
            module_path = candidate
        else:
            return None

    resolved_dir = plugin_dir.resolve()
    if not str(module_path).startswith(str(resolved_dir) + os.sep):
        logger.warning(
            "Plugin %s entry point escapes plugin directory: %s",
            manifest.name, module_path,
        )
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            f"quickfind_plugin_{manifest.name}", str(module_path)
        )
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        logger.warning("Failed to load plugin %s: %s", manifest.name, e)
        return None

    plugin = getattr(mod, "plugin", None)
    if isinstance(plugin, SearchModifierPlugin):
        return plugin

    parse_fn = getattr(mod, "parse", None)
    match_fn = getattr(mod, "match", None)
    if parse_fn or match_fn:
        return SearchModifierPlugin(
            names=manifest.modifiers,
            parse=parse_fn,
            match=match_fn,
            description=manifest.description,
        )

    return SearchModifierPlugin(
        names=manifest.modifiers,
        description=manifest.description,
    )


def load_plugins(
    plugin_dir: Path = DEFAULT_PLUGIN_DIR,
    disabled: frozenset[str] = frozenset(),
) -> PluginLoadResult:
    """Discover, validate, and register plugins from the directory."""
    result = PluginLoadResult()
    manifests = discover_plugins(plugin_dir)

    for manifest in manifests:
        if manifest.name in disabled:
            status = PluginStatus(manifest=manifest, quarantined=True)
            result.skipped.append(status)
            continue

        error = _validate_manifest(manifest)
        if error:
            status = PluginStatus(manifest=manifest, error=error)
            result.failed.append(status)
            continue

        try:
            plugin = load_plugin_module(manifest, plugin_dir)
            if plugin is None:
                status = PluginStatus(
                    manifest=manifest,
                    error="Entry point not found or invalid",
                )
                result.failed.append(status)
                continue

            register_modifier_plugin(plugin)
            status = PluginStatus(manifest=manifest, loaded=True)
            result.loaded.append(status)
        except Exception as e:
            status = PluginStatus(manifest=manifest, error=str(e))
            result.failed.append(status)

    return result


def plugin_summary() -> list[dict[str, Any]]:
    """Return a summary of all registered plugins for settings/help display."""
    plugins = registered_modifier_plugins()
    return [
        {
            "name": p.canonical_name,
            "aliases": list(p.names),
            "description": p.description,
        }
        for p in plugins
    ]
