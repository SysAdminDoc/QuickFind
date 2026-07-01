"""Tests for main window status indicator state."""

import gui.context_menu as context_menu
from gui.context_menu import RecycleResult, _delete_to_recycle
from gui.main_window import _delete_feedback_message
from gui.status_indicators import (
    diagnostics_summary_rows,
    drive_state_indicator_state,
    format_bytes,
    index_mode_indicator_state,
)


def test_index_mode_indicator_hides_for_mft_mode():
    state = index_mode_indicator_state(True)

    assert state.text == ""
    assert state.visible is False
    assert "NTFS MFT" in state.tooltip


def test_index_mode_indicator_shows_non_admin_fallback():
    state = index_mode_indicator_state(False)

    assert state.text == "Non-admin scan"
    assert state.visible is True
    assert "os.scandir fallback" in state.tooltip


def test_drive_state_indicator_hides_when_all_drives_fresh():
    state = drive_state_indicator_state([
        {"drive": "C", "state": "online", "stale": False},
    ])

    assert state.text == ""
    assert state.visible is False


def test_drive_state_indicator_shows_offline_or_stale_drives():
    state = drive_state_indicator_state([
        {"drive": "C", "state": "online", "stale": False},
        {
            "drive": "E",
            "state": "offline",
            "stale": True,
            "stale_reason": "Drive unavailable; cached results may be stale",
        },
        {
            "drive": "F",
            "state": "stale",
            "stale": True,
            "stale_reason": "Loaded from cache; waiting for catchup or refresh",
        },
    ])

    assert state.text == "2 drives stale"
    assert state.visible is True
    assert "E: offline" in state.tooltip
    assert "F: stale" in state.tooltip


def test_diagnostics_summary_rows_include_cache_service_and_content():
    rows = diagnostics_summary_rows(
        {
            "source": "SQLite cache + USN catchup",
            "total_entries": 12,
            "total_files": 9,
            "total_folders": 3,
            "last_update": "2026-06-28T12:00:00",
            "monitor_running": True,
            "rescan_running": False,
            "pending_usn_catchup": False,
        },
        {
            "integrity_ok": True,
            "entry_count": 12,
            "db_size_bytes": 4096,
            "last_saved": "2026-06-28T12:00:01",
            "fts5_status": "FTS5 disabled",
            "content": {"count": 2, "text_bytes": 2048},
        },
        {
            "available": True,
            "state": "monitoring",
            "entries": 12,
            "checked_at": "2026-06-28T12:00:02",
        },
    )

    values = dict(rows)
    assert values["Index source"] == "SQLite cache + USN catchup"
    assert values["Cache integrity"] == "OK"
    assert values["Cache size"] == "4 KB"
    assert values["Content cache"] == "2 docs / 2 KB"
    assert values["Service heartbeat"] == "monitoring (12 entries)"


def test_format_bytes_uses_compact_units():
    assert format_bytes(512) == "512 B"
    assert format_bytes(2048) == "2 KB"
    assert format_bytes(2 * 1024 * 1024) == "2.0 MB"


def test_delete_feedback_message_reports_success_and_recovery_hint():
    message = _delete_feedback_message(
        [
            RecycleResult("C:\\docs\\report.txt", True),
            RecycleResult("C:\\docs\\notes.txt", True),
        ],
        removed_count=2,
    )

    assert "Moved 2 items to Recycle Bin: report.txt + 1 more" in message
    assert "Removed 2 items from current results" in message
    assert "Restore from Windows Recycle Bin if needed" in message


def test_delete_feedback_message_reports_shell_errors():
    message = _delete_feedback_message([
        RecycleResult("C:\\docs\\blocked.txt", False, error_code=5, error="SHFileOperationW returned 5"),
    ])

    assert "Recycle failed for 1 item: blocked.txt" in message
    assert "SHFileOperationW returned 5" in message
    assert "Restore from Windows Recycle Bin" not in message


def test_delete_to_recycle_returns_success(monkeypatch):
    class FakeShell:
        def SHFileOperationW(self, operation):
            operation._obj.fAnyOperationsAborted = 0
            return 0

    monkeypatch.setattr(context_menu, "shell32", FakeShell())

    result = _delete_to_recycle("C:\\docs\\report.txt")

    assert result == RecycleResult("C:\\docs\\report.txt", True)


def test_delete_to_recycle_returns_shell_error(monkeypatch):
    class FakeShell:
        def SHFileOperationW(self, operation):
            operation._obj.fAnyOperationsAborted = 0
            return 5

    monkeypatch.setattr(context_menu, "shell32", FakeShell())

    result = _delete_to_recycle("C:\\docs\\blocked.txt")

    assert result.ok is False
    assert result.error_code == 5
    assert result.error == "SHFileOperationW returned 5"
