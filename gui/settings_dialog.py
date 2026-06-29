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
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from gui.theme import MOCHA
from gui.settings_validation import sanitize_settings_data

logger = logging.getLogger('QuickFind.Settings')

CONFIG_DIR = Path.home() / '.quickfind'
SETTINGS_FILE = CONFIG_DIR / 'settings.json'

DEFAULT_COLUMN_VISIBILITY = {
    'name': True,
    'path': True,
    'size': True,
    'modified': True,
    'created': False,
    'attributes': False,
}


@dataclass
class Settings:
    """Application settings."""
    # Indexing
    index_on_startup: bool = True
    index_drives: list[str] = field(default_factory=list)  # Empty = all supported drives
    monitor_usn: bool = True
    usn_poll_interval_ms: int = 1000
    drive_startup_delay_seconds: int = 0
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
    column_visibility: dict = field(default_factory=lambda: dict(DEFAULT_COLUMN_VISIBILITY))
    enable_dialog_quick_switch: bool = False

    # Network
    enable_http_server: bool = False
    http_port: int = 8080
    http_bind: str = "127.0.0.1"
    http_auth_token: str = ""
    http_use_https: bool = False
    https_cert_file: str = ""
    https_key_file: str = ""

    # EFU file lists
    efu_files: list[str] = field(default_factory=list)

    # Content indexing
    content_index_enabled: bool = False
    content_index_roots: list[str] = field(default_factory=list)
    content_index_extensions: list[str] = field(default_factory=list)
    content_index_max_cache_mb: int = 512
    content_index_max_file_mb: int = 10

    def sanitize(self) -> list[str]:
        data, warnings = sanitize_settings_data(asdict(self), asdict(Settings()))
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)
        return warnings

    def save(self):
        CONFIG_DIR.mkdir(exist_ok=True)
        try:
            for warning in self.sanitize():
                logger.warning(warning)
            tmp = SETTINGS_FILE.with_suffix('.tmp')
            with open(tmp, 'w') as f:
                json.dump(asdict(self), f, indent=2)
            tmp.replace(SETTINGS_FILE)
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
            for warning in s.sanitize():
                logger.warning(warning)
            return s
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return Settings()

    def export_to_file(self, path: str):
        """Export settings to a JSON file."""
        with open(path, 'w') as f:
            json.dump(asdict(self), f, indent=2)

    @staticmethod
    def import_from_file(path: str) -> 'Settings':
        """Import settings from a JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        s = Settings()
        for k, v in data.items():
            if hasattr(s, k):
                setattr(s, k, v)
        for warning in s.sanitize():
            logger.warning(warning)
        return s


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

        # -- General Tab -----------------------------------
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

        # -- UI Tab ----------------------------------------
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

        self._dialog_quick_switch = QCheckBox("Enable Open/Save dialog Quick Switch")
        ui_form.addRow(self._dialog_quick_switch)

        self._start_min = QCheckBox("Start minimized")
        ui_form.addRow(self._start_min)

        self._min_tray = QCheckBox("Minimize to system tray")
        ui_form.addRow(self._min_tray)

        self._close_tray = QCheckBox("Close to system tray")
        ui_form.addRow(self._close_tray)

        self._remember_size = QCheckBox("Remember window size")
        ui_form.addRow(self._remember_size)

        ui_layout.addWidget(ui_group)

        # Column visibility group
        col_group = QGroupBox("Column Visibility")
        col_form = QFormLayout(col_group)

        self._col_checks = {}
        for col_name, default_vis in DEFAULT_COLUMN_VISIBILITY.items():
            cb = QCheckBox(col_name.capitalize())
            self._col_checks[col_name] = cb
            col_form.addRow(cb)

        ui_layout.addWidget(col_group)
        ui_layout.addStretch()
        tabs.addTab(ui, "UI")

        # -- Drives Tab ------------------------------------
        drives_tab = QWidget()
        drives_layout = QVBoxLayout(drives_tab)

        drives_label = QLabel("Drives to index (NTFS uses MFT, FAT/exFAT/ReFS uses directory walk):")
        drives_layout.addWidget(drives_label)

        delay_form = QFormLayout()
        self._drive_startup_delay = QSpinBox()
        self._drive_startup_delay.setRange(0, 120)
        self._drive_startup_delay.setSuffix(" s")
        delay_form.addRow("Startup drive delay:", self._drive_startup_delay)
        drives_layout.addLayout(delay_form)

        self._drives_list = QListWidget()
        drives_layout.addWidget(self._drives_list)

        # Populate with all supported drives
        from core.ntfs import get_all_drives
        for d in get_all_drives():
            label = f"{d.letter}: [{d.filesystem}]"
            if d.label:
                label += f" {d.label}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, d.letter)
            item.setCheckState(Qt.CheckState.Checked)
            self._drives_list.addItem(item)

        tabs.addTab(drives_tab, "Drives")

        # -- EFU Tab ---------------------------------------
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

        # -- Content Tab -----------------------------------
        content_tab = QWidget()
        content_layout = QVBoxLayout(content_tab)

        content_group = QGroupBox("Content Indexing")
        content_form = QFormLayout(content_group)

        self._content_index_enabled = QCheckBox("Enable background content indexing after file indexing")
        content_form.addRow(self._content_index_enabled)

        self._content_index_roots = QLineEdit()
        self._content_index_roots.setPlaceholderText("Blank = all indexed paths; separate roots with semicolons")
        content_form.addRow("Roots:", self._content_index_roots)

        self._content_index_extensions = QLineEdit()
        self._content_index_extensions.setPlaceholderText("Blank = all supported; example: txt;pdf;docx;pptx")
        content_form.addRow("Extensions:", self._content_index_extensions)

        self._content_index_max_cache = QSpinBox()
        self._content_index_max_cache.setRange(1, 102400)
        self._content_index_max_cache.setSuffix(" MB")
        content_form.addRow("Cache quota:", self._content_index_max_cache)

        self._content_index_max_file = QSpinBox()
        self._content_index_max_file.setRange(1, 1024)
        self._content_index_max_file.setSuffix(" MB")
        content_form.addRow("Max file size:", self._content_index_max_file)

        content_layout.addWidget(content_group)
        adapter_lines = []
        try:
            from core.content import adapter_diagnostics
            for diagnostic in adapter_diagnostics():
                state = "available" if diagnostic.available else diagnostic.detail
                adapter_lines.append(f"{diagnostic.name}: {state}")
        except Exception as exc:
            adapter_lines.append(f"Adapter diagnostics unavailable: {exc}")
        self._content_adapter_status = QLabel("\n".join(adapter_lines))
        self._content_adapter_status.setWordWrap(True)
        self._content_adapter_status.setStyleSheet(f"color: {MOCHA['subtext0']}; font-size: 11px;")
        content_layout.addWidget(self._content_adapter_status)
        content_layout.addStretch()
        tabs.addTab(content_tab, "Content")

        # -- HTTP Server Tab -------------------------------
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

        self._http_auth_token = QLineEdit()
        self._http_auth_token.setPlaceholderText("Leave empty to disable authentication; never sent in URLs")
        http_form.addRow("Auth token:", self._http_auth_token)

        self._http_use_https = QCheckBox("Enable HTTPS")
        http_form.addRow(self._http_use_https)

        cert_row = QHBoxLayout()
        self._https_cert_file = QLineEdit()
        cert_btn = QPushButton("Browse...")
        cert_btn.clicked.connect(lambda: self._browse_file(self._https_cert_file, "Select TLS Certificate"))
        cert_row.addWidget(self._https_cert_file)
        cert_row.addWidget(cert_btn)
        http_form.addRow("TLS certificate:", cert_row)

        key_row = QHBoxLayout()
        self._https_key_file = QLineEdit()
        key_btn = QPushButton("Browse...")
        key_btn.clicked.connect(lambda: self._browse_file(self._https_key_file, "Select TLS Private Key"))
        key_row.addWidget(self._https_key_file)
        key_row.addWidget(key_btn)
        http_form.addRow("TLS private key:", key_row)

        http_layout.addWidget(http_group)
        http_layout.addStretch()
        tabs.addTab(http_tab, "HTTP Server")

        # -- Export/Import + Dialog buttons ----------------
        bottom_layout = QHBoxLayout()

        export_btn = QPushButton("Export Settings...")
        export_btn.clicked.connect(self._export_settings)
        import_btn = QPushButton("Import Settings...")
        import_btn.clicked.connect(self._import_settings)
        bottom_layout.addWidget(export_btn)
        bottom_layout.addWidget(import_btn)
        bottom_layout.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        buttons.accepted.connect(self._apply_and_accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        bottom_layout.addWidget(buttons)

        layout.addLayout(bottom_layout)

    def _load_values(self):
        s = self._settings
        self._index_startup.setChecked(s.index_on_startup)
        self._monitor_usn.setChecked(s.monitor_usn)
        self._usn_interval.setValue(s.usn_poll_interval_ms)
        self._drive_startup_delay.setValue(s.drive_startup_delay_seconds)
        self._exclude_hidden.setChecked(s.exclude_hidden)
        self._exclude_system.setChecked(s.exclude_system)
        self._default_case.setChecked(s.default_match_case)
        self._default_regex.setChecked(s.default_regex)
        self._max_results.setValue(s.default_max_results)
        self._search_delay.setValue(s.search_delay_ms)
        self._show_preview.setChecked(s.show_preview_pane)
        self._show_filters.setChecked(s.show_filter_bar)
        self._show_status.setChecked(s.show_status_bar)
        self._dialog_quick_switch.setChecked(s.enable_dialog_quick_switch)
        self._start_min.setChecked(s.start_minimized)
        self._min_tray.setChecked(s.minimize_to_tray)
        self._close_tray.setChecked(s.close_to_tray)
        self._remember_size.setChecked(s.remember_window_size)
        self._enable_http.setChecked(s.enable_http_server)
        self._http_port.setValue(s.http_port)
        self._http_bind.setText(s.http_bind)
        self._http_auth_token.setText(s.http_auth_token)
        self._http_use_https.setChecked(s.http_use_https)
        self._https_cert_file.setText(s.https_cert_file)
        self._https_key_file.setText(s.https_key_file)

        # Column visibility
        for col_name, cb in self._col_checks.items():
            visible = s.column_visibility.get(col_name, DEFAULT_COLUMN_VISIBILITY.get(col_name, True))
            cb.setChecked(visible)

        self._efu_list.clear()
        for path in s.efu_files:
            self._efu_list.addItem(path)
        self._content_index_enabled.setChecked(s.content_index_enabled)
        self._content_index_roots.setText(";".join(s.content_index_roots))
        self._content_index_extensions.setText(";".join(s.content_index_extensions))
        self._content_index_max_cache.setValue(s.content_index_max_cache_mb)
        self._content_index_max_file.setValue(s.content_index_max_file_mb)

    def _apply(self) -> bool:
        s = self._settings
        s.index_on_startup = self._index_startup.isChecked()
        s.monitor_usn = self._monitor_usn.isChecked()
        s.usn_poll_interval_ms = self._usn_interval.value()
        s.drive_startup_delay_seconds = self._drive_startup_delay.value()
        s.exclude_hidden = self._exclude_hidden.isChecked()
        s.exclude_system = self._exclude_system.isChecked()
        s.default_match_case = self._default_case.isChecked()
        s.default_regex = self._default_regex.isChecked()
        s.default_max_results = self._max_results.value()
        s.search_delay_ms = self._search_delay.value()
        s.show_preview_pane = self._show_preview.isChecked()
        s.show_filter_bar = self._show_filters.isChecked()
        s.show_status_bar = self._show_status.isChecked()
        s.enable_dialog_quick_switch = self._dialog_quick_switch.isChecked()
        s.start_minimized = self._start_min.isChecked()
        s.minimize_to_tray = self._min_tray.isChecked()
        s.close_to_tray = self._close_tray.isChecked()
        s.remember_window_size = self._remember_size.isChecked()
        s.enable_http_server = self._enable_http.isChecked()
        s.http_port = self._http_port.value()
        s.http_bind = self._http_bind.text()
        s.http_auth_token = self._http_auth_token.text()
        s.http_use_https = self._http_use_https.isChecked()
        s.https_cert_file = self._https_cert_file.text()
        s.https_key_file = self._https_key_file.text()

        # Column visibility
        for col_name, cb in self._col_checks.items():
            s.column_visibility[col_name] = cb.isChecked()

        # Drives
        drives = []
        for i in range(self._drives_list.count()):
            item = self._drives_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                letter = item.data(Qt.ItemDataRole.UserRole)
                if letter:
                    drives.append(letter)
        s.index_drives = drives

        # EFU files
        s.efu_files = []
        for i in range(self._efu_list.count()):
            s.efu_files.append(self._efu_list.item(i).text())
        s.content_index_enabled = self._content_index_enabled.isChecked()
        s.content_index_roots = [
            root.strip() for root in self._content_index_roots.text().split(";")
            if root.strip()
        ]
        s.content_index_extensions = [
            ext.strip().lower().lstrip(".")
            for ext in self._content_index_extensions.text().split(";")
            if ext.strip()
        ]
        s.content_index_max_cache_mb = self._content_index_max_cache.value()
        s.content_index_max_file_mb = self._content_index_max_file.value()

        warnings = s.sanitize()
        if warnings:
            self._load_values()
            QMessageBox.warning(
                self,
                "Settings Adjusted",
                "Some settings were invalid and have been reset:\n\n" + "\n".join(warnings),
            )
            return False

        self.settings_changed.emit(s)
        return True

    def _apply_and_accept(self):
        if self._apply():
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

    def _browse_file(self, target: QLineEdit, title: str):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "",
            "PEM Files (*.pem *.crt *.cer *.key);;All Files (*)"
        )
        if path:
            target.setText(path)

    def _export_settings(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Settings", "quickfind_settings.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if path:
            try:
                if not self._apply():
                    return
                self._settings.export_to_file(path)
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

    def _import_settings(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Settings", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if path:
            try:
                imported = Settings.import_from_file(path)
                self._settings = imported
                self._load_values()
            except Exception as e:
                QMessageBox.critical(self, "Import Failed", str(e))

    def get_settings(self) -> Settings:
        return self._settings
