"""
Bookmarks manager - save/restore search + filter + sort + view state.
"""

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QDialog, QLineEdit, QFormLayout, QLabel,
    QDialogButtonBox, QMenu, QInputDialog, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon

from gui.theme import MOCHA, ACCENT

logger = logging.getLogger('QuickFind.Bookmarks')

CONFIG_DIR = Path.home() / '.quickfind'
BOOKMARKS_FILE = CONFIG_DIR / 'bookmarks.json'


@dataclass
class Bookmark:
    """A saved search state."""
    name: str
    query: str
    filter_name: str = "Everything"
    sort_column: int = 0
    sort_ascending: bool = True
    match_case: bool = False
    use_regex: bool = False
    folder: str = ""
    created: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> 'Bookmark':
        return Bookmark(
            name=d.get('name', ''),
            query=d.get('query', ''),
            filter_name=d.get('filter_name', 'Everything'),
            sort_column=d.get('sort_column', 0),
            sort_ascending=d.get('sort_ascending', True),
            match_case=d.get('match_case', False),
            use_regex=d.get('use_regex', False),
            folder=d.get('folder', ''),
            created=d.get('created', ''),
        )


class BookmarkManager:
    """Manages bookmark persistence and organization."""

    def __init__(self):
        self._bookmarks: list[Bookmark] = []
        self._load()

    def _load(self):
        """Load bookmarks from disk."""
        if not BOOKMARKS_FILE.exists():
            return
        try:
            with open(BOOKMARKS_FILE, 'r') as f:
                data = json.load(f)
            self._bookmarks = [Bookmark.from_dict(d) for d in data]
        except Exception as e:
            logger.error(f"Failed to load bookmarks: {e}")

    def _save(self):
        """Save bookmarks to disk."""
        CONFIG_DIR.mkdir(exist_ok=True)
        try:
            data = [b.to_dict() for b in self._bookmarks]
            with open(BOOKMARKS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save bookmarks: {e}")

    @property
    def bookmarks(self) -> list[Bookmark]:
        return self._bookmarks

    def add(self, bookmark: Bookmark):
        if not bookmark.created:
            bookmark.created = datetime.now().isoformat()
        self._bookmarks.append(bookmark)
        self._save()

    def remove(self, index: int):
        if 0 <= index < len(self._bookmarks):
            self._bookmarks.pop(index)
            self._save()

    def update(self, index: int, bookmark: Bookmark):
        if 0 <= index < len(self._bookmarks):
            self._bookmarks[index] = bookmark
            self._save()

    def get_folders(self) -> list[str]:
        folders = set()
        for b in self._bookmarks:
            if b.folder:
                folders.add(b.folder)
        return sorted(folders)

    def get_by_folder(self, folder: str) -> list[Bookmark]:
        return [b for b in self._bookmarks if b.folder == folder]


class BookmarkDialog(QDialog):
    """Dialog to add/edit a bookmark."""

    def __init__(self, bookmark: Optional[Bookmark] = None,
                 folders: Optional[list[str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Bookmark" if not bookmark else "Edit Bookmark")
        self.setMinimumWidth(400)

        self._bookmark = bookmark or Bookmark(name="", query="")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(self._bookmark.name)
        form.addRow("Name:", self._name_edit)

        self._query_edit = QLineEdit(self._bookmark.query)
        form.addRow("Search:", self._query_edit)

        self._folder_edit = QLineEdit(self._bookmark.folder)
        self._folder_edit.setPlaceholderText("Optional folder name")
        form.addRow("Folder:", self._folder_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_bookmark(self) -> Bookmark:
        self._bookmark.name = self._name_edit.text() or "Untitled"
        self._bookmark.query = self._query_edit.text()
        self._bookmark.folder = self._folder_edit.text()
        return self._bookmark


class BookmarksPanel(QWidget):
    """Panel showing saved bookmarks organized by folder."""

    bookmark_activated = pyqtSignal(object)  # Bookmark

    def __init__(self, manager: BookmarkManager, parent=None):
        super().__init__(parent)
        self._manager = manager
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("Bookmarks")
        header.setStyleSheet(f"""
            QLabel {{
                background-color: {MOCHA['mantle']};
                color: {MOCHA['subtext0']};
                padding: 6px 12px;
                font-weight: 600;
                font-size: 12px;
                border-bottom: 1px solid {MOCHA['surface0']};
            }}
        """)
        layout.addWidget(header)

        # Tree view
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setRootIsDecorated(True)
        self._tree.itemDoubleClicked.connect(self._on_item_activated)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree)

    def _refresh(self):
        """Refresh the bookmarks tree."""
        self._tree.clear()

        # Group by folder
        folders = self._manager.get_folders()
        no_folder = [b for b in self._manager.bookmarks if not b.folder]

        # Add unfiled bookmarks at top
        for bm in no_folder:
            item = QTreeWidgetItem([bm.name])
            item.setData(0, Qt.ItemDataRole.UserRole, bm)
            item.setToolTip(0, f"Search: {bm.query}")
            self._tree.addTopLevelItem(item)

        # Add folders
        for folder in folders:
            folder_item = QTreeWidgetItem([folder])
            folder_item.setFlags(folder_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._tree.addTopLevelItem(folder_item)

            for bm in self._manager.get_by_folder(folder):
                child = QTreeWidgetItem([bm.name])
                child.setData(0, Qt.ItemDataRole.UserRole, bm)
                child.setToolTip(0, f"Search: {bm.query}")
                folder_item.addChild(child)

            folder_item.setExpanded(True)

    def _on_item_activated(self, item: QTreeWidgetItem, column: int):
        bm = item.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(bm, Bookmark):
            self.bookmark_activated.emit(bm)

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return

        bm = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(bm, Bookmark):
            return

        menu = QMenu(self)
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Delete")

        action = menu.exec(self._tree.mapToGlobal(pos))
        if action == edit_action:
            self._edit_bookmark(bm)
        elif action == delete_action:
            self._delete_bookmark(bm)

    def _edit_bookmark(self, bm: Bookmark):
        idx = self._manager.bookmarks.index(bm) if bm in self._manager.bookmarks else -1
        if idx < 0:
            return
        dialog = BookmarkDialog(bm, self._manager.get_folders(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_bookmark()
            self._manager.update(idx, updated)
            self._refresh()

    def _delete_bookmark(self, bm: Bookmark):
        idx = self._manager.bookmarks.index(bm) if bm in self._manager.bookmarks else -1
        if idx >= 0:
            self._manager.remove(idx)
            self._refresh()

    def add_current_search(self, query: str, filter_name: str = "Everything",
                           match_case: bool = False, use_regex: bool = False):
        """Add current search as a bookmark."""
        bm = Bookmark(
            name=query[:50] if query else "Untitled",
            query=query,
            filter_name=filter_name,
            match_case=match_case,
            use_regex=use_regex,
        )
        dialog = BookmarkDialog(bm, self._manager.get_folders(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._manager.add(dialog.get_bookmark())
            self._refresh()

    def build_menu(self, menu: QMenu):
        """Build a bookmarks menu."""
        for bm in self._manager.bookmarks:
            action = menu.addAction(bm.name)
            action.setToolTip(bm.query)
            action.triggered.connect(lambda checked, b=bm: self.bookmark_activated.emit(b))
