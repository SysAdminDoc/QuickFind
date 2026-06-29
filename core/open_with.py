"""Discovery and launch helpers for supported Open With targets."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True)
class OpenWithApp:
    label: str
    commands: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedOpenWithApp:
    label: str
    executable: str


DEFAULT_OPEN_WITH_APPS = (
    OpenWithApp(
        "VS Code",
        ("code.cmd", "code.exe", "code"),
        (
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%ProgramFiles%\Microsoft VS Code\Code.exe",
            r"%ProgramFiles(x86)%\Microsoft VS Code\Code.exe",
        ),
    ),
    OpenWithApp(
        "VSCodium",
        ("codium.cmd", "codium.exe", "codium"),
        (
            r"%LOCALAPPDATA%\Programs\VSCodium\VSCodium.exe",
            r"%ProgramFiles%\VSCodium\VSCodium.exe",
            r"%ProgramFiles(x86)%\VSCodium\VSCodium.exe",
        ),
    ),
    OpenWithApp(
        "Notepad++",
        ("notepad++.exe", "notepad++"),
        (
            r"%ProgramFiles%\Notepad++\notepad++.exe",
            r"%ProgramFiles(x86)%\Notepad++\notepad++.exe",
        ),
    ),
    OpenWithApp(
        "Obsidian",
        ("obsidian.exe", "obsidian"),
        (
            r"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe",
            r"%ProgramFiles%\Obsidian\Obsidian.exe",
            r"%ProgramFiles(x86)%\Obsidian\Obsidian.exe",
        ),
    ),
)


def resolve_open_with_apps(
    apps: Sequence[OpenWithApp] = DEFAULT_OPEN_WITH_APPS,
    *,
    which: Callable[[str], str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.isfile,
    environ: Mapping[str, str] | None = None,
) -> list[ResolvedOpenWithApp]:
    env = os.environ if environ is None else environ
    resolved: list[ResolvedOpenWithApp] = []
    for app in apps:
        executable = _resolve_app(app, which, exists, env)
        if executable:
            resolved.append(ResolvedOpenWithApp(app.label, executable))
    return resolved


def open_with_command(app: ResolvedOpenWithApp, paths: Sequence[str]) -> list[str]:
    return [app.executable, *[str(path) for path in paths if path]]


def launch_open_with(app: ResolvedOpenWithApp, paths: Sequence[str]) -> tuple[bool, str]:
    command = open_with_command(app, paths)
    if len(command) <= 1:
        return False, "No paths selected."
    try:
        subprocess.Popen(command)
    except OSError as exc:
        return False, f"Failed to launch {app.label}: {exc}"
    return True, f"Opened {len(command) - 1} item(s) with {app.label}."


def _resolve_app(
    app: OpenWithApp,
    which: Callable[[str], str | None],
    exists: Callable[[str], bool],
    environ: Mapping[str, str],
) -> str:
    for command in app.commands:
        resolved = which(command)
        if resolved:
            return resolved
    for candidate in app.paths:
        expanded = candidate
        for key, value in environ.items():
            expanded = expanded.replace(f"%{key}%", value)
        expanded = os.path.expandvars(expanded)
        if exists(expanded):
            return expanded
    return ""
