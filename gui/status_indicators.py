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


def format_bytes(size: int) -> str:
    """Format byte counts for compact diagnostics labels."""
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size // 1024} KB"
    return f"{size} B"


def yes_no(value: bool) -> str:
    return "Yes" if value else "No"


def diagnostics_summary_rows(index_diag: dict, cache_diag: dict, service_diag: dict) -> list[tuple[str, str]]:
    """Build stable label/value rows for diagnostics UI and tests."""
    content = cache_diag.get("content", {})
    integrity = cache_diag.get("integrity_ok")
    if integrity is True:
        integrity_text = "OK"
    elif integrity is False:
        integrity_text = "Failed"
    else:
        integrity_text = "Not checked"

    service_state = service_diag.get("state", "unreachable")
    if service_diag.get("available"):
        service_state = f"{service_state} ({service_diag.get('entries', 0):,} entries)"

    return [
        ("Index source", str(index_diag.get("source", ""))),
        ("Indexed entries", f"{int(index_diag.get('total_entries') or 0):,}"),
        ("Files / folders", f"{int(index_diag.get('total_files') or 0):,} / {int(index_diag.get('total_folders') or 0):,}"),
        ("Last index update", str(index_diag.get("last_update") or "Never")),
        ("Monitor / rescan", f"{yes_no(bool(index_diag.get('monitor_running')))} / {yes_no(bool(index_diag.get('rescan_running')))}"),
        ("Pending USN catchup", yes_no(bool(index_diag.get("pending_usn_catchup")))),
        ("Cache integrity", integrity_text),
        ("Cache entries", f"{int(cache_diag.get('entry_count') or 0):,}"),
        ("Cache size", format_bytes(int(cache_diag.get("db_size_bytes") or 0))),
        ("Cache last saved", str(cache_diag.get("last_saved") or "Never")),
        ("SQLite / FTS", str(cache_diag.get("fts5_status", ""))),
        ("Content cache", f"{int(content.get('count') or 0):,} docs / {format_bytes(int(content.get('text_bytes') or 0))}"),
        ("Service heartbeat", service_state),
        ("Service checked", str(service_diag.get("checked_at") or "")),
    ]
