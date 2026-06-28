"""Index/cache/service diagnostics dialog."""

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from core.cache import cache_diagnostics
from gui.status_indicators import diagnostics_summary_rows, yes_no
from gui.theme import MOCHA
from service.ipc import service_health


class DiagnosticsDialog(QDialog):
    """Shows trust and recovery diagnostics for the active index."""

    def __init__(self, index, actions: dict[str, Callable[[], str | None]] | None = None,
                 parent=None):
        super().__init__(parent)
        self._index = index
        self._actions = actions or {}
        self.setWindowTitle("QuickFind Diagnostics")
        self.setMinimumSize(760, 560)
        self._setup_ui()
        self.refresh()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self._message = QLabel("")
        self._message.setStyleSheet(f"color: {MOCHA['subtext0']};")
        layout.addWidget(self._message)

        self._summary_table = QTableWidget(0, 2)
        self._summary_table.setHorizontalHeaderLabels(["Signal", "Value"])
        self._summary_table.verticalHeader().setVisible(False)
        self._summary_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._summary_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._summary_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._summary_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._summary_table, 1)

        self._drive_table = QTableWidget(0, 9)
        self._drive_table.setHorizontalHeaderLabels([
            "Drive", "Mode", "Entries", "Files", "Folders",
            "Journal ID", "Next USN", "Monitor", "Rescan",
        ])
        self._drive_table.verticalHeader().setVisible(False)
        self._drive_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._drive_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._drive_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._drive_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._drive_table, 1)

        action_row = QHBoxLayout()
        self._refresh_button = QPushButton("Refresh")
        self._refresh_button.clicked.connect(self.refresh)
        action_row.addWidget(self._refresh_button)

        self._rebuild_button = QPushButton("Rebuild Index")
        self._rebuild_button.clicked.connect(lambda: self._run_action("rebuild"))
        action_row.addWidget(self._rebuild_button)

        self._save_cache_button = QPushButton("Save Cache")
        self._save_cache_button.clicked.connect(lambda: self._run_action("save_cache"))
        action_row.addWidget(self._save_cache_button)

        self._start_service_button = QPushButton("Start Service")
        self._start_service_button.clicked.connect(lambda: self._run_action("start_service"))
        action_row.addWidget(self._start_service_button)

        self._stop_service_button = QPushButton("Stop Service")
        self._stop_service_button.clicked.connect(lambda: self._run_action("stop_service"))
        action_row.addWidget(self._stop_service_button)

        action_row.addStretch(1)
        layout.addLayout(action_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def refresh(self) -> None:
        index_diag = self._index.index_diagnostics()
        cache_diag = cache_diagnostics()
        service_diag = service_health()

        self._set_summary_rows(diagnostics_summary_rows(index_diag, cache_diag, service_diag))
        self._set_drive_rows(index_diag.get("drives", []), cache_diag.get("drives", []))
        if not self._message.text():
            self._message.setText("Diagnostics refreshed.")

    def _set_summary_rows(self, rows: list[tuple[str, str]]) -> None:
        self._summary_table.setRowCount(len(rows))
        for row_idx, (label, value) in enumerate(rows):
            self._summary_table.setItem(row_idx, 0, QTableWidgetItem(label))
            self._summary_table.setItem(row_idx, 1, QTableWidgetItem(value))

    def _set_drive_rows(self, index_rows: list[dict], cache_rows: list[dict]) -> None:
        cache_by_drive = {row.get("drive"): row for row in cache_rows}
        merged = []
        seen = set()
        for row in index_rows:
            drive = row.get("drive", "")
            cache_row = cache_by_drive.get(drive, {})
            merged_row = dict(row)
            if not merged_row.get("journal_id"):
                merged_row["journal_id"] = cache_row.get("journal_id", 0)
            if not merged_row.get("next_usn"):
                merged_row["next_usn"] = cache_row.get("next_usn", 0)
            merged.append(merged_row)
            seen.add(drive)

        for drive, row in cache_by_drive.items():
            if drive in seen:
                continue
            merged.append({
                "drive": drive,
                "mode": f"cache {row.get('mode', '')}".strip(),
                "entries": 0,
                "files": 0,
                "folders": 0,
                "journal_id": row.get("journal_id", 0),
                "next_usn": row.get("next_usn", 0),
                "monitoring": False,
                "rescanning": False,
            })

        self._drive_table.setRowCount(len(merged))
        for row_idx, row in enumerate(merged):
            values = [
                row.get("drive", ""),
                row.get("mode", ""),
                f"{int(row.get('entries') or 0):,}",
                f"{int(row.get('files') or 0):,}",
                f"{int(row.get('folders') or 0):,}",
                str(row.get("journal_id") or ""),
                str(row.get("next_usn") or ""),
                yes_no(bool(row.get("monitoring"))),
                yes_no(bool(row.get("rescanning"))),
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_idx not in (0, 1):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._drive_table.setItem(row_idx, col_idx, item)

    def _run_action(self, action_name: str) -> None:
        handler = self._actions.get(action_name)
        if handler is None:
            self._message.setText("Action unavailable.")
            return
        try:
            message = handler()
            self._message.setText(message or "Action completed.")
        except Exception as exc:
            self._message.setText(f"Action failed: {exc}")
        self.refresh()
