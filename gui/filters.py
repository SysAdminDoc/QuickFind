"""
Filter bar and custom filter management.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QToolButton, QButtonGroup, QLabel,
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QCheckBox,
    QPushButton, QListWidget, QListWidgetItem, QDialogButtonBox,
    QSpinBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QIcon, QFont

from core.search import SearchFilter, BUILTIN_FILTERS
from gui.theme import MOCHA, ACCENT

logger = logging.getLogger('QuickFind.Filters')

CONFIG_DIR = Path.home() / '.quickfind'
FILTERS_FILE = CONFIG_DIR / 'filters.json'


class FilterButton(QToolButton):
    """Individual filter button in the filter bar."""

    def __init__(self, filter_obj: SearchFilter, parent=None):
        super().__init__(parent)
        self.filter_obj = filter_obj
        self.setText(filter_obj.name)
        self.setCheckable(True)
        self.setMinimumWidth(60)
        self.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 3px 10px;
                color: {MOCHA['subtext0']};
                font-size: 12px;
                font-weight: 500;
            }}
            QToolButton:hover {{
                background-color: {MOCHA['surface0']};
                color: {MOCHA['text']};
            }}
            QToolButton:checked {{
                background-color: {MOCHA['surface1']};
                color: {ACCENT};
                font-weight: 600;
            }}
        """)


class FilterBar(QWidget):
    """
    Horizontal filter bar with built-in and custom filter buttons.
    Similar to Everything's filter dropdown but always visible.
    """
    filter_changed = pyqtSignal(object)  # SearchFilter or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filters: list[SearchFilter] = []
        self._custom_filters: list[SearchFilter] = []
        self._active_filter: Optional[SearchFilter] = None
        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)

        self._setup_ui()
        self._load_custom_filters()
        self._rebuild_buttons()

    def _setup_ui(self):
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 1, 4, 1)
        self._layout.setSpacing(1)

        # Filter label
        label = QLabel("Filter:")
        label.setObjectName("filterLabel")
        self._layout.addWidget(label)

        # Spacer to push manage button right
        self._layout.addStretch()

        # Manage filters button
        self._manage_btn = QToolButton()
        self._manage_btn.setText("+")
        self._manage_btn.setToolTip("Manage Filters")
        self._manage_btn.setStyleSheet(f"""
            QToolButton {{
                background: transparent;
                border: 1px solid {MOCHA['surface1']};
                border-radius: 4px;
                padding: 2px 8px;
                color: {MOCHA['overlay0']};
                font-size: 14px;
                font-weight: 700;
            }}
            QToolButton:hover {{
                background-color: {MOCHA['surface0']};
                color: {MOCHA['text']};
                border-color: {MOCHA['overlay0']};
            }}
        """)
        self._manage_btn.clicked.connect(self._show_manage_dialog)
        self._layout.addWidget(self._manage_btn)

        self.setFixedHeight(28)
        self.setStyleSheet(f"""
            FilterBar {{
                background-color: {MOCHA['mantle']};
                border-bottom: 1px solid {MOCHA['surface0']};
            }}
        """)

    def _rebuild_buttons(self):
        """Rebuild all filter buttons."""
        # Remove existing buttons (keep label and manage button)
        for btn in self._button_group.buttons():
            self._button_group.removeButton(btn)
            self._layout.removeWidget(btn)
            btn.deleteLater()

        # Clear accumulated filters before re-adding
        self._filters.clear()

        # Add built-in filters
        insert_idx = 1  # After the label
        for name, factory in BUILTIN_FILTERS.items():
            f = factory()
            self._filters.append(f)
            btn = FilterButton(f)
            self._button_group.addButton(btn)
            self._layout.insertWidget(insert_idx, btn)
            insert_idx += 1

            if name == 'Everything':
                btn.setChecked(True)
                self._active_filter = f

            btn.clicked.connect(lambda checked, filt=f: self._on_filter_clicked(filt))

        # Add custom filters
        for f in self._custom_filters:
            btn = FilterButton(f)
            self._button_group.addButton(btn)
            self._layout.insertWidget(insert_idx, btn)
            insert_idx += 1
            btn.clicked.connect(lambda checked, filt=f: self._on_filter_clicked(filt))

    def _on_filter_clicked(self, filter_obj: SearchFilter):
        self._active_filter = filter_obj
        self.filter_changed.emit(filter_obj)

    @property
    def active_filter(self) -> Optional[SearchFilter]:
        return self._active_filter

    def _load_custom_filters(self):
        """Load custom filters from disk."""
        if not FILTERS_FILE.exists():
            return
        try:
            with open(FILTERS_FILE, 'r') as f:
                data = json.load(f)
            for item in data:
                self._custom_filters.append(SearchFilter(
                    name=item.get('name', 'Custom'),
                    extensions=item.get('extensions', []),
                    min_size=item.get('min_size', 0),
                    max_size=item.get('max_size', 0),
                    files_only=item.get('files_only', False),
                    folders_only=item.get('folders_only', False),
                    macro=item.get('macro', ''),
                    exclude_paths=item.get('exclude_paths', []),
                ))
        except Exception as e:
            logger.error(f"Failed to load custom filters: {e}")

    def _save_custom_filters(self):
        """Save custom filters to disk."""
        CONFIG_DIR.mkdir(exist_ok=True)
        try:
            data = []
            for f in self._custom_filters:
                data.append({
                    'name': f.name,
                    'extensions': f.extensions,
                    'min_size': f.min_size,
                    'max_size': f.max_size,
                    'files_only': f.files_only,
                    'folders_only': f.folders_only,
                    'macro': f.macro,
                    'exclude_paths': f.exclude_paths,
                })
            tmp = FILTERS_FILE.with_suffix('.tmp')
            with open(tmp, 'w') as f:
                json.dump(data, f, indent=2)
            tmp.replace(FILTERS_FILE)
        except Exception as e:
            logger.error(f"Failed to save custom filters: {e}")

    def _show_manage_dialog(self):
        """Show dialog to manage custom filters."""
        dialog = ManageFiltersDialog(self._custom_filters, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._custom_filters = dialog.get_filters()
            self._save_custom_filters()
            self._filters.clear()
            self._rebuild_buttons()


class ManageFiltersDialog(QDialog):
    """Dialog for adding/editing/removing custom filters."""

    def __init__(self, filters: list[SearchFilter], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Filters")
        self.setMinimumSize(500, 400)
        self._filters = [SearchFilter(
            name=f.name, extensions=list(f.extensions),
            min_size=f.min_size, max_size=f.max_size,
            files_only=f.files_only, folders_only=f.folders_only,
            macro=f.macro
        ) for f in filters]

        self._setup_ui()
        self._populate_list()

    def _setup_ui(self):
        layout = QHBoxLayout(self)

        # Left: list
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._list)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self._add_filter)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(self._remove_filter)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        left.addLayout(btn_row)
        layout.addLayout(left)

        # Right: editor
        right = QVBoxLayout()
        form = QFormLayout()

        self._name_edit = QLineEdit()
        form.addRow("Name:", self._name_edit)

        self._ext_edit = QLineEdit()
        self._ext_edit.setPlaceholderText("e.g., jpg;png;gif")
        form.addRow("Extensions:", self._ext_edit)

        self._macro_edit = QLineEdit()
        self._macro_edit.setPlaceholderText("Search macro (optional)")
        form.addRow("Macro:", self._macro_edit)

        self._files_only = QCheckBox("Files only")
        form.addRow("", self._files_only)

        self._folders_only = QCheckBox("Folders only")
        form.addRow("", self._folders_only)

        self._min_size = QSpinBox()
        self._min_size.setMaximum(999999999)
        self._min_size.setSuffix(" KB")
        form.addRow("Min size:", self._min_size)

        self._max_size = QSpinBox()
        self._max_size.setMaximum(999999999)
        self._max_size.setSuffix(" KB")
        form.addRow("Max size:", self._max_size)

        right.addLayout(form)

        self._apply_btn = QPushButton("Apply Changes")
        self._apply_btn.clicked.connect(self._apply_changes)
        right.addWidget(self._apply_btn)

        right.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

        layout.addLayout(right)

    def _populate_list(self):
        self._list.clear()
        for f in self._filters:
            self._list.addItem(f.name)

    def _on_row_changed(self, row):
        if 0 <= row < len(self._filters):
            f = self._filters[row]
            self._name_edit.setText(f.name)
            self._ext_edit.setText(';'.join(f.extensions))
            self._macro_edit.setText(f.macro)
            self._files_only.setChecked(f.files_only)
            self._folders_only.setChecked(f.folders_only)
            self._min_size.setValue(f.min_size // 1024 if f.min_size else 0)
            self._max_size.setValue(f.max_size // 1024 if f.max_size else 0)

    def _add_filter(self):
        f = SearchFilter(name="New Filter")
        self._filters.append(f)
        self._list.addItem(f.name)
        self._list.setCurrentRow(len(self._filters) - 1)

    def _remove_filter(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._filters):
            self._filters.pop(row)
            self._populate_list()

    def _apply_changes(self):
        row = self._list.currentRow()
        if 0 <= row < len(self._filters):
            f = self._filters[row]
            f.name = self._name_edit.text() or "Filter"
            f.extensions = [e.strip().lower() for e in self._ext_edit.text().split(';') if e.strip()]
            f.macro = self._macro_edit.text()
            f.files_only = self._files_only.isChecked()
            f.folders_only = self._folders_only.isChecked()
            f.min_size = self._min_size.value() * 1024
            f.max_size = self._max_size.value() * 1024
            self._list.item(row).setText(f.name)

    def get_filters(self) -> list[SearchFilter]:
        return self._filters
