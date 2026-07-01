"""Rendered/offscreen accessibility smoke tests for primary QuickFind widgets."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.index import FileIndex
from gui.diagnostics_dialog import DiagnosticsDialog
from gui.main_window import MainWindow
from gui.preview_pane import PreviewPane
from gui.results_view import ResultsView
from gui.settings_dialog import Settings, SettingsDialog


def _qt_is_mocked() -> bool:
    return QApplication.__module__.startswith("unittest.mock")


pytestmark = pytest.mark.skipif(_qt_is_mocked(), reason="Rendered Qt smoke tests require PyQt6.")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeTray:
    def __init__(self, parent=None):
        self.show_requested = FakeSignal()
        self.quit_requested = FakeSignal()

    def show(self):
        pass

    def hide(self):
        pass

    def isVisible(self):
        return False

    def start_hotkey(self):
        pass

    def stop_hotkey(self):
        pass

    def update_tooltip(self, text: str):
        pass


class FakeLauncherPopup:
    def __init__(self, *args, **kwargs):
        pass

    def set_dialog_quick_switch_enabled(self, enabled: bool):
        pass

    def isVisible(self):
        return False

    def dismiss(self):
        pass

    def show_popup(self):
        pass


class FakeIndex:
    def index_diagnostics(self):
        return {
            "source": "test",
            "total_entries": 0,
            "total_files": 0,
            "total_folders": 0,
            "last_update": "",
            "monitor_running": False,
            "rescan_running": False,
            "pending_usn_catchup": False,
            "drives": [
                {
                    "drive": "C",
                    "state": "online",
                    "mode": "MFT + USN",
                    "entries": 0,
                    "files": 0,
                    "folders": 0,
                    "monitoring": False,
                    "rescanning": False,
                }
            ],
        }


def _assert_accessible(widget, expected_name: str | None = None, *, require_description: bool = True):
    name = widget.accessibleName()
    description = widget.accessibleDescription()
    if expected_name is not None:
        assert name == expected_name
    else:
        assert name
    if require_description:
        assert description
    assert getattr(widget, "_quickfind_accessible_name", name) == name


def test_main_window_keyboard_flow_has_accessible_primary_controls(qapp, monkeypatch):
    import gui.launcher_popup as launcher_popup
    import gui.main_window as main_window_mod

    settings = Settings(index_on_startup=False, enable_http_server=False, start_maximized=False)
    monkeypatch.setattr(Settings, "load", staticmethod(lambda: settings))
    monkeypatch.setattr(main_window_mod, "SystemTray", FakeTray)
    monkeypatch.setattr(launcher_popup, "LauncherPopup", FakeLauncherPopup)

    window = MainWindow()
    qapp.processEvents()

    try:
        flow = window._keyboard_flow
        assert [widget.accessibleName() for widget in flow] == [
            "Filter type",
            "Workspace roots",
            "Search input",
            "Search results tabs",
            "Search results",
        ]
        for widget in flow:
            assert widget.focusPolicy() != Qt.FocusPolicy.NoFocus
        _assert_accessible(window._preview_pane, "Preview pane")
        _assert_accessible(window._status_label, "Status message")
    finally:
        window._quit()
        qapp.processEvents()


def test_settings_dialog_primary_controls_have_accessible_metadata(qapp):
    dialog = SettingsDialog(Settings(index_on_startup=False))
    qapp.processEvents()

    try:
        for widget, name in [
            (dialog._tabs_widget, "Settings sections"),
            (dialog._index_startup, "Index on startup"),
            (dialog._search_delay, "Search delay"),
            (dialog._drives_list, "Drives to index"),
            (dialog._network_root, "Network share root"),
            (dialog._content_index_enabled, "Enable content indexing"),
            (dialog._http_auth_token, "HTTP authentication token"),
            (dialog._export_settings_btn, "Export settings"),
            (dialog._dialog_buttons, "Settings actions"),
        ]:
            _assert_accessible(widget, name)
    finally:
        dialog.close()


def test_results_and_preview_surfaces_have_accessible_metadata(qapp):
    index = FileIndex()
    results = ResultsView(index)
    preview = PreviewPane(index)
    qapp.processEvents()

    try:
        for widget, name in [
            (results.breadcrumb_header, "Selected result path"),
            (results.table_view, "Search results"),
            (results.column_view, "Path column results"),
            (results.thumb_view, "Thumbnail results"),
            (preview._header, "Preview header"),
            (preview._stack, "Preview content"),
            (preview._info_label, "Preview empty state"),
        ]:
            _assert_accessible(widget, name, require_description=bool(widget.accessibleDescription()))
    finally:
        results.close()
        preview.close()


def test_diagnostics_dialog_tables_and_actions_have_accessible_metadata(qapp, monkeypatch):
    import gui.diagnostics_dialog as diagnostics_mod

    monkeypatch.setattr(
        diagnostics_mod,
        "cache_diagnostics",
        lambda: {"integrity_ok": True, "entry_count": 0, "db_size_bytes": 0, "content": {}, "drives": []},
    )
    monkeypatch.setattr(
        diagnostics_mod,
        "service_health",
        lambda: {"available": False, "state": "unreachable", "checked_at": "test"},
    )

    dialog = DiagnosticsDialog(FakeIndex())
    qapp.processEvents()

    try:
        for widget, name in [
            (dialog._summary_table, "Diagnostics summary"),
            (dialog._drive_table, "Drive diagnostics"),
            (dialog._refresh_button, "Refresh diagnostics"),
            (dialog._rebuild_button, "Rebuild index"),
            (dialog._save_cache_button, "Save cache"),
            (dialog._start_service_button, "Start service"),
            (dialog._stop_service_button, "Stop service"),
            (dialog._export_bundle_button, "Export support bundle"),
        ]:
            _assert_accessible(widget, name)
    finally:
        dialog.close()
