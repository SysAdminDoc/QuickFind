"""Tests for Open With target discovery."""

from core.open_with import (
    OpenWithApp,
    ResolvedOpenWithApp,
    open_with_command,
    resolve_open_with_apps,
)


def test_resolve_open_with_apps_prefers_path_commands():
    apps = [
        OpenWithApp("Editor", ("editor.cmd",), (r"%LOCALAPPDATA%\Editor\Editor.exe",)),
        OpenWithApp("Fallback", ("missing.cmd",), (r"%LOCALAPPDATA%\Fallback\Fallback.exe",)),
    ]

    resolved = resolve_open_with_apps(
        apps,
        which=lambda command: r"C:\bin\editor.cmd" if command == "editor.cmd" else None,
        exists=lambda path: path.endswith(r"Fallback\Fallback.exe"),
        environ={"LOCALAPPDATA": r"C:\Users\me\AppData\Local"},
    )

    assert resolved == [
        ResolvedOpenWithApp("Editor", r"C:\bin\editor.cmd"),
        ResolvedOpenWithApp("Fallback", r"C:\Users\me\AppData\Local\Fallback\Fallback.exe"),
    ]


def test_open_with_command_passes_selected_paths():
    app = ResolvedOpenWithApp("Editor", r"C:\bin\editor.cmd")

    assert open_with_command(app, [r"C:\docs\a.txt", r"D:\b.md"]) == [
        r"C:\bin\editor.cmd",
        r"C:\docs\a.txt",
        r"D:\b.md",
    ]
