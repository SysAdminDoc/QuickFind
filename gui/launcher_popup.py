"""
Floating launcher/popup search bar activated by global hotkey.
"""

import os
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QApplication, QLabel, QHBoxLayout,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QColor, QKeyEvent

from gui.theme import MOCHA
from core.dialog_switch import switch_dialog_to_folder
from core.search import SearchEngine, SearchOptions

logger = logging.getLogger('QuickFind.Launcher')

MAX_RESULTS = 10


class _LauncherSearchWorker(QThread):
    """Runs a launcher query off the GUI thread so content/regex/dupe queries
    (which the launcher accepts) cannot freeze the UI per keystroke."""

    results_ready = pyqtSignal(str, list)

    def __init__(self, engine, query, max_results):
        super().__init__()
        self._engine = engine
        self._query = query
        self._max_results = max_results
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            results = self._engine.search(
                self._query,
                max_results=self._max_results,
                cancel_check=lambda: self._cancelled,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Launcher search failed: %s", exc)
            results = []
        if not self._cancelled:
            self.results_ready.emit(self._query, results)


class LauncherPopup(QWidget):
    """Compact floating search popup."""

    file_opened = pyqtSignal(str)

    def __init__(self, search_engine: SearchEngine, file_index, parent=None,
                 dialog_quick_switch_enabled: bool = False):
        super().__init__(parent)
        self._engine = search_engine
        self._file_index = file_index
        self._dialog_quick_switch_enabled = dialog_quick_switch_enabled
        self._worker: Optional[_LauncherSearchWorker] = None
        self._pending_workers: list = []
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._do_search)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._setup_ui()
        self.setFixedWidth(640)
        self.hide()

    def set_dialog_quick_switch_enabled(self, enabled: bool):
        self._dialog_quick_switch_enabled = enabled

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)

        container = QWidget()
        container.setObjectName("launcher_container")
        container.setStyleSheet(f"""
            #launcher_container {{
                background: {MOCHA['base']};
                border: 1px solid {MOCHA['surface1']};
                border-radius: 14px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 120))
        shadow.setOffset(0, 8)
        container.setGraphicsEffect(shadow)

        inner = QVBoxLayout(container)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(0)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search files and folders…")
        self._search_input.setAccessibleName("Quick search")
        self._search_input.setAccessibleDescription("Type to search files, press Escape to dismiss")
        self._search_input.setFont(QFont("Segoe UI", 15))
        self._search_input.setStyleSheet(f"""
            QLineEdit {{
                background: {MOCHA['surface0']};
                color: {MOCHA['text']};
                border: 1px solid transparent;
                border-radius: 10px;
                padding: 12px 18px;
                selection-background-color: {MOCHA['surface2']};
            }}
            QLineEdit:focus {{
                border-color: {MOCHA['surface1']};
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
                padding-top: 4px;
            }}
            QListWidget::item {{
                padding: 8px 14px;
                border-radius: 8px;
                margin: 1px 2px;
            }}
            QListWidget::item:selected {{
                background: {MOCHA['surface0']};
            }}
            QListWidget::item:hover {{
                background: {MOCHA['surface0']};
            }}
        """)
        self._results_list.setFont(QFont("Segoe UI", 10))
        self._results_list.setSpacing(1)
        self._results_list.itemActivated.connect(self._on_item_activated)
        self._results_list.hide()
        inner.addWidget(self._results_list)

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet(f"""
            QLabel {{
                color: {MOCHA['overlay0']};
                font-size: 11px;
                padding: 6px 14px 4px 14px;
            }}
        """)
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._hint_label.hide()
        inner.addWidget(self._hint_label)

        layout.addWidget(container)

    def _on_text_changed(self, text: str):
        self._debounce.start()

    def _do_search(self):
        query = self._search_input.text().strip()

        if not query:
            self._cancel_worker()
            self._results_list.clear()
            self._results_list.hide()
            self._hint_label.hide()
            self.adjustSize()
            return

        # Run the query off the GUI thread; results are rendered when they
        # arrive and only if the query still matches the current input.
        self._cancel_worker()
        worker = _LauncherSearchWorker(self._engine, query, MAX_RESULTS)
        worker.results_ready.connect(self._on_results_ready)
        worker.finished.connect(lambda w=worker: self._retire_worker(w))
        self._worker = worker
        worker.start()

    def _cancel_worker(self):
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._pending_workers.append(self._worker)
        self._worker = None

    def _retire_worker(self, worker):
        try:
            self._pending_workers.remove(worker)
        except ValueError:
            pass
        try:
            worker.deleteLater()
        except RuntimeError:
            pass

    def _on_results_ready(self, query: str, results: list):
        # Ignore stale results from a superseded query.
        if query != self._search_input.text().strip():
            return
        self._results_list.clear()

        if not results:
            self._results_list.hide()
            self._hint_label.setText("No files found")
            self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._hint_label.show()
            self.adjustSize()
            return

        for entry in results:
            path = entry.get_path(self._file_index)
            name = entry.name
            parent = os.path.dirname(path)
            display = f"{name}\n{parent}"
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setForeground(QColor(MOCHA['text']))
            self._results_list.addItem(item)

        self._results_list.show()
        self._results_list.setFixedHeight(min(len(results), MAX_RESULTS) * 44)

        count_text = f"{len(results)} result{'s' if len(results) != 1 else ''}"
        if len(results) == MAX_RESULTS:
            count_text += "+"
        self._hint_label.setText(f"{count_text}  ·  Enter to open  ·  Esc to close")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint_label.show()
        self.adjustSize()

    def _on_item_activated(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            if self._dialog_quick_switch_enabled:
                result = switch_dialog_to_folder(path)
                if result.ok:
                    self.file_opened.emit(result.folder)
                    self.dismiss()
                    return
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
            y = geo.y() + int(geo.height() * 0.28)
            self.move(x, y)

        self._search_input.clear()
        self._results_list.clear()
        self._results_list.hide()
        self._hint_label.hide()
        self.adjustSize()
        self.show()
        self.raise_()
        self.activateWindow()
        self._search_input.setFocus()

    def dismiss(self):
        self._cancel_worker()
        self._search_input.clear()
        self._results_list.clear()
        self._results_list.hide()
        self._hint_label.hide()
        self.hide()

    def focusOutEvent(self, event):
        QTimer.singleShot(150, self._check_focus_lost)
        super().focusOutEvent(event)

    def _check_focus_lost(self):
        focused = QApplication.focusWidget()
        if focused and (focused is self or self.isAncestorOf(focused)):
            return
        self.dismiss()
