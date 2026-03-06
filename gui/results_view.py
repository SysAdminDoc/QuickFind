"""
Results view with sortable table model and thumbnail grid mode.
Everything-style compact, information-dense display.
"""

import os
import logging
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QTableView, QAbstractItemView, QHeaderView, QWidget,
    QListView, QStackedWidget, QVBoxLayout, QStyledItemDelegate,
    QStyle, QApplication, QFileIconProvider
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel,
    pyqtSignal, QTimer, QVariant, QFileInfo
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QImage, QPainter, QColor, QFont
)

from core.index import FileEntry, FileIndex
from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.ResultsView')

# Column definitions — Everything default order: Name, Path, Size, Date Modified
COLUMNS = [
    ('Name', 'name'),
    ('Path', 'path'),
    ('Size', 'size'),
    ('Date Modified', 'date_modified'),
    ('Date Created', 'date_created'),
    ('Type', 'extension'),
    ('Attributes', 'attributes'),
]

COLUMN_NAME = 0
COLUMN_PATH = 1
COLUMN_SIZE = 2
COLUMN_DATE_MOD = 3
COLUMN_DATE_CREATE = 4
COLUMN_TYPE = 5
COLUMN_ATTRIB = 6


def format_size(size: int) -> str:
    """Format file size for display (Everything-style: KB with comma separator)."""
    if size <= 0:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size // 1024:,} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):,.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):,.2f} GB"


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M")


def format_attributes(attrs: int) -> str:
    """Format file attributes as letter codes."""
    parts = []
    if attrs & 0x01: parts.append('R')
    if attrs & 0x02: parts.append('H')
    if attrs & 0x04: parts.append('S')
    if attrs & 0x10: parts.append('D')
    if attrs & 0x20: parts.append('A')
    if attrs & 0x800: parts.append('C')
    if attrs & 0x4000: parts.append('E')
    return ''.join(parts)


class FileIconCache:
    """Cache for file type icons, using QFileIconProvider with QFileInfo for OS-native icons."""
    _cache: dict[str, QIcon] = {}
    _provider = None

    @classmethod
    def get(cls, entry: FileEntry, index: FileIndex = None) -> QIcon:
        if cls._provider is None:
            cls._provider = QFileIconProvider()
            cls._cache = {}

        if entry.is_dir:
            key = '__dir__'
        else:
            ext = entry.extension
            key = ext if ext else '__file__'

        if key not in cls._cache:
            if key == '__dir__':
                cls._cache[key] = cls._provider.icon(QFileIconProvider.IconType.Folder)
            elif key == '__file__':
                cls._cache[key] = cls._provider.icon(QFileIconProvider.IconType.File)
            else:
                # Use QFileInfo with a dummy path so QFileIconProvider returns
                # the OS-registered icon for this extension
                cls._cache[key] = cls._provider.icon(QFileInfo(f"dummy.{ext}"))

        return cls._cache.get(key, QIcon())


class ResultsTableModel(QAbstractTableModel):
    """Table model backed by a list of FileEntry objects."""

    def __init__(self, index: FileIndex, parent=None):
        super().__init__(parent)
        self._index = index
        self._entries: list[FileEntry] = []

    def set_results(self, entries: list[FileEntry]):
        logger.debug(f"Model set_results: {len(entries)} entries")
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._entries.clear()
        self.endResetModel()

    @property
    def entries(self) -> list[FileEntry]:
        return self._entries

    def entry_at(self, row: int) -> Optional[FileEntry]:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section][0]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if row >= len(self._entries):
            return None

        entry = self._entries[row]

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COLUMN_NAME:
                return entry.name
            elif col == COLUMN_PATH:
                return self._index.resolve_parent_path(entry.drive, entry.parent_frn)
            elif col == COLUMN_SIZE:
                if entry.is_dir:
                    return ""
                entry.ensure_stat(self._index)
                return format_size(entry.size) if entry.size else ""
            elif col == COLUMN_DATE_MOD:
                entry.ensure_stat(self._index)
                return format_datetime(entry.date_modified)
            elif col == COLUMN_DATE_CREATE:
                entry.ensure_stat(self._index)
                return format_datetime(entry.date_created)
            elif col == COLUMN_TYPE:
                if entry.is_dir:
                    return "File folder"
                ext = entry.extension
                return f"{ext.upper()} File" if ext else "File"
            elif col == COLUMN_ATTRIB:
                return format_attributes(entry.attributes)

        elif role == Qt.ItemDataRole.DecorationRole:
            if col == COLUMN_NAME:
                return FileIconCache.get(entry)

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col == COLUMN_SIZE:
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        elif role == Qt.ItemDataRole.UserRole:
            return entry

        elif role == Qt.ItemDataRole.ToolTipRole:
            if col == COLUMN_NAME:
                return entry.get_path(self._index)

        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder
        count = len(self._entries)

        # MFT provides metadata at index time; ensure_stat is a no-op for most entries.
        # Only USN-modified entries (with _stat_loaded reset) need lazy os.stat.
        needs_stat = column in (COLUMN_SIZE, COLUMN_DATE_MOD, COLUMN_DATE_CREATE)
        if needs_stat:
            unfilled = sum(1 for e in self._entries if not e._stat_loaded)
            if unfilled > 0 and unfilled <= 100_000:
                import time as _time
                t0 = _time.perf_counter()
                for entry in self._entries:
                    entry.ensure_stat(self._index)
                elapsed = (_time.perf_counter() - t0) * 1000
                logger.debug(f"Table sort: loaded stats for {unfilled} entries in {elapsed:.0f}ms")

        try:
            if column == COLUMN_NAME:
                self._entries.sort(key=lambda e: e.name.lower(), reverse=reverse)
            elif column == COLUMN_PATH:
                self._entries.sort(
                    key=lambda e: self._index.resolve_parent_path(e.drive, e.parent_frn).lower(),
                    reverse=reverse
                )
            elif column == COLUMN_SIZE:
                self._entries.sort(
                    key=lambda e: e.size if e._stat_loaded else -1,
                    reverse=reverse
                )
            elif column == COLUMN_DATE_MOD:
                _dt_min = datetime.min
                self._entries.sort(
                    key=lambda e: e.date_modified or _dt_min,
                    reverse=reverse
                )
            elif column == COLUMN_DATE_CREATE:
                _dt_min = datetime.min
                self._entries.sort(
                    key=lambda e: e.date_created or _dt_min,
                    reverse=reverse
                )
            elif column == COLUMN_TYPE:
                self._entries.sort(key=lambda e: e.extension, reverse=reverse)
            elif column == COLUMN_ATTRIB:
                self._entries.sort(key=lambda e: e.attributes, reverse=reverse)
        except Exception as exc:
            logger.error(f"Table sort failed: {exc}")

        self.endResetModel()


class ResultsTableView(QTableView):
    """Everything-style compact table view for search results."""

    item_activated = pyqtSignal(object)  # FileEntry
    selection_changed = pyqtSignal(object)  # FileEntry or None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(20)  # Everything-compact rows
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Column sizing
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(40)
        header.setSortIndicatorShown(True)
        header.setHighlightSections(False)

        self.doubleClicked.connect(self._on_double_click)

    def set_model(self, model: ResultsTableModel):
        """Set the model and configure column widths."""
        self.setModel(model)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)

        # Everything default columns: Name, Path, Size, Date Modified visible
        # Hide: Date Created, Type, Attributes
        self.setColumnHidden(COLUMN_DATE_CREATE, True)
        self.setColumnHidden(COLUMN_TYPE, True)
        self.setColumnHidden(COLUMN_ATTRIB, True)

        # Column widths matching Everything defaults
        self.setColumnWidth(COLUMN_NAME, 280)
        self.setColumnWidth(COLUMN_SIZE, 75)
        self.setColumnWidth(COLUMN_DATE_MOD, 130)

        # Path stretches to fill
        header = self.horizontalHeader()
        header.setSectionResizeMode(COLUMN_PATH, QHeaderView.ResizeMode.Stretch)

        # Default sort: Date Modified descending (MFT provides timestamps natively)
        self.sortByColumn(COLUMN_DATE_MOD, Qt.SortOrder.DescendingOrder)

    def _on_double_click(self, index: QModelIndex):
        model = self.model()
        if isinstance(model, ResultsTableModel):
            entry = model.entry_at(index.row())
            if entry:
                self.item_activated.emit(entry)

    def _on_selection_changed(self, selected, deselected):
        indexes = self.selectionModel().selectedRows()
        if indexes:
            model = self.model()
            if isinstance(model, ResultsTableModel):
                entry = model.entry_at(indexes[0].row())
                self.selection_changed.emit(entry)
        else:
            self.selection_changed.emit(None)

    def selected_entries(self) -> list[FileEntry]:
        entries = []
        model = self.model()
        if isinstance(model, ResultsTableModel):
            for idx in self.selectionModel().selectedRows():
                entry = model.entry_at(idx.row())
                if entry:
                    entries.append(entry)
        return entries

    def select_all_results(self):
        self.selectAll()


class ThumbnailDelegate(QStyledItemDelegate):
    """Custom delegate for thumbnail view rendering."""

    THUMB_SIZE = 128
    PADDING = 8
    TEXT_HEIGHT = 36

    def __init__(self, parent=None):
        super().__init__(parent)

    def sizeHint(self, option, index):
        return QSize(
            self.THUMB_SIZE + self.PADDING * 2,
            self.THUMB_SIZE + self.TEXT_HEIGHT + self.PADDING * 2
        )

    def paint(self, painter: QPainter, option, index):
        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(MOCHA['surface1']))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, QColor(MOCHA['surface0']))

        entry = index.data(Qt.ItemDataRole.UserRole)
        if entry and isinstance(entry, FileEntry):
            icon = FileIconCache.get(entry)
            icon_rect = option.rect.adjusted(
                self.PADDING, self.PADDING,
                -self.PADDING, -(self.TEXT_HEIGHT + self.PADDING)
            )
            icon.paint(painter, icon_rect)

            text_rect = option.rect.adjusted(
                4, self.THUMB_SIZE + self.PADDING,
                -4, -2
            )
            painter.setPen(QColor(MOCHA['text']))
            painter.setFont(QFont("Segoe UI", 9))
            metrics = painter.fontMetrics()
            elided = metrics.elidedText(
                entry.name, Qt.TextElideMode.ElideMiddle, text_rect.width()
            )
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, elided)

        painter.restore()


class ThumbnailListView(QListView):
    """Grid view showing file thumbnails."""

    item_activated = pyqtSignal(object)
    selection_changed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setSpacing(4)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setGridSize(QSize(144, 172))

        self.doubleClicked.connect(self._on_double_click)

    def _on_double_click(self, index: QModelIndex):
        model = self.model()
        if isinstance(model, ResultsTableModel):
            entry = model.entry_at(index.row())
            if entry:
                self.item_activated.emit(entry)


class ResultsView(QStackedWidget):
    """Stacked widget that switches between table view and thumbnail view."""

    item_activated = pyqtSignal(object)
    selection_changed = pyqtSignal(object)

    def __init__(self, index: FileIndex, parent=None):
        super().__init__(parent)
        self._file_index = index
        self._model = ResultsTableModel(index)

        # Table view (index 0)
        self.table_view = ResultsTableView()
        self.table_view.set_model(self._model)
        self.table_view.item_activated.connect(self.item_activated)
        self.table_view.selection_changed.connect(self.selection_changed)
        self.addWidget(self.table_view)

        # Thumbnail view (index 1)
        self.thumb_view = ThumbnailListView()
        self.thumb_view.setModel(self._model)
        self.thumb_view.item_activated.connect(self.item_activated)
        self.addWidget(self.thumb_view)

    @property
    def model(self) -> ResultsTableModel:
        return self._model

    def set_results(self, entries: list[FileEntry]):
        self._model.set_results(entries)

    def clear(self):
        self._model.clear()

    def show_table_view(self):
        self.setCurrentIndex(0)

    def show_thumbnail_view(self):
        self.setCurrentIndex(1)

    def selected_entries(self) -> list[FileEntry]:
        if self.currentIndex() == 0:
            return self.table_view.selected_entries()
        return []

    @property
    def result_count(self) -> int:
        return self._model.rowCount()
