"""
Results view with sortable table model, thumbnail grid mode,
result virtualization (fetchMore), drag & drop, column menu,
keyboard navigation, result highlighting, and inline column filters.

v0.6.0: Column right-click menu, keyboard nav, match highlighting delegate,
         inline filter row below headers.
"""

import os
import logging
from collections import OrderedDict
from datetime import datetime
from typing import Optional

from PyQt6.QtWidgets import (
    QTableView, QAbstractItemView, QHeaderView, QWidget,
    QListView, QStackedWidget, QVBoxLayout, QHBoxLayout, QStyledItemDelegate,
    QStyle, QApplication, QFileIconProvider, QMenu, QLineEdit, QLabel
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel,
    pyqtSignal, QTimer, QVariant, QFileInfo, QUrl, QMimeData, QRect
)
from PyQt6.QtGui import (
    QIcon, QPixmap, QImage, QPainter, QColor, QFont, QDrag,
    QFontMetrics, QPen, QKeyEvent, QTextDocument, QAbstractTextDocumentLayout
)

from core.index import FileEntry, FileIndex
from core.ntfs import (
    FILE_ATTRIBUTE_COMPRESSED, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_EA,
    FILE_ATTRIBUTE_ENCRYPTED, FILE_ATTRIBUTE_HIDDEN,
    FILE_ATTRIBUTE_NOT_CONTENT_INDEXED, FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_REPARSE_POINT, FILE_ATTRIBUTE_SPARSE_FILE,
    FILE_ATTRIBUTE_SYSTEM, FILE_ATTRIBUTE_TEMPORARY,
)
from gui.accessibility import describe_widget
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

# Number of rows to load at a time for virtualization
FETCH_BATCH_SIZE = 5000
MAX_FILE_ICON_CACHE_SIZE = 256
MAX_PATH_COLUMNS = 8


def format_size(size: int) -> str:
    """Format file size for display (Everything-style: KB with comma separator)."""
    if size < 0:
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
    if attrs & FILE_ATTRIBUTE_HIDDEN: parts.append('H')
    if attrs & FILE_ATTRIBUTE_SYSTEM: parts.append('S')
    if attrs & FILE_ATTRIBUTE_DIRECTORY: parts.append('D')
    if attrs & 0x20: parts.append('A')
    if attrs & FILE_ATTRIBUTE_TEMPORARY: parts.append('T')
    if attrs & FILE_ATTRIBUTE_SPARSE_FILE: parts.append('P')
    if attrs & FILE_ATTRIBUTE_REPARSE_POINT: parts.append('L')
    if attrs & FILE_ATTRIBUTE_COMPRESSED: parts.append('C')
    if attrs & FILE_ATTRIBUTE_OFFLINE: parts.append('O')
    if attrs & FILE_ATTRIBUTE_NOT_CONTENT_INDEXED: parts.append('I')
    if attrs & FILE_ATTRIBUTE_ENCRYPTED: parts.append('E')
    if attrs & FILE_ATTRIBUTE_EA: parts.append('EA')
    return ''.join(parts)


REPARSE_TAG_NAMES = {
    0xA0000003: "MOUNT_POINT",
    0xA000000C: "SYMLINK",
    0x8000001B: "APP_EXEC_LINK",
    0x9000001A: "CLOUD",
}


def format_reparse_tag(tag: int) -> str:
    if not tag:
        return ""
    name = REPARSE_TAG_NAMES.get(tag)
    if name:
        return f"{name} (0x{tag:08X})"
    return f"0x{tag:08X}"


def entry_metadata_lines(entry: FileEntry) -> list[str]:
    lines = []
    tag = format_reparse_tag(entry.reparse_tag)
    if tag:
        lines.append(f"Reparse tag: {tag}")
    if entry.has_extended_attributes:
        lines.append("Extended attributes: present")
    return lines


def path_segments(path: str) -> list[str]:
    """Split a Windows path into Finder-style root/folder/item segments."""
    normalized = (path or "").replace("/", "\\").rstrip("\\")
    if not normalized:
        return []

    if normalized.startswith("\\\\"):
        parts = [part for part in normalized.split("\\") if part]
        if len(parts) >= 2:
            return [f"\\\\{parts[0]}\\{parts[1]}", *parts[2:]]
        return [normalized]

    drive, rest = os.path.splitdrive(normalized)
    parts = [part for part in rest.strip("\\").split("\\") if part]
    if drive:
        return [drive, *parts]
    return parts or [normalized]


def compact_path_segments(segments: list[str],
                          max_columns: int = MAX_PATH_COLUMNS) -> list[str]:
    if len(segments) <= max_columns:
        return segments
    return segments[:max_columns - 1] + [f"...\\{segments[-1]}"]


class FileIconCache:
    """Cache for file type icons, using QFileIconProvider with QFileInfo for OS-native icons."""
    _cache: OrderedDict[str, QIcon] = OrderedDict()
    _provider = None

    @classmethod
    def get(cls, entry: FileEntry, index: FileIndex = None) -> QIcon:
        if cls._provider is None:
            cls._provider = QFileIconProvider()
            cls._cache = OrderedDict()

        if entry.is_dir:
            key = '__dir__'
        else:
            ext = entry.extension
            key = ext if ext else '__file__'

        if key in cls._cache:
            icon = cls._cache.pop(key)
            cls._cache[key] = icon
            return icon

        if key == '__dir__':
            icon = cls._provider.icon(QFileIconProvider.IconType.Folder)
        elif key == '__file__':
            icon = cls._provider.icon(QFileIconProvider.IconType.File)
        else:
            # Use QFileInfo with a dummy path so QFileIconProvider returns
            # the OS-registered icon for this extension
            icon = cls._provider.icon(QFileInfo(f"dummy.{ext}"))
        cls._cache[key] = icon
        cls._trim_cache()

        return cls._cache.get(key, QIcon())

    @classmethod
    def _trim_cache(cls):
        while len(cls._cache) > MAX_FILE_ICON_CACHE_SIZE:
            cls._cache.popitem(last=False)


# ── Match Highlighting Delegate ──────────────────────────

class HighlightDelegate(QStyledItemDelegate):
    """Custom delegate that highlights search query matches in accent color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._highlight_text = ""
        self._accent_color = QColor(MOCHA['blue'])

    def set_highlight(self, text: str):
        self._highlight_text = text.lower()

    def paint(self, painter: QPainter, option, index):
        # Draw background (selection, alternating rows)
        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else QApplication.style()

        # Let the style draw background and focus rect
        painter.save()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget)

        # Draw icon for column 0
        col = index.column()
        if col == COLUMN_NAME:
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon and not icon.isNull():
                icon_rect = QRect(option.rect.left() + 2, option.rect.top() + 1,
                                  option.rect.height() - 2, option.rect.height() - 2)
                icon.paint(painter, icon_rect)
                text_rect = option.rect.adjusted(option.rect.height() + 2, 0, 0, 0)
            else:
                text_rect = option.rect.adjusted(4, 0, 0, 0)
        else:
            text_rect = option.rect.adjusted(4, 0, -4, 0)

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        # Right-align size column
        alignment = index.data(Qt.ItemDataRole.TextAlignmentRole)
        if alignment:
            text_align = Qt.AlignmentFlag(alignment) | Qt.AlignmentFlag.AlignVCenter
        else:
            text_align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter

        # If there's a highlight match and this is a highlightable column
        if self._highlight_text and col in (COLUMN_NAME, COLUMN_PATH) and text:
            self._draw_highlighted(painter, text_rect, text, text_align, option)
        else:
            text_color = QColor(MOCHA['text']) if option.state & QStyle.StateFlag.State_Selected else QColor(MOCHA['text'])
            painter.setPen(text_color)
            painter.setFont(option.font)
            painter.drawText(text_rect, text_align, text)

        painter.restore()

    def _draw_highlighted(self, painter: QPainter, rect: QRect, text: str,
                          alignment, option):
        """Draw text with highlighted match substrings."""
        lower_text = text.lower()
        hl = self._highlight_text
        font = option.font
        fm = QFontMetrics(font)
        painter.setFont(font)

        x = rect.left()
        y_center = rect.center().y() + fm.ascent() // 2 - 1
        max_x = rect.right()

        pos = 0
        while pos < len(text):
            idx = lower_text.find(hl, pos)
            if idx < 0:
                # Draw remaining text normally
                segment = text[pos:]
                painter.setPen(QColor(MOCHA['text']))
                painter.drawText(x, y_center, segment)
                break

            # Draw text before match
            if idx > pos:
                before = text[pos:idx]
                painter.setPen(QColor(MOCHA['text']))
                painter.drawText(x, y_center, before)
                x += fm.horizontalAdvance(before)

            # Draw match in accent color
            match = text[idx:idx + len(hl)]
            painter.setPen(self._accent_color)
            painter.drawText(x, y_center, match)
            x += fm.horizontalAdvance(match)

            pos = idx + len(hl)

            if x > max_x:
                break


class ResultsTableModel(QAbstractTableModel):
    """Table model with fetchMore virtualization and drag & drop support."""

    def __init__(self, index: FileIndex, parent=None):
        super().__init__(parent)
        self._index = index
        self._all_results: list[FileEntry] = []  # Full result set
        self._entries: list[FileEntry] = []       # Currently loaded (visible) subset
        self._loaded_count = 0

    def set_results(self, entries: list[FileEntry]):
        logger.debug(f"Model set_results: {len(entries)} entries")
        self.beginResetModel()
        self._all_results = entries
        # Load initial batch
        self._loaded_count = min(len(entries), FETCH_BATCH_SIZE)
        self._entries = entries[:self._loaded_count]
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._all_results.clear()
        self._entries.clear()
        self._loaded_count = 0
        self.endResetModel()

    @property
    def entries(self) -> list[FileEntry]:
        return self._all_results

    @property
    def total_count(self) -> int:
        return len(self._all_results)

    def entry_at(self, row: int) -> Optional[FileEntry]:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def rowCount(self, parent=QModelIndex()):
        return len(self._entries)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    # ── Virtualization via fetchMore ──────────────────

    def canFetchMore(self, parent=QModelIndex()) -> bool:
        return self._loaded_count < len(self._all_results)

    def fetchMore(self, parent=QModelIndex()):
        remaining = len(self._all_results) - self._loaded_count
        fetch_count = min(remaining, FETCH_BATCH_SIZE)
        if fetch_count <= 0:
            return

        self.beginInsertRows(
            QModelIndex(),
            self._loaded_count,
            self._loaded_count + fetch_count - 1
        )
        self._entries = self._all_results[:self._loaded_count + fetch_count]
        self._loaded_count += fetch_count
        self.endInsertRows()

    # ── Drag & Drop ──────────────────────────────────

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        default = super().flags(index)
        if index.isValid():
            return default | Qt.ItemFlag.ItemIsDragEnabled
        return default

    def mimeTypes(self) -> list[str]:
        return ['text/uri-list']

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        urls = []
        seen_rows = set()
        for idx in indexes:
            row = idx.row()
            if row in seen_rows:
                continue
            seen_rows.add(row)
            entry = self.entry_at(row)
            if entry:
                path = entry.get_path(self._index)
                urls.append(QUrl.fromLocalFile(path))
        mime.setUrls(urls)
        return mime

    # ── Data display ─────────────────────────────────

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
                if entry._path:
                    # Use cached path's parent directory
                    idx = entry._path.rfind('\\')
                    return entry._path[:idx] if idx > 0 else entry._path
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
                path = entry.get_path(self._index)
                snippet = getattr(entry, "content_snippet", "")
                metadata = entry_metadata_lines(entry)
                if metadata:
                    path = "\n".join([path] + metadata)
                if snippet:
                    return f"{path}\n\nContent match:\n{snippet}"
                return path

        return None

    def sort(self, column: int, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel()
        reverse = order == Qt.SortOrder.DescendingOrder

        # Sort the full result set, then re-slice
        needs_stat = column in (COLUMN_SIZE, COLUMN_DATE_MOD, COLUMN_DATE_CREATE)
        if needs_stat:
            unfilled = sum(1 for e in self._all_results if not e._stat_loaded)
            if unfilled > 0 and unfilled <= 100_000:
                import time as _time
                t0 = _time.perf_counter()
                for entry in self._all_results:
                    entry.ensure_stat(self._index)
                elapsed = (_time.perf_counter() - t0) * 1000
                logger.debug(f"Table sort: loaded stats for {unfilled} entries in {elapsed:.0f}ms")

        try:
            if column == COLUMN_NAME:
                self._all_results.sort(key=lambda e: e.name.lower(), reverse=reverse)
            elif column == COLUMN_PATH:
                self._all_results.sort(
                    key=lambda e: (e._path or self._index.resolve_parent_path(e.drive, e.parent_frn)).lower(),
                    reverse=reverse
                )
            elif column == COLUMN_SIZE:
                self._all_results.sort(
                    key=lambda e: e.size if e._stat_loaded else -1,
                    reverse=reverse
                )
            elif column == COLUMN_DATE_MOD:
                _dt_min = datetime.min
                self._all_results.sort(
                    key=lambda e: e.date_modified or _dt_min,
                    reverse=reverse
                )
            elif column == COLUMN_DATE_CREATE:
                _dt_min = datetime.min
                self._all_results.sort(
                    key=lambda e: e.date_created or _dt_min,
                    reverse=reverse
                )
            elif column == COLUMN_TYPE:
                self._all_results.sort(key=lambda e: e.extension, reverse=reverse)
            elif column == COLUMN_ATTRIB:
                self._all_results.sort(key=lambda e: e.attributes, reverse=reverse)
        except Exception as exc:
            logger.error(f"Table sort failed: {exc}")

        # Re-slice visible entries
        self._entries = self._all_results[:self._loaded_count]
        self.endResetModel()


# ── Inline Column Filter Row ─────────────────────────────

class ColumnFilterRow(QWidget):
    """A row of filter inputs below the table header for per-column filtering."""
    filter_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._inputs: list[QLineEdit] = []
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.setFixedHeight(22)
        self.hide()

        style = f"""
            QLineEdit {{
                background: {MOCHA['surface0']};
                color: {MOCHA['text']};
                border: 1px solid {MOCHA['surface1']};
                border-radius: 0px;
                padding: 1px 4px;
                font-size: 11px;
            }}
            QLineEdit:focus {{
                border-color: {MOCHA['blue']};
            }}
        """
        self.setStyleSheet(style)

    def setup_columns(self, count: int):
        """Create filter inputs for each column."""
        for inp in self._inputs:
            inp.deleteLater()
        self._inputs.clear()

        for i in range(count):
            inp = QLineEdit()
            inp.setPlaceholderText("Filter...")
            inp.textChanged.connect(self.filter_changed)
            self._layout.addWidget(inp)
            self._inputs.append(inp)

    def get_filter(self, column: int) -> str:
        if 0 <= column < len(self._inputs):
            return self._inputs[column].text().strip().lower()
        return ""

    def has_active_filters(self) -> bool:
        return any(inp.text().strip() for inp in self._inputs)

    def clear_all(self):
        for inp in self._inputs:
            inp.blockSignals(True)
            inp.clear()
            inp.blockSignals(False)
        self.filter_changed.emit()

    def sync_widths(self, header: QHeaderView):
        """Sync filter input widths to match column header widths."""
        for i, inp in enumerate(self._inputs):
            if i < header.count():
                w = header.sectionSize(i)
                inp.setFixedWidth(w)
                inp.setVisible(not header.isSectionHidden(i))


class ResultsTableView(QTableView):
    """Everything-style compact table view for search results with drag support,
    column right-click menu, and keyboard navigation."""

    item_activated = pyqtSignal(object)  # FileEntry
    selection_changed = pyqtSignal(object)  # FileEntry or None
    open_folder_requested = pyqtSignal(object)  # FileEntry
    delete_requested = pyqtSignal(object)  # list[FileEntry]
    rename_requested = pyqtSignal(object)  # FileEntry
    quick_preview_requested = pyqtSignal()
    column_visibility_changed = pyqtSignal(dict)  # {column_index: bool}

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

        # Enable drag support
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

        # Column sizing
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setMinimumSectionSize(40)
        header.setSortIndicatorShown(True)
        header.setHighlightSections(False)

        # Column right-click menu
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._show_column_menu)

        # Highlight delegate
        self._highlight_delegate = HighlightDelegate(self)
        self.setItemDelegate(self._highlight_delegate)

        self.doubleClicked.connect(self._on_double_click)

    def set_highlight(self, text: str):
        """Set the text to highlight in results."""
        self._highlight_delegate.set_highlight(text)
        self.viewport().update()

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

    def keyPressEvent(self, event: QKeyEvent):
        """Keyboard navigation: Enter=open, Delete=recycle, F2=rename."""
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_Space and mods == Qt.KeyboardModifier.NoModifier:
            self.quick_preview_requested.emit()
            return

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            entries = self.selected_entries()
            if entries:
                if mods & Qt.KeyboardModifier.ControlModifier:
                    # Ctrl+Enter: open containing folder
                    self.open_folder_requested.emit(entries[0])
                else:
                    # Enter: open file/folder
                    self.item_activated.emit(entries[0])
            return

        if key == Qt.Key.Key_Delete:
            entries = self.selected_entries()
            if entries:
                self.delete_requested.emit(entries)
            return

        if key == Qt.Key.Key_F2:
            entries = self.selected_entries()
            if entries and len(entries) == 1:
                self.rename_requested.emit(entries[0])
            return

        super().keyPressEvent(event)

    def _show_column_menu(self, pos):
        """Show column visibility context menu on header right-click."""
        menu = QMenu(self)
        header = self.horizontalHeader()

        for i, (name, _) in enumerate(COLUMNS):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not header.isSectionHidden(i))
            action.triggered.connect(lambda checked, col=i: self._toggle_column(col, checked))

        menu.exec(header.mapToGlobal(pos))

    def _toggle_column(self, column: int, visible: bool):
        """Toggle column visibility."""
        self.setColumnHidden(column, not visible)
        # Emit signal so settings can persist
        vis = {}
        header = self.horizontalHeader()
        for i in range(len(COLUMNS)):
            vis[i] = not header.isSectionHidden(i)
        self.column_visibility_changed.emit(vis)

    def apply_column_visibility(self, visibility: dict):
        """Apply saved column visibility from settings."""
        # Map string column names to indices
        col_name_to_idx = {key: i for i, (_, key) in enumerate(COLUMNS)}
        # Also map display names and common aliases
        col_display_to_idx = {label.lower(): i for i, (label, _) in enumerate(COLUMNS)}
        aliases = {'modified': 'date_modified', 'created': 'date_created'}
        for col, visible in visibility.items():
            if isinstance(col, int):
                idx = col
            elif col in col_name_to_idx:
                idx = col_name_to_idx[col]
            elif col in aliases and aliases[col] in col_name_to_idx:
                idx = col_name_to_idx[aliases[col]]
            elif col.lower() in col_display_to_idx:
                idx = col_display_to_idx[col.lower()]
            else:
                continue
            if 0 <= idx < len(COLUMNS):
                self.setColumnHidden(idx, not visible)

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


class BreadcrumbHeader(QWidget):
    """Compact breadcrumb for the selected result path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        self._label = QLabel("No selection")
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._label.setStyleSheet(f"""
            QLabel {{
                color: {MOCHA['subtext1']};
                background-color: {MOCHA['mantle']};
                border-bottom: 1px solid {MOCHA['surface0']};
                font-size: 11px;
                padding: 2px 4px;
            }}
        """)
        layout.addWidget(self._label, 1)

    def set_path(self, path: str):
        segments = path_segments(path)
        if not segments:
            self._label.setText("No selection")
            self._label.setToolTip("")
            return
        self._label.setText("  >  ".join(segments))
        self._label.setToolTip(path)


class PathColumnModel(QAbstractTableModel):
    """Finder-style path segment columns for search results."""

    def __init__(self, index: FileIndex, parent=None):
        super().__init__(parent)
        self._index = index
        self._rows: list[tuple[FileEntry, list[str]]] = []
        self._column_count = 1

    def set_results(self, entries: list[FileEntry]):
        self.beginResetModel()
        self._rows = [
            (entry, compact_path_segments(path_segments(entry.get_path(self._index))))
            for entry in entries[:FETCH_BATCH_SIZE]
        ]
        self._column_count = max([len(segments) for _entry, segments in self._rows] or [1])
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self._rows.clear()
        self._column_count = 1
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return self._column_count

    def entry_at(self, row: int) -> Optional[FileEntry]:
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return None
        if section == 0:
            return "Root"
        if section == self._column_count - 1:
            return "Item"
        return f"Folder {section}"

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None
        entry, segments = self._rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return segments[col] if col < len(segments) else ""
        if role == Qt.ItemDataRole.DecorationRole and col == max(len(segments) - 1, 0):
            return FileIconCache.get(entry, self._index)
        if role == Qt.ItemDataRole.UserRole:
            return entry
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry.get_path(self._index)
        return None


class PathColumnView(QTableView):
    """Column-oriented path view for Finder-like scanning."""

    item_activated = pyqtSignal(object)
    selection_changed = pyqtSignal(object)
    quick_preview_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSortingEnabled(False)
        self.setShowGrid(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(22)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.doubleClicked.connect(self._on_double_click)

    def set_model(self, model: PathColumnModel):
        self.setModel(model)
        self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        for column in range(model.columnCount()):
            self.setColumnWidth(column, 180 if column else 120)

    def _on_double_click(self, index: QModelIndex):
        model = self.model()
        if isinstance(model, PathColumnModel):
            entry = model.entry_at(index.row())
            if entry:
                self.item_activated.emit(entry)

    def _on_selection_changed(self, selected, deselected):
        entries = self.selected_entries()
        self.selection_changed.emit(entries[0] if entries else None)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.quick_preview_requested.emit()
            return
        super().keyPressEvent(event)

    def selected_entries(self) -> list[FileEntry]:
        entries = []
        model = self.model()
        if isinstance(model, PathColumnModel):
            for idx in self.selectionModel().selectedRows():
                entry = model.entry_at(idx.row())
                if entry:
                    entries.append(entry)
        return entries


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
    quick_preview_requested = pyqtSignal()

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

        # Enable drag
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)

        self.doubleClicked.connect(self._on_double_click)

    def set_model(self, model: ResultsTableModel):
        self.setModel(model)
        selection_model = self.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(self._on_selection_changed)

    def _on_double_click(self, index: QModelIndex):
        model = self.model()
        if isinstance(model, ResultsTableModel):
            entry = model.entry_at(index.row())
            if entry:
                self.item_activated.emit(entry)

    def _on_selection_changed(self, selected, deselected):
        entries = self.selected_entries()
        self.selection_changed.emit(entries[0] if entries else None)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.quick_preview_requested.emit()
            return
        super().keyPressEvent(event)

    def selected_entries(self) -> list[FileEntry]:
        entries = []
        seen_rows = set()
        model = self.model()
        if isinstance(model, ResultsTableModel):
            for idx in self.selectedIndexes():
                row = idx.row()
                if row in seen_rows:
                    continue
                seen_rows.add(row)
                entry = model.entry_at(row)
                if entry:
                    entries.append(entry)
        return entries


class ResultsView(QWidget):
    """Results container with breadcrumb, details, columns, and thumbnail views."""

    item_activated = pyqtSignal(object)
    selection_changed = pyqtSignal(object)
    open_folder_requested = pyqtSignal(object)
    delete_requested = pyqtSignal(object)
    rename_requested = pyqtSignal(object)
    quick_preview_requested = pyqtSignal()
    column_visibility_changed = pyqtSignal(dict)

    def __init__(self, index: FileIndex, parent=None):
        super().__init__(parent)
        self._file_index = index
        self._model = ResultsTableModel(index)
        self._path_column_model = PathColumnModel(index)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.breadcrumb_header = BreadcrumbHeader()
        describe_widget(
            self.breadcrumb_header,
            "Selected result path",
            "Shows the full path for the selected search result.",
        )
        layout.addWidget(self.breadcrumb_header)

        self._stack = QStackedWidget()
        describe_widget(
            self._stack,
            "Results view mode",
            "Contains details, path column, and thumbnail result views.",
        )
        layout.addWidget(self._stack, 1)

        # Table view (index 0)
        self.table_view = ResultsTableView()
        describe_widget(self.table_view, "Search results", "File search results table.")
        self.table_view.set_model(self._model)
        self.table_view.item_activated.connect(self.item_activated)
        self.table_view.selection_changed.connect(self._on_child_selection_changed)
        self.table_view.open_folder_requested.connect(self.open_folder_requested)
        self.table_view.delete_requested.connect(self.delete_requested)
        self.table_view.rename_requested.connect(self.rename_requested)
        self.table_view.quick_preview_requested.connect(self.quick_preview_requested)
        self.table_view.column_visibility_changed.connect(self.column_visibility_changed)
        self._stack.addWidget(self.table_view)

        # Finder-style path columns (index 1)
        self.column_view = PathColumnView()
        describe_widget(
            self.column_view,
            "Path column results",
            "Search results displayed as path segments.",
        )
        self.column_view.set_model(self._path_column_model)
        self.column_view.item_activated.connect(self.item_activated)
        self.column_view.selection_changed.connect(self._on_child_selection_changed)
        self.column_view.quick_preview_requested.connect(self.quick_preview_requested)
        self._stack.addWidget(self.column_view)

        # Thumbnail view (index 2)
        self.thumb_view = ThumbnailListView()
        describe_widget(
            self.thumb_view,
            "Thumbnail results",
            "Search results displayed as large icons and thumbnails.",
        )
        self.thumb_view.set_model(self._model)
        self.thumb_view.item_activated.connect(self.item_activated)
        self.thumb_view.selection_changed.connect(self._on_child_selection_changed)
        self.thumb_view.quick_preview_requested.connect(self.quick_preview_requested)
        self._stack.addWidget(self.thumb_view)

    @property
    def model(self) -> ResultsTableModel:
        return self._model

    def set_results(self, entries: list[FileEntry]):
        self._model.set_results(entries)
        self._path_column_model.set_results(entries)
        for column in range(self._path_column_model.columnCount()):
            self.column_view.setColumnWidth(column, 180 if column else 120)
        self.breadcrumb_header.set_path("")

    def remove_paths(self, paths: list[str]) -> int:
        keys = {_normalized_result_path(path) for path in paths}
        if not keys:
            return 0
        remaining = []
        removed = 0
        for entry in self._model.entries:
            try:
                entry_key = _normalized_result_path(entry.get_path(self._file_index))
            except Exception:
                remaining.append(entry)
                continue
            if entry_key in keys:
                removed += 1
            else:
                remaining.append(entry)
        if removed:
            self.set_results(remaining)
        return removed

    def set_highlight(self, text: str):
        self.table_view.set_highlight(text)

    def clear(self):
        self._model.clear()
        self._path_column_model.clear()
        self.breadcrumb_header.set_path("")

    def show_table_view(self):
        self._stack.setCurrentIndex(0)

    def show_column_view(self):
        self._stack.setCurrentIndex(1)

    def show_thumbnail_view(self):
        self._stack.setCurrentIndex(2)

    def selected_entries(self) -> list[FileEntry]:
        if self._stack.currentIndex() == 0:
            return self.table_view.selected_entries()
        if self._stack.currentIndex() == 1:
            return self.column_view.selected_entries()
        return self.thumb_view.selected_entries()

    @property
    def result_count(self) -> int:
        return self._model.total_count

    def _on_child_selection_changed(self, entry: Optional[FileEntry]):
        if entry is None:
            self.breadcrumb_header.set_path("")
        else:
            self.breadcrumb_header.set_path(entry.get_path(self._file_index))
        self.selection_changed.emit(entry)


def _normalized_result_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))
