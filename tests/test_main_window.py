"""Tests for main window status indicator state."""

from gui.status_indicators import index_mode_indicator_state


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
