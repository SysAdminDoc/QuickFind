"""Tests for main window status indicator state."""

from gui.status_indicators import diagnostics_summary_rows, format_bytes, index_mode_indicator_state


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
