"""Windows common-file-dialog quick switch helpers."""

from dataclasses import dataclass
import logging
import os
from typing import Callable, Iterable

logger = logging.getLogger("QuickFind.DialogSwitch")


@dataclass(frozen=True)
class DialogSwitchResult:
    ok: bool
    message: str
    folder: str = ""
    hwnd: int = 0


def folder_target_from_path(path: str, is_dir: Callable[[str], bool] = os.path.isdir) -> str:
    """Return the folder that should be sent to a file dialog."""
    if not path:
        return ""
    target = os.path.abspath(os.path.normpath(path))
    if is_dir(target):
        return target
    return os.path.dirname(target)


def is_probable_file_dialog(class_name: str, title: str,
                            child_classes: Iterable[str]) -> bool:
    """Heuristic for standard Open/Save dialogs without binding to one app."""
    if class_name != "#32770":
        return False

    title_lower = (title or "").lower()
    title_matches = any(
        token in title_lower
        for token in ("open", "save", "select", "choose", "browse")
    )
    child_set = set(child_classes)
    has_dialog_controls = "Edit" in child_set and (
        "ComboBoxEx32" in child_set or "DirectUIHWND" in child_set
    )
    return title_matches or has_dialog_controls


def _load_win32():
    try:
        import win32con
        import win32gui
    except Exception as exc:
        raise RuntimeError("pywin32 window APIs are unavailable") from exc
    return win32con, win32gui


def _child_windows(win32gui, hwnd: int) -> list[int]:
    children: list[int] = []

    def collect(child_hwnd, _param):
        children.append(child_hwnd)
        children.extend(_child_windows(win32gui, child_hwnd))
        return True

    win32gui.EnumChildWindows(hwnd, collect, None)
    return children


def _child_classes(win32gui, hwnd: int) -> list[str]:
    classes = []
    for child in _child_windows(win32gui, hwnd):
        try:
            classes.append(win32gui.GetClassName(child))
        except Exception:
            continue
    return classes


def _find_filename_edit(win32gui, hwnd: int) -> int:
    edits = []
    for child in _child_windows(win32gui, hwnd):
        try:
            if win32gui.GetClassName(child) != "Edit":
                continue
            if not win32gui.IsWindowEnabled(child) or not win32gui.IsWindowVisible(child):
                continue
            edits.append(child)
        except Exception:
            continue
    return edits[-1] if edits else 0


def switch_dialog_to_folder(path: str, hwnd: int | None = None) -> DialogSwitchResult:
    """Send a folder path to the active common Open/Save dialog."""
    folder = folder_target_from_path(path)
    if not folder or not os.path.isdir(folder):
        return DialogSwitchResult(False, "Selected result is not an available folder.", folder)

    try:
        win32con, win32gui = _load_win32()
        target_hwnd = int(hwnd or win32gui.GetForegroundWindow() or 0)
        if not target_hwnd:
            return DialogSwitchResult(False, "No active window found.", folder)

        class_name = win32gui.GetClassName(target_hwnd)
        title = win32gui.GetWindowText(target_hwnd)
        child_classes = _child_classes(win32gui, target_hwnd)
        if not is_probable_file_dialog(class_name, title, child_classes):
            return DialogSwitchResult(False, "Active window is not an Open/Save dialog.", folder, target_hwnd)

        edit_hwnd = _find_filename_edit(win32gui, target_hwnd)
        if not edit_hwnd:
            return DialogSwitchResult(False, "Could not find the dialog file name field.", folder, target_hwnd)

        dialog_path = folder if folder.endswith("\\") else f"{folder}\\"
        win32gui.SetForegroundWindow(target_hwnd)
        win32gui.SendMessage(edit_hwnd, win32con.WM_SETTEXT, 0, dialog_path)
        win32gui.PostMessage(edit_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
        win32gui.PostMessage(edit_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
        return DialogSwitchResult(True, f"Switched dialog to {folder}", folder, target_hwnd)
    except Exception as exc:
        logger.debug("Dialog quick switch failed: %s", exc)
        return DialogSwitchResult(False, f"Dialog quick switch failed: {exc}", folder)
