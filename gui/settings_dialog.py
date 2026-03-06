"""
Settings dialog for QuickFind configuration.
"""

import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QGroupBox, QPushButton, QDialogButtonBox, QLabel,
    QListWidget, QListWidgetItem, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal

from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.Settings')

CONFIG_DIR = Path.home() / '.quickfind'
SETTINGS_FILE = CONFIG_DIR / 'settings.json'


@dataclass
class Settings:
    """Application settings."""
    # Indexing
    index_on_startup: bool = True
    index_drives: list[str] = field(default_factory=list)  # Empty = all NTFS
    monitor_usn: bool = True
    usn_poll_interval_ms: int = 1000
    exclude_hidden: bool = False
    exclude_system: bool = False

    # Search
    default_match_case: bool = False
    default_regex: bool = False
    default_max_results: int = 0  # 0 = unlimited
    search_delay_ms: int = 0

    # UI
    show_preview_pane: bool = False
    show_filter_bar: bool = True
    show_status_bar: bool = True
    start_minimized: bool = False
    minimize_to_tray: bool = True
    close_to_tray: bool = True
    remember_window_size: bool = True
    window_width: int = 1200
    window_height: int = 700
    start_maximized: bool = True

    # Network
    enable_http_server: bool = False
    http_port: int = 8080
    http_bind: str = "127.0.0.1"

    # EFU file lists
    efu_files: list[str] = field(default_factory=list)

    def save(self):
        CONFIG_DIR.mkdir(exist_ok=True)
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    @staticmethod
    def load() -> 'Settings':
        if not SETTINGS_FILE.exists():
            return Settings()
        try:
            with open(SETTINGS_FILE, 'r') as f:
                data = json.load(f)
            s = Settings()
            for k, v in data.items():
                if hasattr(s, k):
                    setattr(s, k, v)
            return s
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return Settings()


class SettingsDialog(QDialog):
    """Settings dialog with tabbed pages."""

    settings_changed = pyqtSignal(object)  # Settings

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("QuickFind - Settings")
        self.setMinimumSize(600, 500)
        self._settings = Settings(**asdict(settings))  # Work on a copy

        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        # ── General Tab ─────────────────────────────────
        general = QWidget()
        general_layout = QVBoxLayout(general)

        # Indexing group
        idx_group = QGroupBox("Indexing")
        idx_form = QFormLayout(idx_group)

        self._index_startup = QCheckBox("Index on startup")
        idx_form.addRow(self._index_startup)

        self._monitor_usn = QCheckBox("Monitor USN journal for real-time updates")
        idx_form.addRow(self._monitor_usn)

        self._usn_interval = QSpinBox()
        self._usn_interval.setRange(100, 10000)
        self._usn_interval.setSuffix(" ms")
        idx_form.addRow("USN poll interval:", self._usn_interval)

        self._exclude_hidden = QCheckBox("Exclude hidden files from index")
        idx_form.addRow(self._exclude_hidden)

        self._exclude_system = QCheckBox("Exclude system files from index")
        idx_form.addRow(self._exclude_system)

        general_layout.addWidget(idx_group)

        # Search group
        search_group = QGroupBox("Search")
        search_form = QFormLayout(search_group)

        self._default_case = QCheckBox("Match case by default")
        search_form.addRow(self._default_case)

        self._default_regex = QCheckBox("Enable regex by default")
        search_form.addRow(self._default_regex)

        self._max_results = QSpinBox()
        self._max_results.setRange(0, 10000000)
        self._max_results.setSpecialValueText("Unlimited")
        search_form.addRow("Max results:", self._max_results)

        self._search_delay = QSpinBox()
        self._search_delay.setRange(0, 2000)
        self._search_delay.setSuffix(" ms")
        search_form.addRow("Search delay:", self._search_delay)

        general_layout.addWidget(search_group)
        general_layout.addStretch()
        tabs.addTab(general, "General")

        # ── UI Tab ──────────────────────────────────────
        ui = QWidget()
        ui_layout = QVBoxLayout(ui)

        ui_group = QGroupBox("Interface")
        ui_form = QFormLayout(ui_group)

        self._show_preview = QCheckBox("Show preview pane")
        ui_form.addRow(self._show_preview)

        self._show_filters = QCheckBox("Show filter dropdown")
        ui_form.addRow(self._show_filters)

        self._show_status = QCheckBox("Show status bar")
        ui_form.addRow(self._show_status)

        self._start_min = QCheckBox("Start minimized")
        ui_form.addRow(self._start_min)

        self._min_tray = QCheckBox("Minimize to system tray")
        ui_form.addRow(self._min_tray)

        self._close_tray = QCheckBox("Close to system tray")
        ui_form.addRow(self._close_tray)

        self._remember_size = QCheckBox("Remember window size")
        ui_form.addRow(self._remember_size)

        ui_layout.addWidget(ui_group)
        ui_layout.addStretch()
        tabs.addTab(ui, "UI")

        # ── Drives Tab ──────────────────────────────────
        drives_tab = QWidget()
        drives_layout = QVBoxLayout(drives_tab)

        drives_label = QLabel("Drives to index (leave empty to auto-detect all NTFS drives):")
        drives_layout.addWidget(drives_label)

        self._drives_list = QListWidget()
        drives_layout.addWidget(self._drives_list)

        # Populate with available drives
        from core.ntfs import get_ntfs_drives
        for d in get_ntfs_drives():
            item = QListWidgetItem(f"{d}:")
            item.setCheckState(Qt.CheckState.Checked)
            self._drives_list.addItem(item)

        tabs.addTab(drives_tab, "Drives")

        # ── EFU Tab ─────────────────────────────────────
        efu_tab = QWidget()
        efu_layout = QVBoxLayout(efu_tab)

        efu_label = QLabel("EFU file lists for non-NTFS / network drives:")
        efu_layout.addWidget(efu_label)

        self._efu_list = QListWidget()
        efu_layout.addWidget(self._efu_list)

        efu_buttons = QHBoxLayout()
        add_efu = QPushButton("Add EFU File")
        add_efu.clicked.connect(self._add_efu)
        remove_efu = QPushButton("Remove")
        remove_efu.clicked.connect(self._remove_efu)
        efu_buttons.addWidget(add_efu)
        efu_buttons.addWidget(remove_efu)
        efu_buttons.addStretch()
        efu_layout.addLayout(efu_buttons)

        tabs.addTab(efu_tab, "File Lists")

        # ── HTTP Server Tab ─────────────────────────────
        http_tab = QWidget()
        http_layout = QVBoxLayout(http_tab)

        http_group = QGroupBox("HTTP Server")
        http_form = QFormLayout(http_group)

        self._enable_http = QCheckBox("Enable HTTP server")
        http_form.addRow(self._enable_http)

        self._http_port = QSpinBox()
        self._http_port.setRange(1, 65535)
        http_form.addRow("Port:", self._http_port)

        self._http_bind = QLineEdit()
        http_form.addRow("Bind address:", self._http_bind)

        http_layout.addWidget(http_group)
        http_layout.addStretch()
        tabs.addTab(http_tab, "HTTP Server")

        # ── Dialog buttons ──────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        layout.addWidget(buttons)

    def _load_values(self):
        s = self._settings
        self._index_startup.setChecked(s.index_on_startup)
        self._monitor_usn.setChecked(s.monitor_usn)
        self._usn_interval.setValue(s.usn_poll_interval_ms)
        self._exclude_hidden.setChecked(s.exclude_hidden)
        self._exclude_system.setChecked(s.exclude_system)
        self._default_case.setChecked(s.default_match_case)
        self._default_regex.setChecked(s.default_regex)
        self._max_results.setValue(s.default_max_results)
        self._search_delay.setValue(s.search_delay_ms)
        self._show_preview.setChecked(s.show_preview_pane)
        self._show_filters.setChecked(s.show_filter_bar)
        self._show_status.setChecked(s.show_status_bar)
        self._start_min.setChecked(s.start_minimized)
        self._min_tray.setChecked(s.minimize_to_tray)
        self._close_tray.setChecked(s.close_to_tray)
        self._remember_size.setChecked(s.remember_window_size)
        self._enable_http.setChecked(s.enable_http_server)
        self._http_port.setValue(s.http_port)
        self._http_bind.setText(s.http_bind)

        for path in s.efu_files:
            self._efu_list.addItem(path)

    def _apply(self):
        s = self._settings
        s.index_on_startup = self._index_startup.isChecked()
        s.monitor_usn = self._monitor_usn.isChecked()
        s.usn_poll_interval_ms = self._usn_interval.value()
        s.exclude_hidden = self._exclude_hidden.isChecked()
        s.exclude_system = self._exclude_system.isChecked()
        s.default_match_case = self._default_case.isChecked()
        s.default_regex = self._default_regex.isChecked()
        s.default_max_results = self._max_results.value()
        s.search_delay_ms = self._search_delay.value()
        s.show_preview_pane = self._show_preview.isChecked()
        s.show_filter_bar = self._show_filters.isChecked()
        s.show_status_bar = self._show_status.isChecked()
        s.start_minimized = self._start_min.isChecked()
        s.minimize_to_tray = self._min_tray.isChecked()
        s.close_to_tray = self._close_tray.isChecked()
        s.remember_window_size = self._remember_size.isChecked()
        s.enable_http_server = self._enable_http.isChecked()
        s.http_port = self._http_port.value()
        s.http_bind = self._http_bind.text()

        # Drives
        drives = []
        for i in range(self._drives_list.count()):
            item = self._drives_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                drives.append(item.text().rstrip(':'))
        s.index_drives = drives

        # EFU files
        s.efu_files = []
        for i in range(self._efu_list.count()):
            s.efu_files.append(self._efu_list.item(i).text())

        self.settings_changed.emit(s)

    def _apply_and_accept(self):
        self._apply()
        self.accept()

    def _add_efu(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select EFU File", "",
            "Everything File Lists (*.efu);;All Files (*)"
        )
        if path:
            self._efu_list.addItem(path)

    def _remove_efu(self):
        row = self._efu_list.currentRow()
        if row >= 0:
            self._efu_list.takeItem(row)

    def get_settings(self) -> Settings:
        return self._settings
