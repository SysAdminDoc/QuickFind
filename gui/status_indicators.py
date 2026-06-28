"""Pure status-bar indicator state helpers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IndexModeIndicator:
    text: str
    tooltip: str
    visible: bool


def index_mode_indicator_state(is_admin_mode: bool) -> IndexModeIndicator:
    """Return the status-bar badge state for the active index mode."""
    if is_admin_mode:
        return IndexModeIndicator(
            text="",
            tooltip="Indexing with NTFS MFT and USN Journal",
            visible=False,
        )

    return IndexModeIndicator(
        text="Non-admin scan",
        tooltip=(
            "MFT access is unavailable; QuickFind is using os.scandir fallback. "
            "Indexing and updates may be slower."
        ),
        visible=True,
    )
