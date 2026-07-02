"""
Settings dialog for QuickFind configuration.
"""

import json
import logging
import shutil
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QCheckBox, QSpinBox, QComboBox, QLineEdit,
    QGroupBox, QPushButton, QDialogButtonBox, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt, pyqtSignal

from core.ntfs import (
    FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_COMPRESSED,
    FILE_ATTRIBUTE_DEVICE,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_EA,
    FILE_ATTRIBUTE_ENCRYPTED,
    FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_NORMAL,
    FILE_ATTRIBUTE_NOT_CONTENT_INDEXED,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_READONLY,
    FILE_ATTRIBUTE_REPARSE_POINT,
    FILE_ATTRIBUTE_SPARSE_FILE,
    FILE_ATTRIBUTE_SYSTEM,
    FILE_ATTRIBUTE_TEMPORARY,
)
from core.network_shares import (
    delete_network_credential,
    normalize_network_root,
    save_network_credential,
)
from core.localization import available_languages, tr
from gui.accessibility import describe_widget
from gui.theme import MOCHA, available_themes
from gui.settings_validation import (
    SETTINGS_SCHEMA_VERSION,
    migrate_settings_data,
    sanitize_settings_data,
)

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

INDEX_CASE_MODE_CHOICES = [
    ("Smart", "smart"),
    ("Case-insensitive", "insensitive"),
    ("Case-sensitive", "sensitive"),
]

ATTRIBUTE_CODE_TO_MASK = {
    "R": FILE_ATTRIBUTE_READONLY,
    "H": FILE_ATTRIBUTE_HIDDEN,
    "S": FILE_ATTRIBUTE_SYSTEM,
    "D": FILE_ATTRIBUTE_DIRECTORY,
    "A": FILE_ATTRIBUTE_ARCHIVE,
    "DEV": FILE_ATTRIBUTE_DEVICE,
    "N": FILE_ATTRIBUTE_NORMAL,
    "T": FILE_ATTRIBUTE_TEMPORARY,
    "P": FILE_ATTRIBUTE_SPARSE_FILE,
    "L": FILE_ATTRIBUTE_REPARSE_POINT,
    "C": FILE_ATTRIBUTE_COMPRESSED,
    "O": FILE_ATTRIBUTE_OFFLINE,
    "I": FILE_ATTRIBUTE_NOT_CONTENT_INDEXED,
    "E": FILE_ATTRIBUTE_ENCRYPTED,
    "EA": FILE_ATTRIBUTE_EA,
}


def split_rule_text(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\n", ";").split(";") if part.strip()]


def attribute_mask_to_text(mask: int) -> str:
    remaining = int(mask or 0)
    parts: list[str] = []
    for code, value in ATTRIBUTE_CODE_TO_MASK.items():
        if remaining & value:
            parts.append(code)
            remaining &= ~value
    if remaining:
        parts.append(hex(remaining))
    return ";".join(parts)


def attribute_text_to_mask(text: str) -> int:
    mask = 0
    for raw_token in text.replace(",", ";").split(";"):
        token = raw_token.strip()
        if not token:
            continue
        code = token.upper()
        if code in ATTRIBUTE_CODE_TO_MASK:
            mask |= ATTRIBUTE_CODE_TO_MASK[code]
            continue
        try:
            mask |= int(token, 0)
        except ValueError as exc:
            raise ValueError(f"Unknown file attribute code: {token}") from exc
    return mask


@dataclass
class Settings:
    """Application settings."""
    schema_version: int = SETTINGS_SCHEMA_VERSION

    # Indexing
    index_on_startup: bool = True
    index_drives: list[str] = field(default_factory=list)  # Empty = all supported drives
    monitor_usn: bool = True
    usn_poll_interval_ms: int = 1000
    drive_startup_delay_seconds: int = 0
    exclude_hidden: bool = False
    exclude_system: bool = False
    exclude_globs: list[str] = field(default_factory=list)
    exclude_regexes: list[str] = field(default_factory=list)
    exclude_attribute_mask: int = 0
    follow_reparse_points: bool = False
    index_case_mode: str = "smart"

    # Search
    default_match_case: bool = False
    default_regex: bool = False
    default_max_results: int = 0  # 0 = unlimited
    search_delay_ms: int = 0

    # UI
    show_preview_pane: bool = False
    show_filter_bar: bool = True
    show_status_bar: bool = True
    theme_name: str = "mocha"
    language: str = "en"
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
    network_share_roots: list[str] = field(default_factory=list)

    # EFU file lists
    efu_files: list[str] = field(default_factory=list)
    efu_refresh_interval_minutes: int = 0

    # Content indexing
    content_index_enabled: bool = False
    content_index_roots: list[str] = field(default_factory=list)
    content_index_extensions: list[str] = field(default_factory=list)
    content_index_max_cache_mb: int = 512
    content_index_max_file_mb: int = 10

    def sanitize(self) -> list[str]:
        data, warnings = migrate_settings_data(asdict(self), asdict(Settings()))
        for k, v in data.items():
            if hasattr(self, k):
                setattr(self, k, v)
        return warnings

    def save(self):
        try:
            for warning in self.sanitize():
                logger.warning(warning)
            _write_settings_file(self, SETTINGS_FILE, backup_existing=True)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    @staticmethod
    def load() -> 'Settings':
        if not SETTINGS_FILE.exists():
            return Settings()
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            s, warnings = Settings.from_mapping(data)
            original_version = data.get("schema_version", 0)
            should_rewrite = original_version != SETTINGS_SCHEMA_VERSION
            if should_rewrite:
                _write_settings_file(s, SETTINGS_FILE, backup_existing=True)
            for warning in warnings:
                logger.warning(warning)
            return s
        except Exception as e:
            logger.error(f"Failed to load settings: {e}")
            return Settings()

    @staticmethod
    def from_mapping(data: dict) -> tuple['Settings', list[str]]:
        migrated, warnings = migrate_settings_data(data, asdict(Settings()))
        s = Settings()
        for k, v in migrated.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s, warnings

    def export_to_file(self, path: str):
        """Export settings to a JSON file."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2, ensure_ascii=False)

    @staticmethod
    def import_from_file(path: str) -> 'Settings':
        """Import settings from a JSON file."""
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        s, warnings = Settings.from_mapping(data)
        for warning in warnings:
            logger.warning(warning)
        return s

    @staticmethod
    def import_with_rollback(path: str, current: 'Settings') -> tuple['Settings', list[str]]:
        previous = Settings(**asdict(current))
        try:
            return Settings.import_from_file(path), []
        except Exception as exc:
            logger.error(f"Settings import failed; keeping previous profile: {exc}")
            return previous, [str(exc)]


def _settings_backup_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return path.with_name(f"{path.name}.{stamp}.bak")


def _write_settings_file(settings: Settings, path: Path, backup_existing: bool = True) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if backup_existing and path.exists():
        backup = _settings_backup_path(path)
        counter = 1
        while backup.exists():
            backup = path.with_name(f"{path.name}.{datetime.now().strftime('%Y%m%d%H%M%S')}.{counter}.bak")
            counter += 1
        shutil.copy2(path, backup)

    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(asdict(settings), f, indent=2, ensure_ascii=False)
    tmp.replace(path)
    return backup


class SettingsDialog(QDialog):
    """Settings dialog with tabbed pages."""

    settings_changed = pyqtSignal(object)  # Settings

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings.title", "QuickFind - Settings"))
        self.setMinimumSize(600, 500)
        self._settings = Settings(**asdict(settings))  # Work on a copy

        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self._tabs_widget = QTabWidget()
        tabs = self._tabs_widget
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

        self._exclude_globs = QLineEdit()
        self._exclude_globs.setPlaceholderText("Example: *.tmp;node_modules;*\\build\\*")
        idx_form.addRow("Exclude globs:", self._exclude_globs)

        self._exclude_regexes = QLineEdit()
        self._exclude_regexes.setPlaceholderText("Semicolon-separated regex patterns")
        idx_form.addRow("Exclude regexes:", self._exclude_regexes)

        self._exclude_attributes = QLineEdit()
        self._exclude_attributes.setPlaceholderText("Example: H;S;L or 0x400")
        idx_form.addRow("Exclude attributes:", self._exclude_attributes)

        self._follow_reparse = QCheckBox("Follow symbolic links and junctions")
        idx_form.addRow(self._follow_reparse)

        self._index_case_mode = QComboBox()
        for label, value in INDEX_CASE_MODE_CHOICES:
            self._index_case_mode.addItem(label, value)
        idx_form.addRow("Index case mode:", self._index_case_mode)

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
        tabs.addTab(general, tr("settings.general", "General"))

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

        self._theme_combo = QComboBox()
        for value, label in available_themes():
            self._theme_combo.addItem(label, value)
        ui_form.addRow("Theme:", self._theme_combo)

        self._language_combo = QComboBox()
        for value, label in available_languages():
            self._language_combo.addItem(label, value)
        ui_form.addRow(tr("settings.language", "Language:"), self._language_combo)

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

        share_group = QGroupBox("Network Shares")
        share_layout = QVBoxLayout(share_group)
        share_form = QFormLayout()
        self._network_root = QLineEdit()
        self._network_root.setPlaceholderText("\\\\server\\share or \\\\server\\share\\folder")
        share_form.addRow("UNC root:", self._network_root)
        self._network_username = QLineEdit()
        share_form.addRow("Username:", self._network_username)
        self._network_password = QLineEdit()
        self._network_password.setEchoMode(QLineEdit.EchoMode.Password)
        share_form.addRow("Password:", self._network_password)
        share_layout.addLayout(share_form)

        self._network_list = QListWidget()
        share_layout.addWidget(self._network_list)

        share_buttons = QHBoxLayout()
        self._add_share_btn = QPushButton("Add/Update Share")
        self._add_share_btn.clicked.connect(self._add_network_share)
        self._remove_share_btn = QPushButton("Remove Share")
        self._remove_share_btn.clicked.connect(self._remove_network_share)
        share_buttons.addWidget(self._add_share_btn)
        share_buttons.addWidget(self._remove_share_btn)
        share_buttons.addStretch()
        share_layout.addLayout(share_buttons)
        drives_layout.addWidget(share_group)

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

        efu_form = QFormLayout()
        self._efu_refresh_interval = QSpinBox()
        self._efu_refresh_interval.setRange(0, 1440)
        self._efu_refresh_interval.setSpecialValueText("Disabled")
        self._efu_refresh_interval.setSuffix(" min")
        efu_form.addRow("Refresh interval:", self._efu_refresh_interval)
        efu_layout.addLayout(efu_form)

        self._efu_list = QListWidget()
        efu_layout.addWidget(self._efu_list)

        efu_buttons = QHBoxLayout()
        self._add_efu_btn = QPushButton("Add EFU File")
        self._add_efu_btn.clicked.connect(self._add_efu)
        self._remove_efu_btn = QPushButton("Remove")
        self._remove_efu_btn.clicked.connect(self._remove_efu)
        efu_buttons.addWidget(self._add_efu_btn)
        efu_buttons.addWidget(self._remove_efu_btn)
        efu_buttons.addStretch()
        efu_layout.addLayout(efu_buttons)

        tabs.addTab(efu_tab, "File Lists")

        # -- Content Tab -----------------------------------
        content_tab = QWidget()
        content_layout = QVBoxLayout(content_tab)

        content_group = QGroupBox("Content Indexing")
        content_form = QFormLayout(content_group)

        self._content_index_enabled = QCheckBox(
            tr("settings.content.enable", "Enable background content indexing after file indexing"))
        content_form.addRow(self._content_index_enabled)

        self._content_index_roots = QLineEdit()
        self._content_index_roots.setPlaceholderText("Blank = all indexed paths; separate roots with semicolons")
        content_form.addRow(tr("settings.content.roots", "Roots:"), self._content_index_roots)

        self._content_index_extensions = QLineEdit()
        self._content_index_extensions.setPlaceholderText("Blank = all supported; example: txt;pdf;docx;pptx")
        content_form.addRow(tr("settings.content.extensions", "Extensions:"), self._content_index_extensions)

        self._content_index_max_cache = QSpinBox()
        self._content_index_max_cache.setRange(1, 102400)
        self._content_index_max_cache.setSuffix(" MB")
        content_form.addRow(tr("settings.content.cache_quota", "Cache quota:"), self._content_index_max_cache)

        self._content_index_max_file = QSpinBox()
        self._content_index_max_file.setRange(1, 1024)
        self._content_index_max_file.setSuffix(" MB")
        content_form.addRow(tr("settings.content.max_file_size", "Max file size:"), self._content_index_max_file)

        content_layout.addWidget(content_group)

        cache_group = QGroupBox(tr("settings.content.cache_group", "Content Cache"))
        cache_layout = QVBoxLayout(cache_group)
        self._content_cache_status = QLabel("")
        self._content_cache_status.setWordWrap(True)
        self._content_cache_status.setStyleSheet(f"color: {MOCHA['subtext0']}; font-size: 11px;")
        cache_layout.addWidget(self._content_cache_status)
        cache_buttons = QHBoxLayout()
        self._purge_cache_btn = QPushButton(tr("settings.content.purge_all", "Purge All Content Cache"))
        self._purge_cache_btn.clicked.connect(self._purge_all_content_cache)
        cache_buttons.addWidget(self._purge_cache_btn)
        self._purge_root_btn = QPushButton(tr("settings.content.purge_root", "Purge Root..."))
        self._purge_root_btn.clicked.connect(self._purge_content_cache_root)
        cache_buttons.addWidget(self._purge_root_btn)
        cache_buttons.addStretch()
        cache_layout.addLayout(cache_buttons)
        content_layout.addWidget(cache_group)
        self._refresh_content_cache_status()

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
        tabs.addTab(content_tab, tr("settings.content", "Content"))

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
        self._https_cert_btn = QPushButton("Browse...")
        self._https_cert_btn.clicked.connect(lambda: self._browse_file(self._https_cert_file, "Select TLS Certificate"))
        cert_row.addWidget(self._https_cert_file)
        cert_row.addWidget(self._https_cert_btn)
        http_form.addRow("TLS certificate:", cert_row)

        key_row = QHBoxLayout()
        self._https_key_file = QLineEdit()
        self._https_key_btn = QPushButton("Browse...")
        self._https_key_btn.clicked.connect(lambda: self._browse_file(self._https_key_file, "Select TLS Private Key"))
        key_row.addWidget(self._https_key_file)
        key_row.addWidget(self._https_key_btn)
        http_form.addRow("TLS private key:", key_row)

        http_layout.addWidget(http_group)
        http_layout.addStretch()
        tabs.addTab(http_tab, tr("settings.http_server", "HTTP Server"))

        # -- Export/Import + Dialog buttons ----------------
        bottom_layout = QHBoxLayout()

        self._export_settings_btn = QPushButton("Export Settings...")
        self._export_settings_btn.clicked.connect(self._export_settings)
        self._import_settings_btn = QPushButton("Import Settings...")
        self._import_settings_btn.clicked.connect(self._import_settings)
        bottom_layout.addWidget(self._export_settings_btn)
        bottom_layout.addWidget(self._import_settings_btn)
        bottom_layout.addStretch()

        self._dialog_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel |
            QDialogButtonBox.StandardButton.Apply
        )
        self._dialog_buttons.accepted.connect(self._apply_and_accept)
        self._dialog_buttons.rejected.connect(self.reject)
        self._dialog_buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self._apply)
        bottom_layout.addWidget(self._dialog_buttons)

        layout.addLayout(bottom_layout)
        self._setup_accessibility()

    def _setup_accessibility(self):
        controls = [
            (self._tabs_widget, "Settings sections", "Switch between QuickFind settings pages."),
            (self._index_startup, "Index on startup", "Start indexing when QuickFind launches."),
            (self._monitor_usn, "Monitor USN journal", "Monitor NTFS changes for real-time updates."),
            (self._usn_interval, "USN poll interval", "Milliseconds between USN journal checks."),
            (self._exclude_hidden, "Exclude hidden files", "Skip hidden files during indexing."),
            (self._exclude_system, "Exclude system files", "Skip system files during indexing."),
            (self._exclude_globs, "Exclude glob patterns", "Semicolon-separated glob rules to skip."),
            (self._exclude_regexes, "Exclude regex patterns", "Semicolon-separated regular expressions to skip."),
            (self._exclude_attributes, "Exclude attributes", "File attribute codes or masks to skip."),
            (self._follow_reparse, "Follow symbolic links and junctions", "Follow reparse points in directory-walk indexes."),
            (self._index_case_mode, "Index case mode", "Choose smart, insensitive, or sensitive baseline matching."),
            (self._default_case, "Default match case", "Enable case-sensitive search by default."),
            (self._default_regex, "Default regex", "Enable regex search by default."),
            (self._max_results, "Default maximum results", "Limit results, or use unlimited."),
            (self._search_delay, "Search delay", "Milliseconds to debounce typing before search runs."),
            (self._show_preview, "Show preview pane", "Show the preview pane by default."),
            (self._show_filters, "Show filter dropdown", "Show the file-type filter dropdown."),
            (self._show_status, "Show status bar", "Show the application status bar."),
            (self._theme_combo, "Theme", "Choose the active theme pack."),
            (self._language_combo, "Language", "Choose the user interface language."),
            (self._dialog_quick_switch, "Open Save dialog Quick Switch", "Allow selected folders to target the active file dialog."),
            (self._start_min, "Start minimized", "Start QuickFind minimized."),
            (self._min_tray, "Minimize to system tray", "Send QuickFind to the tray when minimized."),
            (self._close_tray, "Close to system tray", "Keep QuickFind running in the tray when closed."),
            (self._remember_size, "Remember window size", "Persist the window size between launches."),
            (self._drive_startup_delay, "Startup drive delay", "Wait for late-mounted drives before indexing."),
            (self._drives_list, "Drives to index", "Checked drives are included in indexing."),
            (self._network_root, "Network share root", "UNC path for an SMB network share."),
            (self._network_username, "Network username", "Optional username for the network share."),
            (self._network_password, "Network password", "Optional password for the network share."),
            (self._network_list, "Network shares", "Configured network share roots."),
            (self._add_share_btn, "Add or update network share", "Save the network share root and optional credential."),
            (self._remove_share_btn, "Remove network share", "Remove the selected network share."),
            (self._efu_refresh_interval, "EFU refresh interval", "Minutes between external file-list refreshes."),
            (self._efu_list, "EFU file lists", "Configured Everything file-list imports."),
            (self._add_efu_btn, "Add EFU file", "Choose an Everything file-list import."),
            (self._remove_efu_btn, "Remove EFU file", "Remove the selected file-list import."),
            (self._content_index_enabled, "Enable content indexing", "Run background text extraction after file indexing."),
            (self._content_index_roots, "Content index roots", "Optional roots for content indexing."),
            (self._content_index_extensions, "Content index extensions", "Optional file extensions for content indexing."),
            (self._content_index_max_cache, "Content cache quota", "Maximum content cache size in megabytes."),
            (self._content_index_max_file, "Content max file size", "Maximum file size for content extraction."),
            (self._content_adapter_status, "Content adapter status", "Availability of optional content extraction adapters."),
            (self._enable_http, "Enable HTTP server", "Enable read-only remote browser search."),
            (self._http_port, "HTTP port", "Port for the remote search server."),
            (self._http_bind, "HTTP bind address", "Network interface for the remote search server."),
            (self._http_auth_token, "HTTP authentication token", "Bearer, Basic, and browser session token."),
            (self._http_use_https, "Enable HTTPS", "Use the configured TLS certificate and private key."),
            (self._https_cert_file, "TLS certificate file", "Path to the HTTPS certificate file."),
            (self._https_cert_btn, "Browse TLS certificate", "Choose the HTTPS certificate file."),
            (self._https_key_file, "TLS private key file", "Path to the HTTPS private key file."),
            (self._https_key_btn, "Browse TLS private key", "Choose the HTTPS private key file."),
            (self._export_settings_btn, "Export settings", "Export settings to a JSON file."),
            (self._import_settings_btn, "Import settings", "Import settings from a JSON file."),
            (self._dialog_buttons, "Settings actions", "Apply, cancel, or save settings."),
        ]
        for widget, name, description in controls:
            describe_widget(widget, name, description)

        for col_name, cb in self._col_checks.items():
            describe_widget(
                cb,
                f"{col_name.capitalize()} column visibility",
                f"Show or hide the {col_name} results column.",
            )

    def _load_values(self):
        s = self._settings
        self._index_startup.setChecked(s.index_on_startup)
        self._monitor_usn.setChecked(s.monitor_usn)
        self._usn_interval.setValue(s.usn_poll_interval_ms)
        self._drive_startup_delay.setValue(s.drive_startup_delay_seconds)
        self._exclude_hidden.setChecked(s.exclude_hidden)
        self._exclude_system.setChecked(s.exclude_system)
        self._exclude_globs.setText(";".join(s.exclude_globs))
        self._exclude_regexes.setText(";".join(s.exclude_regexes))
        self._exclude_attributes.setText(attribute_mask_to_text(s.exclude_attribute_mask))
        self._follow_reparse.setChecked(s.follow_reparse_points)
        mode_index = self._index_case_mode.findData(s.index_case_mode)
        self._index_case_mode.setCurrentIndex(max(0, mode_index))
        self._default_case.setChecked(s.default_match_case)
        self._default_regex.setChecked(s.default_regex)
        self._max_results.setValue(s.default_max_results)
        self._search_delay.setValue(s.search_delay_ms)
        self._show_preview.setChecked(s.show_preview_pane)
        self._show_filters.setChecked(s.show_filter_bar)
        self._show_status.setChecked(s.show_status_bar)
        theme_index = self._theme_combo.findData(s.theme_name)
        self._theme_combo.setCurrentIndex(max(0, theme_index))
        language_index = self._language_combo.findData(s.language)
        self._language_combo.setCurrentIndex(max(0, language_index))
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
        self._efu_refresh_interval.setValue(s.efu_refresh_interval_minutes)
        self._network_list.clear()
        for root in s.network_share_roots:
            item = QListWidgetItem(root)
            item.setData(Qt.ItemDataRole.UserRole, root)
            self._network_list.addItem(item)

        # Restore the drive selection (empty index_drives is the "all drives"
        # sentinel); without this, reopening Settings re-checks every drive and
        # any OK silently overwrites the user's choice.
        selected_drives = set(s.index_drives)
        for i in range(self._drives_list.count()):
            item = self._drives_list.item(i)
            letter = item.data(Qt.ItemDataRole.UserRole)
            checked = (not selected_drives) or (letter in selected_drives)
            item.setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
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
        s.exclude_globs = split_rule_text(self._exclude_globs.text())
        s.exclude_regexes = split_rule_text(self._exclude_regexes.text())
        try:
            s.exclude_attribute_mask = attribute_text_to_mask(self._exclude_attributes.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Attribute Filter", str(exc))
            return False
        s.follow_reparse_points = self._follow_reparse.isChecked()
        s.index_case_mode = self._index_case_mode.currentData() or "smart"
        s.default_match_case = self._default_case.isChecked()
        s.default_regex = self._default_regex.isChecked()
        s.default_max_results = self._max_results.value()
        s.search_delay_ms = self._search_delay.value()
        s.show_preview_pane = self._show_preview.isChecked()
        s.show_filter_bar = self._show_filters.isChecked()
        s.show_status_bar = self._show_status.isChecked()
        s.theme_name = self._theme_combo.currentData() or "mocha"
        s.language = self._language_combo.currentData() or "en"
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

        # Network shares — defer credential deletion until commit so a removal
        # that the user then cancels does not permanently destroy the credential.
        previous_roots = set(s.network_share_roots)
        s.network_share_roots = []
        for i in range(self._network_list.count()):
            root = self._network_list.item(i).data(Qt.ItemDataRole.UserRole)
            if root:
                s.network_share_roots.append(root)
        for removed_root in previous_roots - set(s.network_share_roots):
            try:
                delete_network_credential(removed_root)
            except Exception:
                pass

        # EFU files
        s.efu_files = []
        for i in range(self._efu_list.count()):
            s.efu_files.append(self._efu_list.item(i).text())
        s.efu_refresh_interval_minutes = self._efu_refresh_interval.value()
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

        # Emit a distinct snapshot each time: the main window keeps a reference to
        # the emitted object, and if we handed it our own mutable settings the next
        # Apply would mutate it in place, making all change-detection compares equal.
        self.settings_changed.emit(Settings(**asdict(s)))
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

    def _add_network_share(self):
        try:
            root = normalize_network_root(self._network_root.text())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Network Share", str(exc))
            return

        username = self._network_username.text().strip()
        password = self._network_password.text()
        if username or password:
            if not username or not password:
                QMessageBox.warning(
                    self,
                    "Incomplete Network Credential",
                    "Both username and password are required to store SMB credentials.",
                )
                return
            try:
                save_network_credential(root, username, password)
            except Exception as exc:
                QMessageBox.warning(self, "Credential Save Failed", str(exc))
                return

        for i in range(self._network_list.count()):
            item = self._network_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == root:
                item.setText(root)
                self._network_password.clear()
                return

        item = QListWidgetItem(root)
        item.setData(Qt.ItemDataRole.UserRole, root)
        self._network_list.addItem(item)
        self._network_password.clear()

    def _remove_network_share(self):
        row = self._network_list.currentRow()
        if row < 0:
            return
        # Only remove from the list; the stored credential is deleted on commit
        # (Apply/OK) so cancelling leaves it intact.
        self._network_list.takeItem(row)

    def _refresh_content_cache_status(self):
        try:
            from core.cache import get_content_cache_stats, get_content_cache_path
            stats = get_content_cache_stats()
            count = stats.get("count", 0)
            text_bytes = stats.get("text_bytes", 0)
            size_mb = text_bytes / (1024 * 1024) if text_bytes else 0
            db_path = get_content_cache_path()
            self._content_cache_status.setText(
                f"Cache: {count:,} entries, {size_mb:.1f} MB text\n"
                f"Location: {db_path}"
            )
        except Exception:
            self._content_cache_status.setText("Content cache status unavailable.")

    def _purge_all_content_cache(self):
        try:
            from core.cache import purge_content_cache, get_content_cache_stats, get_content_cache_path
            deleted = purge_content_cache()
            stats = get_content_cache_stats()
            count = stats.get("count", 0)
            text_bytes = stats.get("text_bytes", 0)
            size_mb = text_bytes / (1024 * 1024) if text_bytes else 0
            self._content_cache_status.setText(
                f"Purged {deleted:,} entries. Cache: {count:,} entries, {size_mb:.1f} MB text\n"
                f"Location: {get_content_cache_path()}"
            )
        except Exception as e:
            self._content_cache_status.setText(f"Purge failed: {e}")

    def _purge_content_cache_root(self):
        root = QFileDialog.getExistingDirectory(self, "Select Root to Purge")
        if not root:
            return
        try:
            from core.cache import purge_content_cache_by_root, get_content_cache_stats, get_content_cache_path
            deleted = purge_content_cache_by_root(root)
            stats = get_content_cache_stats()
            count = stats.get("count", 0)
            text_bytes = stats.get("text_bytes", 0)
            size_mb = text_bytes / (1024 * 1024) if text_bytes else 0
            self._content_cache_status.setText(
                f"Purged {deleted:,} entries under {root}. Cache: {count:,} entries, {size_mb:.1f} MB text\n"
                f"Location: {get_content_cache_path()}"
            )
        except Exception as e:
            self._content_cache_status.setText(f"Purge failed: {e}")

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
            imported, errors = Settings.import_with_rollback(path, self._settings)
            self._settings = imported
            self._load_values()
            if errors:
                QMessageBox.critical(self, "Import Failed", "\n".join(errors))

    def get_settings(self) -> Settings:
        return self._settings
