"""
Context menu for search results with shell integration.
"""

import os
import subprocess
import ctypes
import logging
import threading
from typing import Optional

from PyQt6.QtWidgets import QMenu, QApplication, QInputDialog
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtCore import QUrl

from core.index import FileEntry, FileIndex

logger = logging.getLogger('QuickFind.ContextMenu')

shell32 = ctypes.windll.shell32


def _open_file(path: str):
    """Open a file with its default application."""
    try:
        os.startfile(path)
    except OSError as e:
        logger.error(f"Failed to open {path}: {e}")


def _open_path(path: str):
    """Open the containing folder and select the file."""
    try:
        # Use explorer /select to highlight the file
        subprocess.Popen(['explorer', '/select,', path])
    except Exception as e:
        logger.error(f"Failed to open path for {path}: {e}")


def _copy_to_clipboard(text: str):
    """Copy text to clipboard."""
    app = QApplication.instance()
    if app:
        app.clipboard().setText(text)


def _open_cmd_here(directory: str):
    """Open command prompt in directory."""
    try:
        subprocess.Popen(['cmd', '/k', f'cd /d "{directory}"'], creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        logger.error(f"Failed to open CMD: {e}")


def _open_powershell_here(directory: str):
    """Open PowerShell in directory."""
    try:
        subprocess.Popen(['powershell', '-NoExit', '-Command', f'Set-Location "{directory}"'],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
    except Exception as e:
        logger.error(f"Failed to open PowerShell: {e}")


def _open_terminal_here(directory: str):
    """Open Windows Terminal in directory."""
    try:
        subprocess.Popen(['wt', '-d', directory])
    except FileNotFoundError:
        _open_powershell_here(directory)
    except Exception as e:
        logger.error(f"Failed to open terminal: {e}")


def _show_properties(path: str):
    """Show Windows file properties dialog."""
    try:
        # ShellExecuteW with "properties" verb
        shell32.ShellExecuteW(None, "properties", path, None, None, 1)
    except Exception as e:
        logger.error(f"Failed to show properties for {path}: {e}")


def _delete_to_recycle(path: str):
    """Delete file to Recycle Bin using SHFileOperation."""
    try:
        import ctypes.wintypes
        # Use shell API for safe recycling
        # SHFileOperationW with FOF_ALLOWUNDO
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [
                ('hwnd', ctypes.wintypes.HWND),
                ('wFunc', ctypes.c_uint),
                ('pFrom', ctypes.c_wchar_p),
                ('pTo', ctypes.c_wchar_p),
                ('fFlags', ctypes.c_ushort),
                ('fAnyOperationsAborted', ctypes.wintypes.BOOL),
                ('hNameMappings', ctypes.c_void_p),
                ('lpszProgressTitle', ctypes.c_wchar_p),
            ]

        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_SILENT = 0x0004
        FOF_NOCONFIRMATION = 0x0010

        op = SHFILEOPSTRUCTW()
        op.wFunc = FO_DELETE
        op.pFrom = path + '\0'
        op.fFlags = FOF_ALLOWUNDO | FOF_SILENT | FOF_NOCONFIRMATION

        shell32.SHFileOperationW(ctypes.byref(op))
    except Exception as e:
        logger.error(f"Failed to delete {path}: {e}")


def build_context_menu(entries: list[FileEntry], file_index: FileIndex,
                       parent_widget=None,
                       hide_callback=None) -> QMenu:
    """
    Build a context menu for the selected file entries.
    """
    menu = QMenu(parent_widget)

    if not entries:
        return menu

    single = len(entries) == 1
    entry = entries[0]
    path = entry.get_path(file_index)
    parent_dir = file_index.resolve_parent_path(entry.drive, entry.parent_frn)

    # ── Open ────────────────────────────────────────
    if single:
        open_action = menu.addAction("Open")
        open_action.setFont(open_action.font())  # Will be made bold below
        font = open_action.font()
        font.setBold(True)
        open_action.setFont(font)
        open_action.triggered.connect(lambda: _open_file(path))

    open_path_action = menu.addAction("Open Path" if single else "Open Paths")
    if single:
        open_path_action.triggered.connect(lambda: _open_path(path))
    else:
        # Open unique parent directories
        open_path_action.triggered.connect(lambda: [
            _open_path(e.get_path(file_index)) for e in entries[:5]
        ])

    menu.addSeparator()

    # ── Copy submenu ────────────────────────────────
    copy_menu = menu.addMenu("Copy")

    if single:
        copy_name = copy_menu.addAction("Copy Name")
        copy_name.triggered.connect(lambda: _copy_to_clipboard(entry.name))

        copy_path = copy_menu.addAction("Copy Full Path")
        copy_path.triggered.connect(lambda: _copy_to_clipboard(path))

        copy_dir = copy_menu.addAction("Copy Directory Path")
        copy_dir.triggered.connect(lambda: _copy_to_clipboard(parent_dir))
    else:
        copy_names = copy_menu.addAction(f"Copy {len(entries)} Names")
        copy_names.triggered.connect(
            lambda: _copy_to_clipboard('\n'.join(e.name for e in entries))
        )

        copy_paths = copy_menu.addAction(f"Copy {len(entries)} Full Paths")
        copy_paths.triggered.connect(
            lambda: _copy_to_clipboard('\n'.join(e.get_path(file_index) for e in entries))
        )

    menu.addSeparator()

    # ── Terminal options ────────────────────────────
    if single:
        target_dir = path if entry.is_dir else parent_dir

        terminal_menu = menu.addMenu("Open Terminal Here")

        cmd_action = terminal_menu.addAction("Command Prompt")
        cmd_action.triggered.connect(lambda: _open_cmd_here(target_dir))

        ps_action = terminal_menu.addAction("PowerShell")
        ps_action.triggered.connect(lambda: _open_powershell_here(target_dir))

        wt_action = terminal_menu.addAction("Windows Terminal")
        wt_action.triggered.connect(lambda: _open_terminal_here(target_dir))

    menu.addSeparator()

    # ── Hide from results ──────────────────────────
    if hide_callback:
        if single:
            if entry.is_dir:
                hide_dir = menu.addAction("Hide This Directory")
                hide_dir.triggered.connect(lambda: hide_callback(path, 'directory'))
            else:
                hide_file = menu.addAction("Hide This File")
                hide_file.triggered.connect(lambda: hide_callback(path, 'file'))

                hide_parent = menu.addAction(f"Hide Directory: {os.path.basename(parent_dir)}")
                hide_parent.triggered.connect(lambda: hide_callback(parent_dir, 'directory'))
        else:
            # Multi-selection: collect unique parent directories
            unique_dirs = set()
            for e in entries:
                if e.is_dir:
                    unique_dirs.add(e.get_path(file_index))
                else:
                    unique_dirs.add(file_index.resolve_parent_path(e.drive, e.parent_frn))
            if len(unique_dirs) == 1:
                d = next(iter(unique_dirs))
                hide_d = menu.addAction(f"Hide Directory: {os.path.basename(d)}")
                hide_d.triggered.connect(lambda: hide_callback(d, 'directory'))
            else:
                hide_menu = menu.addMenu("Hide Directories")
                for d in sorted(unique_dirs):
                    act = hide_menu.addAction(os.path.basename(d))
                    act.triggered.connect(lambda checked, dp=d: hide_callback(dp, 'directory'))

        menu.addSeparator()

    # ── Delete ──────────────────────────────────────
    delete_action = menu.addAction(f"Delete ({len(entries)})" if len(entries) > 1 else "Delete")
    def _async_delete():
        paths = [e.get_path(file_index) for e in entries]
        threading.Thread(target=lambda: [_delete_to_recycle(p) for p in paths], daemon=True).start()
    delete_action.triggered.connect(_async_delete)

    menu.addSeparator()

    # ── Properties ──────────────────────────────────
    if single:
        props_action = menu.addAction("Properties")
        props_action.triggered.connect(lambda: _show_properties(path))

    return menu
