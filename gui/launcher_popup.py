"""
Floating launcher/popup search bar activated by global hotkey.
"""

import os
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QApplication, QLabel, QHBoxLayout,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QColor, QKeyEvent

from gui.theme import MOCHA, ACCENT
from core.search import SearchEngine, SearchOptions

logger = logging.getLogger('QuickFind.Launcher')

MAX_RESULTS = 12


class LauncherPopup(QWidget):
    """Compact floating search popup."""

    file_opened = pyqtSignal(str)

    def __init__(self, search_engine: SearchEngine, file_index, parent=None):
        super().__init__(parent)
        self._engine = search_engine
        self._file_index = file_index
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(100)
        self._debounce.timeout.connect(self._do_search)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_ui()
        self.setFixedWidth(680)
        self.hide()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        container = QWidget()
        container.setObjectName("launcher_container")
        container.setStyleSheet(f"""
            #launcher_container {{
                background: {MOCHA['base']};
                border: 2px solid {ACCENT};
                border-radius: 12px;
            }}
        """)
        inner = QVBoxLayout(container)
        inner.setContentsMargins(8, 8, 8, 8)
        inner.setSpacing(4)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search files and folders...")
        self._search_input.setAccessibleName("Quick search")
        self._search_input.setAccessibleDescription("Type to search files, press Escape to dismiss")
        self._search_input.setFont(QFont("Segoe UI", 16))
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {MOCHA['surface0']};
                color: {MOCHA['text']};
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
            }}
        """)
        self._search_input.textChanged.connect(self._on_text_changed)
        inner.addWidget(self._search_input)

        self._results_list = QListWidget()
        self._results_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                color: {MOCHA['text']};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: 6px 12px;
                border-radius: 6px;
            }}
            QListWidget::item:selected {{
                background: {MOCHA['surface1']};
            }}
            QListWidget::item:hover {{
                background: {MOCHA['surface0']};
            }}
        """)
        self._results_list.setFont(QFont("Segoe UI", 11))
        self._results_list.itemActivated.connect(self._on_item_activated)
        self._results_list.hide()
        inner.addWidget(self._results_list)

        layout.addWidget(container)

    def _on_text_changed(self, text: str):
        self._debounce.start()

    def _do_search(self):
        query = self._search_input.text().strip()
        self._results_list.clear()

        if not query:
            self._results_list.hide()
            self.adjustSize()
            return

        results = self._engine.search(query, max_results=MAX_RESULTS)

        if not results:
            self._results_list.hide()
            self.adjustSize()
            return

        for entry in results:
            path = entry.get_path(self._file_index)
            item = QListWidgetItem(f"{entry.name}\n{path}")
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._results_list.addItem(item)

        self._results_list.show()
        self._results_list.setFixedHeight(min(len(results), MAX_RESULTS) * 48)
        self.adjustSize()

    def _on_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            try:
                os.startfile(path)
                from core.cache import record_file_open
                record_file_open(path)
            except OSError:
                pass
            self.file_opened.emit(path)
        self.dismiss()

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.dismiss()
        elif key == Qt.Key.Key_Down:
            if self._results_list.isVisible():
                self._results_list.setFocus()
                if self._results_list.currentRow() < 0:
                    self._results_list.setCurrentRow(0)
        elif key == Qt.Key.Key_Up:
            if self._results_list.isVisible() and self._results_list.currentRow() <= 0:
                self._search_input.setFocus()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._results_list.isVisible() and self._results_list.currentRow() >= 0:
                item = self._results_list.currentItem()
                if item:
                    self._on_item_activated(item)
            elif self._results_list.isVisible() and self._results_list.count() > 0:
                self._results_list.setCurrentRow(0)
                item = self._results_list.currentItem()
                if item:
                    self._on_item_activated(item)
        else:
            super().keyPressEvent(event)

    def show_popup(self):
        """Show the popup centered on the primary screen."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + int(geo.height() * 0.25)
            self.move(x, y)

        self._search_input.clear()
        self._results_list.clear()
        self._results_list.hide()
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search_input.setFocus()

    def dismiss(self):
        self._search_input.clear()
        self._results_list.clear()
        self._results_list.hide()
        self.hide()

    def focusOutEvent(self, event):
        QTimer.singleShot(100, self._check_focus_lost)
        super().focusOutEvent(event)

    def _check_focus_lost(self):
        focused = QApplication.focusWidget()
        if focused and (focused is self or self.isAncestorOf(focused)):
            return
        self.dismiss()
