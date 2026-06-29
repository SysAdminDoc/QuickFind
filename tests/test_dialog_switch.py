"""Tests for Open/Save dialog Quick Switch helpers."""

from core.dialog_switch import folder_target_from_path, is_probable_file_dialog
from core.index import FileEntry, NTFS_ROOT_FRN
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY
import gui.context_menu as context_menu
from gui.context_menu import build_context_menu


class TempIndex:
    def resolve_parent_path(self, drive: str, parent_frn: int) -> str:
        return f"{drive}:\\docs"


class FakeSignal:
    def connect(self, callback):
        self.callback = callback


class FakeFont:
    def setBold(self, _value):
        pass


class FakeAction:
    def __init__(self, text):
        self._text = text
        self.triggered = FakeSignal()

    def text(self):
        return self._text

    def font(self):
        return FakeFont()

    def setFont(self, _font):
        pass


class FakeMenu:
    def __init__(self, _parent=None):
        self._actions = []

    def addAction(self, text):
        action = FakeAction(text)
        self._actions.append(action)
        return action

    def addMenu(self, text):
        menu = FakeMenu()
        self._actions.append(FakeAction(text))
        return menu

    def addSeparator(self):
        pass

    def actions(self):
        return self._actions


def test_folder_target_preserves_directory_paths():
    target = folder_target_from_path(
        "C:\\docs\\Reports",
        is_dir=lambda path: path.endswith("Reports"),
    )

    assert target.endswith("Reports")


def test_folder_target_uses_parent_for_file_paths():
    target = folder_target_from_path(
        "C:\\docs\\report.pdf",
        is_dir=lambda _path: False,
    )

    assert target == "C:\\docs"


def test_probable_file_dialog_requires_dialog_shape():
    assert is_probable_file_dialog(
        "#32770",
        "Open",
        ["DirectUIHWND", "ComboBoxEx32", "Edit"],
    ) is True
    assert is_probable_file_dialog(
        "Notepad",
        "notes.txt - Notepad",
        ["Edit"],
    ) is False


def test_context_menu_adds_quick_switch_action_when_enabled(monkeypatch):
    monkeypatch.setattr(context_menu, "QMenu", FakeMenu)
    entry = FileEntry(
        frn=10,
        parent_frn=NTFS_ROOT_FRN,
        name="Reports",
        drive="C",
        attributes=FILE_ATTRIBUTE_DIRECTORY,
    )
    entry._path = "C:\\docs\\Reports"

    menu = build_context_menu(
        [entry],
        TempIndex(),
        dialog_quick_switch_enabled=True,
    )

    assert any(
        action.text() == "Quick Switch Open/Save Dialog Here"
        for action in menu.actions()
    )


def test_context_menu_adds_compare_action_for_two_files(monkeypatch):
    monkeypatch.setattr(context_menu, "QMenu", FakeMenu)
    first = FileEntry(frn=10, parent_frn=NTFS_ROOT_FRN, name="a.txt", drive="C", attributes=0)
    second = FileEntry(frn=11, parent_frn=NTFS_ROOT_FRN, name="b.txt", drive="C", attributes=0)
    first._path = "C:\\docs\\a.txt"
    second._path = "C:\\docs\\b.txt"

    menu = build_context_menu(
        [first, second],
        TempIndex(),
        compare_callback=lambda _entries: None,
    )

    assert any(action.text() == "Compare Selected Files" for action in menu.actions())
