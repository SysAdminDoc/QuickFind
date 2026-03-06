"""
Dialog for managing hidden paths per filter category.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QComboBox, QLabel, QDialogButtonBox, QFileDialog,
    QInputDialog
)
from PyQt6.QtCore import Qt

from core.hidden_paths import HiddenPathsManager
from core.search import BUILTIN_FILTERS
from gui.theme import MOCHA


class HiddenPathsDialog(QDialog):
    """Dialog to view, add, edit, and remove hidden paths per filter."""

    def __init__(self, manager: HiddenPathsManager, current_filter: str = "Everything", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Hidden Paths")
        self.setMinimumSize(550, 400)
        self._manager = manager
        self._current_filter = current_filter
        self._setup_ui()
        self._populate()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Filter selector
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Filter category:"))
        self._filter_combo = QComboBox()
        self._filter_combo.setMinimumWidth(160)

        # Add all built-in filter names
        for name in BUILTIN_FILTERS:
            self._filter_combo.addItem(name)

        # Add any filter names that have hidden paths but aren't built-in
        for name in self._manager.filter_names():
            if self._filter_combo.findText(name) == -1:
                self._filter_combo.addItem(name)

        # Select current filter
        idx = self._filter_combo.findText(self._current_filter)
        if idx >= 0:
            self._filter_combo.setCurrentIndex(idx)

        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        top_row.addWidget(self._filter_combo, 1)
        layout.addLayout(top_row)

        # Info label
        self._info_label = QLabel()
        self._info_label.setStyleSheet(f"color: {MOCHA['subtext0']}; font-size: 11px; padding: 2px 0;")
        layout.addWidget(self._info_label)

        # Path list
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self._list, 1)

        # Action buttons
        btn_row = QHBoxLayout()

        add_dir_btn = QPushButton("Add Directory...")
        add_dir_btn.clicked.connect(self._add_directory)
        btn_row.addWidget(add_dir_btn)

        add_path_btn = QPushButton("Add Path Manually...")
        add_path_btn.clicked.connect(self._add_manual)
        btn_row.addWidget(add_path_btn)

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(self._edit_path)
        btn_row.addWidget(edit_btn)

        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(remove_btn)

        layout.addLayout(btn_row)

        # Dialog buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def _populate(self):
        self._list.clear()
        filter_name = self._filter_combo.currentText()
        paths = self._manager.get_paths(filter_name)
        for p in paths:
            self._list.addItem(p)
        count = len(paths)
        self._info_label.setText(
            f"{count} hidden path{'s' if count != 1 else ''} for \"{filter_name}\" filter"
        )

    def _on_filter_changed(self, text: str):
        self._current_filter = text
        self._populate()

    def _add_directory(self):
        path = QFileDialog.getExistingDirectory(self, "Select Directory to Hide")
        if path:
            filter_name = self._filter_combo.currentText()
            self._manager.add_path(filter_name, path)
            self._populate()

    def _add_manual(self):
        text, ok = QInputDialog.getText(
            self, "Add Hidden Path",
            "Enter path or partial path to hide from results:\n"
            "(Files/directories containing this string will be excluded)"
        )
        if ok and text.strip():
            filter_name = self._filter_combo.currentText()
            self._manager.add_path(filter_name, text.strip())
            self._populate()

    def _edit_path(self):
        items = self._list.selectedItems()
        if not items:
            return
        item = items[0]
        old_path = item.text()
        text, ok = QInputDialog.getText(
            self, "Edit Hidden Path", "Path:", text=old_path
        )
        if ok and text.strip() and text.strip() != old_path:
            filter_name = self._filter_combo.currentText()
            self._manager.remove_path(filter_name, old_path)
            self._manager.add_path(filter_name, text.strip())
            self._populate()

    def _remove_selected(self):
        items = self._list.selectedItems()
        if not items:
            return
        filter_name = self._filter_combo.currentText()
        for item in items:
            self._manager.remove_path(filter_name, item.text())
        self._populate()
