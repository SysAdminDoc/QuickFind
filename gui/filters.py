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
from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.Filters')

CONFIG_DIR = Path.home() / '.quickfind'
FILTERS_FILE = CONFIG_DIR / 'filters.json'



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
            macro=f.macro, exclude_paths=list(f.exclude_paths)
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
