"""
QuickFind Main Window - Everything-compatible file search UI.
v0.7.0: Dark title bar, regex validation, result count in tabs, tray tooltip
         progress, exclude hidden/system wiring, window state restore.
"""

import ctypes
import os
import re
import logging
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QSplitter, QStatusBar, QLabel, QMenuBar, QMenu, QComboBox,
    QProgressBar, QApplication, QMessageBox, QTabWidget, QTabBar,
    QCompleter, QToolTip
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QThread, pyqtSlot, QStringListModel, QPoint
from PyQt6.QtGui import (
    QAction, QIcon, QPixmap, QPainter, QColor, QFont, QKeySequence,
    QCloseEvent
)

from core.index import FileIndex, FileEntry, IndexWorker
from core.search import SearchEngine, SearchOptions, SearchFilter, BUILTIN_FILTERS
from core.file_list import load_efu
from core.everything_import import import_all as import_everything

from gui.theme import MOCHA, ACCENT
from gui.results_view import ResultsView
from gui.preview_pane import PreviewPane
from gui.filters import FilterBar
from gui.bookmarks import BookmarkManager, BookmarksPanel, Bookmark
from gui.context_menu import build_context_menu
from gui.tray import SystemTray
from gui.settings_dialog import Settings, SettingsDialog
from core.hidden_paths import HiddenPathsManager

logger = logging.getLogger('QuickFind.MainWindow')

VERSION = "0.7.0"


def _set_dark_title_bar(hwnd):
    """Enable dark title bar on Windows 10/11 via DwmSetWindowAttribute."""
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


APP_TITLE = f"QuickFind v{VERSION}"

# Search syntax help text
SYNTAX_HELP = """Search Syntax:
  *.ext           Extension filter (e.g., *.py)
  ext:pdf         Extension modifier
  size:>1mb       Size filter (kb, mb, gb)
  dm:today        Date modified (today, yesterday, thisweek, thismonth)
  dc:>2024-01-01  Date created range
  parent:folder   Parent directory name
  len:>10         Filename length
  attrib:H        Attribute filter (R,H,S,D,A)
  dupe:name       Find duplicates by name/size
  regex:pattern   Regex search
  content:text    Content search (slow)
  "exact match"   Quoted exact phrase
  term1 term2     AND (both must match)
  term1 | term2   OR (either matches)
  !term           NOT (exclude matches)"""


class SearchWorker(QThread):
    """Background thread for search execution."""
    results_ready = pyqtSignal(list)

    def __init__(self, engine: SearchEngine, query: str,
                 active_filter=None, options=None):
        super().__init__()
        self._engine = engine
        self._query = query
        self._filter = active_filter
        self._options = options
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        results = self._engine.search(
            self._query,
            active_filter=self._filter,
            base_options=self._options,
            cancel_check=lambda: self._cancelled,
        )
        if not self._cancelled:
            self.results_ready.emit(results)


class SearchTab:
    """State for a single search tab."""
    def __init__(self, file_index: FileIndex):
        self.results_view = ResultsView(file_index)
        self.query = ""
        self.filter_index = 0
        self.search_worker: Optional[SearchWorker] = None


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Core components
        self._settings = Settings.load()
        self._file_index = FileIndex()
        self._search_engine = SearchEngine(self._file_index)
        self._bookmark_manager = BookmarkManager()
        self._hidden_paths_manager = HiddenPathsManager()

        # State
        self._search_worker: Optional[SearchWorker] = None
        self._index_worker: Optional[IndexWorker] = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(self._settings.search_delay_ms)
        self._search_timer.timeout.connect(self._execute_search)

        # Live status bar refresh timer
        self._status_refresh_timer = QTimer()
        self._status_refresh_timer.setInterval(5000)  # Update every 5 seconds
        self._status_refresh_timer.timeout.connect(self._refresh_status_bar)

        # Search history completer model
        self._history_model = QStringListModel()

        self._setup_ui()
        self._setup_menus()
        self._setup_tray()
        self._connect_signals()
        self._apply_settings()

        # Dark title bar
        _set_dark_title_bar(int(self.winId()))

        # Wire exclude/USN settings to FileIndex
        self._file_index._exclude_hidden = self._settings.exclude_hidden
        self._file_index._exclude_system = self._settings.exclude_system
        self._file_index._usn_poll_interval_ms = self._settings.usn_poll_interval_ms

        # Start maximized
        if self._settings.start_maximized:
            self.showMaximized()

        # Start indexing — try cache first for instant startup
        if self._settings.index_on_startup:
            QTimer.singleShot(100, self._start_indexing_with_cache)

        # Start live status bar updates
        self._status_refresh_timer.start()

        # Load search history for autocomplete
        self._refresh_search_history()

    def _setup_ui(self):
        """Build the UI layout."""
        self.setWindowTitle(APP_TITLE)
        self.resize(self._settings.window_width, self._settings.window_height)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Search row (Everything-style: single compact row) ──
        search_row = QWidget()
        search_row.setObjectName("searchRow")
        search_row.setFixedHeight(26)
        search_row.setStyleSheet(f"""
            #searchRow {{
                background-color: {MOCHA['mantle']};
                border-bottom: 1px solid {MOCHA['surface0']};
            }}
        """)
        search_layout = QHBoxLayout(search_row)
        search_layout.setContentsMargins(2, 2, 2, 2)
        search_layout.setSpacing(4)

        # Filter dropdown (Everything-style)
        self._filter_combo = QComboBox()
        self._filter_combo.setObjectName("filterCombo")
        self._filter_combo.setFixedHeight(22)
        self._filter_combo.setFixedWidth(120)
        self._build_filter_combo()
        search_layout.addWidget(self._filter_combo)

        # Search input (fills remaining space) with autocomplete
        self._search_input = QLineEdit()
        self._search_input.setFixedHeight(22)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setPlaceholderText("Search files and folders...")
        self._search_input.setToolTip(SYNTAX_HELP)

        # Autocomplete from search history
        self._completer = QCompleter()
        self._completer.setModel(self._history_model)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setMaxVisibleItems(10)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._search_input.setCompleter(self._completer)

        search_layout.addWidget(self._search_input)

        main_layout.addWidget(search_row)

        # ── Tab widget for multi-tab search ──
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self._tab_widget.tabCloseRequested.connect(self._close_tab)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {MOCHA['surface0']};
                color: {MOCHA['subtext0']};
                padding: 4px 12px;
                border: none;
                border-right: 1px solid {MOCHA['base']};
                min-width: 80px;
            }}
            QTabBar::tab:selected {{
                background: {MOCHA['base']};
                color: {MOCHA['text']};
            }}
            QTabBar::tab:hover {{
                background: {MOCHA['surface1']};
            }}
            QTabBar::close-button {{
                image: none;
                subcontrol-position: right;
            }}
            QTabBar::close-button:hover {{
                background: {MOCHA['surface2']};
            }}
        """)

        # ── Main content area (results dominate) ──
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Bookmarks panel (left, hidden by default)
        self._bookmarks_panel = BookmarksPanel(self._bookmark_manager)
        self._bookmarks_panel.setMinimumWidth(150)
        self._bookmarks_panel.setMaximumWidth(300)
        self._bookmarks_panel.hide()

        # First search tab
        self._tabs: list[SearchTab] = []
        self._add_new_tab("Search")

        # Preview pane (right, hidden by default)
        self._preview_pane = PreviewPane(self._file_index)
        self._preview_pane.setMinimumWidth(200)

        self._splitter.addWidget(self._bookmarks_panel)
        self._splitter.addWidget(self._tab_widget)
        self._splitter.addWidget(self._preview_pane)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._splitter.setSizes([0, 1000, 300])

        main_layout.addWidget(self._splitter, 1)

        # ── Status bar (compact, Everything-style with live stats) ──
        self._status_bar = QStatusBar()
        self._status_bar.setSizeGripEnabled(True)
        self.setStatusBar(self._status_bar)

        self._result_count_label = QLabel("0 objects")
        self._result_count_label.setStyleSheet(f"color: {MOCHA['subtext0']}; font-size: 11px; padding: 0 4px;")
        self._status_bar.addWidget(self._result_count_label)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {MOCHA['overlay0']}; font-size: 11px;")
        self._status_bar.addWidget(self._status_label, 1)

        # Live DB stats
        self._db_stats_label = QLabel("")
        self._db_stats_label.setStyleSheet(f"color: {MOCHA['overlay1']}; font-size: 11px; padding: 0 6px;")
        self._status_bar.addPermanentWidget(self._db_stats_label)

        # Startup performance metrics
        self._perf_label = QLabel("")
        self._perf_label.setStyleSheet(f"color: {MOCHA['overlay1']}; font-size: 11px; padding: 0 6px;")
        self._status_bar.addPermanentWidget(self._perf_label)

        self._last_update_label = QLabel("")
        self._last_update_label.setStyleSheet(f"color: {MOCHA['overlay1']}; font-size: 11px; padding: 0 6px;")
        self._status_bar.addPermanentWidget(self._last_update_label)

        self._index_status = QLabel("")
        self._index_status.setStyleSheet(f"color: {MOCHA['subtext0']}; font-size: 11px; padding: 0 4px;")
        self._status_bar.addPermanentWidget(self._index_status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(150)
        self._progress_bar.setMaximumHeight(10)
        self._progress_bar.setRange(0, 0)
        self._progress_bar.hide()
        self._status_bar.addPermanentWidget(self._progress_bar)

        # Keep FilterBar reference for compatibility (hidden, manages custom filters)
        self._filter_bar = FilterBar()
        self._filter_bar.hide()

    # ── Tab management ────────────────────────────────

    def _add_new_tab(self, title: str = "Search") -> SearchTab:
        tab = SearchTab(self._file_index)
        self._tabs.append(tab)
        idx = self._tab_widget.addTab(tab.results_view, title)

        # Connect signals for the new tab's results view
        tab.results_view.item_activated.connect(self._on_item_activated)
        tab.results_view.selection_changed.connect(self._on_selection_changed)
        tab.results_view.open_folder_requested.connect(self._on_open_folder)
        tab.results_view.delete_requested.connect(self._on_delete_requested)
        tab.results_view.rename_requested.connect(self._on_rename_requested)
        tab.results_view.column_visibility_changed.connect(self._on_column_visibility_changed)
        tab.results_view.table_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        tab.results_view.table_view.customContextMenuRequested.connect(
            self._show_context_menu
        )

        self._tab_widget.setCurrentIndex(idx)
        return tab

    def _close_tab(self, index: int):
        if self._tab_widget.count() <= 1:
            return  # Don't close the last tab
        tab = self._tabs[index]
        if tab.search_worker and tab.search_worker.isRunning():
            tab.search_worker.cancel()
            tab.search_worker.wait(1000)
        self._tab_widget.removeTab(index)
        self._tabs.pop(index)

    def _on_tab_changed(self, index: int):
        if index < 0 or index >= len(self._tabs):
            return
        tab = self._tabs[index]
        # Restore search input and filter for this tab
        self._search_input.blockSignals(True)
        self._search_input.setText(tab.query)
        self._search_input.blockSignals(False)
        self._filter_combo.blockSignals(True)
        self._filter_combo.setCurrentIndex(tab.filter_index)
        self._filter_combo.blockSignals(False)
        # Update result count (guard: label may not exist yet during init)
        if hasattr(self, '_result_count_label'):
            count = tab.results_view.result_count
            self._result_count_label.setText(f"{count:,} object{'s' if count != 1 else ''}")

    def _current_tab(self) -> Optional[SearchTab]:
        idx = self._tab_widget.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]
        return None

    @property
    def _results_view(self) -> ResultsView:
        """Get the current tab's results view (backwards-compatible property)."""
        tab = self._current_tab()
        if tab:
            return tab.results_view
        return self._tabs[0].results_view if self._tabs else None

    def _build_filter_combo(self):
        """Populate the filter dropdown with built-in and custom filters."""
        self._filter_combo.clear()
        self._filter_objects: list[SearchFilter] = []

        for name, factory in BUILTIN_FILTERS.items():
            f = factory()
            self._filter_combo.addItem(name)
            self._filter_objects.append(f)

        # Load custom filters
        from gui.filters import FILTERS_FILE
        import json
        if FILTERS_FILE.exists():
            try:
                with open(FILTERS_FILE, 'r') as fp:
                    data = json.load(fp)
                if data:
                    self._filter_combo.insertSeparator(self._filter_combo.count())
                    for item in data:
                        f = SearchFilter(
                            name=item.get('name', 'Custom'),
                            extensions=item.get('extensions', []),
                            min_size=item.get('min_size', 0),
                            max_size=item.get('max_size', 0),
                            files_only=item.get('files_only', False),
                            folders_only=item.get('folders_only', False),
                            macro=item.get('macro', ''),
                            exclude_paths=item.get('exclude_paths', []),
                        )
                        self._filter_combo.addItem(item.get('name', 'Custom'))
                        self._filter_objects.append(f)
            except Exception:
                pass

        # Default to "Everything"
        self._filter_combo.setCurrentIndex(0)

    def _get_active_filter(self) -> Optional[SearchFilter]:
        """Get the currently selected filter from the dropdown."""
        idx = self._filter_combo.currentIndex()
        # Account for separator items
        if 0 <= idx < len(self._filter_objects):
            return self._filter_objects[idx]
        # Try to find by matching text
        name = self._filter_combo.currentText()
        for f in self._filter_objects:
            if f.name == name:
                return f
        return self._filter_objects[0] if self._filter_objects else None

    def _setup_menus(self):
        """Build the menu bar (Everything-style)."""
        menubar = self.menuBar()

        # ── File menu ───────────────────────────────
        file_menu = menubar.addMenu("&File")

        new_window = file_menu.addAction("New &Window")
        new_window.setShortcut(QKeySequence("Ctrl+N"))
        new_window.triggered.connect(self._new_window)

        new_tab = file_menu.addAction("New &Tab")
        new_tab.setShortcut(QKeySequence("Ctrl+T"))
        new_tab.triggered.connect(lambda: self._add_new_tab("Search"))

        close_tab = file_menu.addAction("&Close Tab")
        close_tab.setShortcut(QKeySequence("Ctrl+W"))
        close_tab.triggered.connect(lambda: self._close_tab(self._tab_widget.currentIndex()))

        file_menu.addSeparator()

        open_efu = file_menu.addAction("Open File &List...")
        open_efu.triggered.connect(self._open_efu)

        export_efu = file_menu.addAction("&Export Results as EFU...")
        export_efu.triggered.connect(self._export_efu)

        file_menu.addSeparator()

        exit_action = file_menu.addAction("E&xit")
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self._quit)

        # ── Edit menu ──────────────────────────────
        edit_menu = menubar.addMenu("&Edit")

        select_all = edit_menu.addAction("Select &All")
        select_all.setShortcut(QKeySequence("Ctrl+A"))
        select_all.triggered.connect(lambda: self._results_view.table_view.select_all_results())

        edit_menu.addSeparator()

        copy_path = edit_menu.addAction("&Copy Path")
        copy_path.setShortcut(QKeySequence("Ctrl+C"))
        copy_path.triggered.connect(self._copy_selected_paths)

        copy_name = edit_menu.addAction("Copy &Name")
        copy_name.setShortcut(QKeySequence("Ctrl+Shift+C"))
        copy_name.triggered.connect(self._copy_selected_names)

        # ── Search menu ─────────────────────────────
        search_menu = menubar.addMenu("&Search")

        focus_search = search_menu.addAction("&Focus Search")
        focus_search.setShortcut(QKeySequence("Ctrl+F"))
        focus_search.triggered.connect(self._focus_search)

        search_menu.addSeparator()

        self._match_case_action = search_menu.addAction("Match &Case")
        self._match_case_action.setCheckable(True)
        self._match_case_action.setShortcut(QKeySequence("Alt+C"))
        self._match_case_action.toggled.connect(lambda: self._trigger_search())

        self._regex_action = search_menu.addAction("&Regex")
        self._regex_action.setCheckable(True)
        self._regex_action.setShortcut(QKeySequence("Alt+R"))
        self._regex_action.toggled.connect(lambda: self._trigger_search())

        self._match_path_action = search_menu.addAction("Match &Path")
        self._match_path_action.setCheckable(True)
        self._match_path_action.setShortcut(QKeySequence("Alt+P"))
        self._match_path_action.toggled.connect(lambda: self._trigger_search())

        self._match_whole_action = search_menu.addAction("Match &Whole Word")
        self._match_whole_action.setCheckable(True)
        self._match_whole_action.setShortcut(QKeySequence("Alt+W"))
        self._match_whole_action.toggled.connect(lambda: self._trigger_search())

        search_menu.addSeparator()

        clear_history = search_menu.addAction("Clear Search &History")
        clear_history.triggered.connect(self._clear_search_history)

        search_menu.addSeparator()

        # Filter submenu
        filter_submenu = search_menu.addMenu("Fi&lter")
        for i, (name, factory) in enumerate(BUILTIN_FILTERS.items()):
            act = filter_submenu.addAction(name)
            act.triggered.connect(lambda checked, idx=i: self._filter_combo.setCurrentIndex(idx))

        # ── View menu ───────────────────────────────
        view_menu = menubar.addMenu("&View")

        self._detail_view_action = view_menu.addAction("&Details")
        self._detail_view_action.setCheckable(True)
        self._detail_view_action.setChecked(True)
        self._detail_view_action.triggered.connect(lambda: self._set_view_mode('details'))

        self._thumb_view_action = view_menu.addAction("&Thumbnails")
        self._thumb_view_action.setCheckable(True)
        self._thumb_view_action.triggered.connect(lambda: self._set_view_mode('thumbnails'))

        view_menu.addSeparator()

        self._preview_action = view_menu.addAction("Preview &Pane")
        self._preview_action.setCheckable(True)
        self._preview_action.setChecked(self._settings.show_preview_pane)
        self._preview_action.setShortcut(QKeySequence("Alt+V"))
        self._preview_action.toggled.connect(self._toggle_preview)

        self._bookmarks_action = view_menu.addAction("&Bookmarks Panel")
        self._bookmarks_action.setCheckable(True)
        self._bookmarks_action.setShortcut(QKeySequence("Ctrl+B"))
        self._bookmarks_action.toggled.connect(self._toggle_bookmarks)

        self._status_bar_action = view_menu.addAction("&Status Bar")
        self._status_bar_action.setCheckable(True)
        self._status_bar_action.setChecked(True)
        self._status_bar_action.toggled.connect(self._toggle_status_bar)

        # ── Bookmarks menu ──────────────────────────
        self._bookmarks_menu = menubar.addMenu("&Bookmarks")

        add_bookmark = self._bookmarks_menu.addAction("&Add Bookmark")
        add_bookmark.setShortcut(QKeySequence("Ctrl+D"))
        add_bookmark.triggered.connect(self._add_bookmark)

        manage_bookmarks = self._bookmarks_menu.addAction("&Manage Bookmarks")
        manage_bookmarks.setShortcut(QKeySequence("Ctrl+Shift+B"))
        manage_bookmarks.triggered.connect(lambda: self._toggle_bookmarks(True))

        self._bookmarks_menu.addSeparator()
        self._bookmarks_panel.build_menu(self._bookmarks_menu)

        # ── Tools menu ──────────────────────────────
        tools_menu = menubar.addMenu("&Tools")

        reindex = tools_menu.addAction("&Rebuild Index")
        reindex.setShortcut(QKeySequence("Ctrl+Shift+R"))
        reindex.triggered.connect(self._start_indexing)

        tools_menu.addSeparator()

        import_ev_action = tools_menu.addAction("&Import from Everything...")
        import_ev_action.triggered.connect(self._import_from_everything)

        manage_filters = tools_menu.addAction("Manage &Filters...")
        manage_filters.triggered.connect(self._show_manage_filters)

        manage_hidden = tools_menu.addAction("Manage &Hidden Paths...")
        manage_hidden.triggered.connect(self._show_manage_hidden_paths)

        tools_menu.addSeparator()

        settings_action = tools_menu.addAction("&Settings...")
        settings_action.triggered.connect(self._show_settings)

        # ── Help menu ───────────────────────────────
        help_menu = menubar.addMenu("&Help")

        syntax_help = help_menu.addAction("Search &Syntax")
        syntax_help.triggered.connect(self._show_syntax_help)

        help_menu.addSeparator()

        about_action = help_menu.addAction("&About QuickFind")
        about_action.triggered.connect(self._show_about)

    def _setup_tray(self):
        """Setup system tray icon."""
        self._tray = SystemTray(self)
        self._tray.show_requested.connect(self._show_from_tray)
        self._tray.quit_requested.connect(self._quit)
        self._tray.show()
        self._tray.start_hotkey()

    def _connect_signals(self):
        """Connect all signals."""
        # Search
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        # Index
        self._file_index.indexing_started.connect(self._on_indexing_started)
        self._file_index.indexing_progress.connect(self._on_indexing_progress)
        self._file_index.indexing_complete.connect(self._on_indexing_complete)
        self._file_index.index_updated.connect(self._on_index_updated)
        self._file_index.error_occurred.connect(
            lambda msg: self._status_label.setText(f"Error: {msg}")
        )

        # Bookmarks
        self._bookmarks_panel.bookmark_activated.connect(self._on_bookmark_activated)

    def _apply_settings(self):
        """Apply current settings to the UI."""
        s = self._settings
        self._preview_pane.setVisible(s.show_preview_pane)
        self._preview_action.setChecked(s.show_preview_pane)
        self._filter_combo.setVisible(s.show_filter_bar)
        self._search_timer.setInterval(s.search_delay_ms)
        self._match_case_action.setChecked(s.default_match_case)
        self._regex_action.setChecked(s.default_regex)

        # Restore column visibility
        if hasattr(s, 'column_visibility') and s.column_visibility:
            for tab in self._tabs:
                tab.results_view.table_view.apply_column_visibility(s.column_visibility)

    # ── Search ─────────────────────────────────────────

    def _on_search_text_changed(self, text: str):
        """Debounced search trigger."""
        # Save query to current tab
        tab = self._current_tab()
        if tab:
            tab.query = text
            # Update tab title
            idx = self._tab_widget.currentIndex()
            title = text[:20] if text.strip() else "Search"
            self._tab_widget.setTabText(idx, title)
        self._search_timer.start()

    def _on_filter_changed(self, index: int):
        """Re-execute search when filter changes."""
        tab = self._current_tab()
        if tab:
            tab.filter_index = index
        self._trigger_search()

    def _trigger_search(self):
        """Trigger a search with the current query and options."""
        self._search_timer.stop()
        self._execute_search()

    def _execute_search(self):
        """Execute the search in a background thread."""
        tab = self._current_tab()
        if not tab:
            return

        # Reset debounce interval back to normal for user-typed searches
        self._search_timer.setInterval(self._settings.search_delay_ms)

        # Cancel any running search for this tab
        if tab.search_worker and tab.search_worker.isRunning():
            tab.search_worker.cancel()
            tab.search_worker.wait(3000)
            if tab.search_worker.isRunning():
                logger.warning("Previous search worker still running, skipping new search")
                return

        query = self._search_input.text().strip()
        use_regex = self._regex_action.isChecked()

        # Validate regex syntax before searching
        if use_regex and query:
            regex_query = query
            # Strip regex: prefix if present
            if regex_query.lower().startswith('regex:'):
                regex_query = regex_query[6:]
            if regex_query:
                try:
                    re.compile(regex_query)
                    self._search_input.setStyleSheet("")
                except re.error as e:
                    self._search_input.setStyleSheet(
                        f"border: 1px solid {MOCHA['red']};"
                    )
                    self._status_label.setText(f"Regex error: {e}")
                    return
        else:
            self._search_input.setStyleSheet("")

        options = SearchOptions(
            match_case=self._match_case_action.isChecked(),
            use_regex=use_regex,
            match_path=self._match_path_action.isChecked(),
            match_whole_word=self._match_whole_action.isChecked(),
            max_results=0,  # Always unlimited — show every indexed object
        )

        active_filter = self._get_active_filter()

        # Merge per-filter hidden paths into exclude list
        if active_filter:
            hidden = self._hidden_paths_manager.get_paths(active_filter.name)
            if hidden:
                merged = list(active_filter.exclude_paths) + hidden
                active_filter = SearchFilter(
                    name=active_filter.name,
                    extensions=active_filter.extensions,
                    min_size=active_filter.min_size,
                    max_size=active_filter.max_size,
                    files_only=active_filter.files_only,
                    folders_only=active_filter.folders_only,
                    macro=active_filter.macro,
                    exclude_paths=merged,
                )

        # Update result highlighting
        tab.results_view.set_highlight(query)

        worker = SearchWorker(
            self._search_engine, query, active_filter, options
        )
        worker.results_ready.connect(self._on_search_results)
        tab.search_worker = worker
        self._search_worker = worker  # Keep reference for backwards compat
        worker.start()

    @pyqtSlot(list)
    def _on_search_results(self, results: list):
        """Handle search results from worker thread."""
        tab = self._current_tab()
        if not tab:
            return

        logger.debug(f"Search returned {len(results)} results")
        tab.results_view.set_results(results)
        count = len(results)
        self._result_count_label.setText(f"{count:,} object{'s' if count != 1 else ''}")

        # Update tab title with result count
        idx = self._tab_widget.currentIndex()
        query = self._search_input.text().strip()
        tab_label = query[:20] if query else "Search"
        self._tab_widget.setTabText(idx, f"{tab_label} ({count:,})")

        # Update window title like Everything
        if query:
            self.setWindowTitle(f"{query} - {count:,} objects - {APP_TITLE}")
            # Save to search history
            from core.cache import add_search_history
            add_search_history(query, count)
            # Refresh autocomplete
            self._refresh_search_history()
        else:
            self.setWindowTitle(f"{count:,} objects - {APP_TITLE}")

    def _refresh_search_history(self):
        """Refresh the search history autocomplete list."""
        from core.cache import get_search_history
        try:
            history = get_search_history(limit=50)
            self._history_model.setStringList(history)
        except Exception:
            pass

    def _clear_search_history(self):
        """Clear all search history."""
        from core.cache import clear_search_history
        clear_search_history()
        self._history_model.setStringList([])
        self._status_label.setText("Search history cleared")

    # ── Indexing ───────────────────────────────────────

    def _start_indexing_with_cache(self):
        """Try loading from cache first, fall back to full MFT scan."""
        if self._index_worker and self._index_worker.isRunning():
            return

        drives = self._settings.index_drives if self._settings.index_drives else None
        self._index_worker = IndexWorker(self._file_index, drives, use_cache=True)
        self._index_worker.cache_loaded.connect(self._on_cache_loaded)
        self._index_worker.finished.connect(self._on_index_worker_done)
        self._index_worker.start()

    def _start_indexing(self):
        """Force a full MFT re-index (no cache)."""
        if self._index_worker and self._index_worker.isRunning():
            return

        drives = self._settings.index_drives if self._settings.index_drives else None
        self._index_worker = IndexWorker(self._file_index, drives, use_cache=False)
        self._index_worker.finished.connect(self._on_index_worker_done)
        self._index_worker.start()

    def _on_indexing_started(self):
        self._progress_bar.show()
        self._status_label.setText("Indexing...")
        self._tray.update_tooltip("QuickFind - Indexing...")

    def _on_indexing_progress(self, drive: str, count: int):
        self._status_label.setText(f"Indexing {drive}: ({count:,} records)...")
        self._tray.update_tooltip(f"QuickFind - Indexing {drive}: {count:,} records")

    def _on_indexing_complete(self, stats):
        self._progress_bar.hide()
        self._index_status.setText(
            f"{stats.total_files:,} files, {stats.total_folders:,} folders "
            f"({stats.index_time_ms:,}ms)"
        )
        self._status_label.setText("")

        total = stats.total_files + stats.total_folders
        self._tray.update_tooltip(f"QuickFind - {total:,} entries indexed")

        # Show startup performance metric
        if stats.entries_per_sec > 0:
            self._perf_label.setText(f"{stats.entries_per_sec:,.0f} entries/sec")
        else:
            self._perf_label.setText("")

        # Show non-admin mode indicator
        if not self._file_index.is_admin_mode:
            self._status_label.setText("Running in non-admin mode (os.scandir fallback)")

        self._refresh_status_bar()

        # Load EFU files
        for efu_path in self._settings.efu_files:
            if os.path.exists(efu_path):
                entries = load_efu(efu_path)
                for entry in entries:
                    drive = entry.drive
                    if drive not in self._file_index._entries:
                        self._file_index._entries[drive] = {}
                    self._file_index._entries[drive][entry.frn] = entry
                self._file_index._rebuild_flat_list()

        # Start USN monitoring (no-op if already started by _on_cache_loaded)
        if self._settings.monitor_usn:
            self._file_index.start_monitoring()

        # Run initial search (show all)
        self._trigger_search()

    def _on_cache_loaded(self):
        """Cache loaded — start USN monitoring early so catchup changes get tracked."""
        if self._settings.monitor_usn:
            self._file_index.start_monitoring()

    def _on_index_worker_done(self):
        """Worker finished (either full index or cache+USN catchup)."""
        # Save updated cache after USN catchup
        try:
            self._file_index.save_to_cache()
        except Exception:
            pass
        # Refresh results to pick up any USN changes
        if self._search_input.text().strip() or self._file_index.all_entries:
            self._trigger_search()
        self._refresh_status_bar()

    def _on_index_updated(self, count: int):
        # Debounce: don't re-search on every USN tick
        # Skip if a search is already running — let it finish first
        if self._search_worker and self._search_worker.isRunning():
            return
        if not self._search_timer.isActive():
            self._search_timer.setInterval(5000)
            self._search_timer.start()

    # ── Live Status Bar ───────────────────────────────

    def _refresh_status_bar(self):
        """Update the live status bar with DB stats."""
        from core.cache import db_count, db_size_bytes

        try:
            entry_count = db_count()
            db_size = db_size_bytes()

            if entry_count > 0:
                if db_size >= 1024 * 1024:
                    size_str = f"{db_size / (1024 * 1024):.1f} MB"
                elif db_size >= 1024:
                    size_str = f"{db_size // 1024} KB"
                else:
                    size_str = f"{db_size} B"
                self._db_stats_label.setText(f"DB: {entry_count:,} entries ({size_str})")
            else:
                self._db_stats_label.setText("")

            if self._file_index.stats.last_update:
                self._last_update_label.setText(
                    f"Updated: {self._file_index.stats.last_update.strftime('%H:%M:%S')}"
                )
            else:
                self._last_update_label.setText("")
        except Exception:
            pass

    # ── Results interaction ─────────────────────────────

    def _on_item_activated(self, entry: FileEntry):
        """Open a file/folder when double-clicked or Enter pressed."""
        path = entry.get_path(self._file_index)
        try:
            os.startfile(path)
        except OSError:
            pass

    def _on_open_folder(self, entry: FileEntry):
        """Open containing folder (Ctrl+Enter)."""
        path = entry.get_path(self._file_index)
        folder = os.path.dirname(path) if not entry.is_dir else path
        try:
            os.startfile(folder)
        except OSError:
            pass

    def _on_delete_requested(self, entries):
        """Delete selected entries to recycle bin."""
        from gui.context_menu import recycle_file
        for entry in entries:
            path = entry.get_path(self._file_index)
            recycle_file(path)

    def _on_rename_requested(self, entry: FileEntry):
        """Rename a file (F2). Opens explorer rename dialog."""
        path = entry.get_path(self._file_index)
        try:
            import subprocess
            subprocess.Popen(['explorer', '/select,', path])
        except Exception:
            pass

    def _on_selection_changed(self, entry: Optional[FileEntry]):
        """Update preview pane and status bar on selection."""
        logger.debug(f"Selection changed: {entry.name if entry else None}")
        self._preview_pane.preview_entry(entry)
        if entry:
            path = entry.get_path(self._file_index)
            self._status_label.setText(path)

    def _show_context_menu(self, pos):
        entries = self._results_view.selected_entries()
        if not entries:
            return
        menu = build_context_menu(
            entries, self._file_index, self,
            hide_callback=self._hide_path_from_results
        )
        menu.exec(self._results_view.table_view.viewport().mapToGlobal(pos))

    def _copy_selected_paths(self):
        entries = self._results_view.selected_entries()
        if entries:
            paths = '\n'.join(e.get_path(self._file_index) for e in entries)
            QApplication.clipboard().setText(paths)

    def _copy_selected_names(self):
        entries = self._results_view.selected_entries()
        if entries:
            names = '\n'.join(e.name for e in entries)
            QApplication.clipboard().setText(names)

    def _hide_path_from_results(self, path: str, path_type: str):
        """Hide a file or directory from the current filter's results."""
        active_filter = self._get_active_filter()
        filter_name = active_filter.name if active_filter else "Everything"
        self._hidden_paths_manager.add_path(filter_name, path)
        self._status_label.setText(f"Hidden from {filter_name}: {path}")
        self._trigger_search()

    def _focus_search(self):
        self._search_input.setFocus()
        self._search_input.selectAll()

    # ── Column visibility ────────────────────────────

    def _on_column_visibility_changed(self, visibility: dict):
        """Persist column visibility to settings."""
        self._settings.column_visibility = visibility
        self._settings.save()

    # ── View toggles ───────────────────────────────────

    def _set_view_mode(self, mode: str):
        if mode == 'details':
            self._results_view.show_table_view()
            self._detail_view_action.setChecked(True)
            self._thumb_view_action.setChecked(False)
        else:
            self._results_view.show_thumbnail_view()
            self._detail_view_action.setChecked(False)
            self._thumb_view_action.setChecked(True)

    def _toggle_preview(self, show: bool):
        self._preview_pane.setVisible(show)
        self._settings.show_preview_pane = show

    def _toggle_bookmarks(self, show: bool):
        self._bookmarks_panel.setVisible(show)
        if show:
            self._splitter.setSizes([200, 700, 300 if self._preview_pane.isVisible() else 0])

    def _toggle_status_bar(self, show: bool):
        self._status_bar.setVisible(show)

    # ── Syntax Help ───────────────────────────────────

    def _show_syntax_help(self):
        """Show search syntax help dialog."""
        QMessageBox.information(
            self, "Search Syntax Help",
            f"<pre style='font-family: Consolas, monospace; font-size: 12px;'>"
            f"{SYNTAX_HELP}</pre>"
        )

    # ── Bookmarks ──────────────────────────────────────

    def _add_bookmark(self):
        query = self._search_input.text()
        active = self._get_active_filter()
        filter_name = active.name if active else "Everything"
        self._bookmarks_panel.add_current_search(
            query, filter_name,
            self._match_case_action.isChecked(),
            self._regex_action.isChecked()
        )

    def _on_bookmark_activated(self, bookmark: Bookmark):
        self._search_input.setText(bookmark.query)
        self._match_case_action.setChecked(bookmark.match_case)
        self._regex_action.setChecked(bookmark.use_regex)
        self._trigger_search()

    # ── File operations ────────────────────────────────

    def _new_window(self):
        import subprocess, sys
        subprocess.Popen([sys.executable] + sys.argv)

    def _open_efu(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File List", "",
            "Everything File Lists (*.efu);;All Files (*)"
        )
        if path:
            entries = load_efu(path)
            for entry in entries:
                drive = entry.drive
                if drive not in self._file_index._entries:
                    self._file_index._entries[drive] = {}
                self._file_index._entries[drive][entry.frn] = entry
            self._file_index._rebuild_flat_list()
            self._trigger_search()

    def _export_efu(self):
        from PyQt6.QtWidgets import QFileDialog
        from core.file_list import save_efu

        entries = self._results_view.model.entries
        if not entries:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.efu",
            "Everything File Lists (*.efu);;All Files (*)"
        )
        if path:
            save_efu(entries, path, self._file_index)

    # ── Everything Import ──────────────────────────────

    def _import_from_everything(self):
        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(
            self, "Select folder containing Everything CSV files",
            os.path.expanduser("~"),
        )
        if not folder:
            return

        filters_csv = os.path.join(folder, "Filters.csv")
        bookmarks_csv = os.path.join(folder, "Bookmarks.csv")

        found = []
        if os.path.exists(filters_csv):
            found.append("Filters.csv")
        else:
            filters_csv = None
        if os.path.exists(bookmarks_csv):
            found.append("Bookmarks.csv")
        else:
            bookmarks_csv = None

        if not found:
            self._status_label.setText("No Everything CSV files found in that folder")
            return

        fc, bc = import_everything(filters_csv, bookmarks_csv)

        msg = []
        if fc:
            msg.append(f"{fc} filters")
        if bc:
            msg.append(f"{bc} bookmarks")

        self._status_label.setText(f"Imported {' and '.join(msg)} from Everything")

        # Reload filter combo and bookmarks
        if fc:
            self._build_filter_combo()
        if bc:
            self._bookmark_manager._load()
            self._bookmarks_panel._refresh()

    # ── Filter management ─────────────────────────────

    def _show_manage_filters(self):
        from gui.filters import ManageFiltersDialog, FILTERS_FILE
        import json

        custom_filters = []
        if FILTERS_FILE.exists():
            try:
                with open(FILTERS_FILE, 'r') as f:
                    data = json.load(f)
                for item in data:
                    custom_filters.append(SearchFilter(
                        name=item.get('name', 'Custom'),
                        extensions=item.get('extensions', []),
                        min_size=item.get('min_size', 0),
                        max_size=item.get('max_size', 0),
                        files_only=item.get('files_only', False),
                        folders_only=item.get('folders_only', False),
                        macro=item.get('macro', ''),
                        exclude_paths=item.get('exclude_paths', []),
                    ))
            except Exception:
                pass

        from PyQt6.QtWidgets import QDialog
        dialog = ManageFiltersDialog(custom_filters, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_filters = dialog.get_filters()
            from pathlib import Path
            FILTERS_FILE.parent.mkdir(exist_ok=True)
            data = []
            for f in new_filters:
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
            with open(FILTERS_FILE, 'w') as fp:
                json.dump(data, fp, indent=2)
            self._build_filter_combo()

    # ── Hidden paths management ────────────────────────

    def _show_manage_hidden_paths(self):
        from gui.hidden_paths_dialog import HiddenPathsDialog
        active_filter = self._get_active_filter()
        filter_name = active_filter.name if active_filter else "Everything"
        dialog = HiddenPathsDialog(self._hidden_paths_manager, filter_name, self)
        dialog.exec()
        self._trigger_search()

    # ── Settings ───────────────────────────────────────

    def _show_settings(self):
        dialog = SettingsDialog(self._settings, self)
        dialog.settings_changed.connect(self._on_settings_changed)
        dialog.exec()

    def _on_settings_changed(self, new_settings: Settings):
        self._settings = new_settings
        self._settings.save()
        self._apply_settings()

        # Sync exclude/USN settings to FileIndex
        self._file_index._exclude_hidden = self._settings.exclude_hidden
        self._file_index._exclude_system = self._settings.exclude_system
        self._file_index._usn_poll_interval_ms = self._settings.usn_poll_interval_ms
        self._file_index._rebuild_flat_list()
        self._trigger_search()

    # ── Window management ──────────────────────────────

    def _show_from_tray(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self._search_input.setFocus()
        self._search_input.selectAll()

    def _quit(self):
        # Stop status bar timer
        self._status_refresh_timer.stop()
        # Save cache before shutdown for instant next startup
        try:
            self._file_index.save_to_cache()
        except Exception:
            pass
        self._file_index.shutdown()
        self._tray.stop_hotkey()
        self._tray.hide()
        if self._settings.remember_window_size:
            self._settings.start_maximized = self.isMaximized()
            if not self.isMaximized():
                self._settings.window_width = self.width()
                self._settings.window_height = self.height()
            self._settings.save()
        QApplication.quit()

    def _show_about(self):
        admin_mode = "MFT + USN Journal" if self._file_index.is_admin_mode else "os.scandir (non-admin)"
        QMessageBox.about(
            self, "About QuickFind",
            f"<h3>QuickFind v{VERSION}</h3>"
            f"<p>Lightning-fast file search for Windows.</p>"
            f"<p>Engine: {admin_mode}</p>"
            f"<p style='color: {MOCHA['subtext0']}'>Built with Python + PyQt6</p>"
        )

    def closeEvent(self, event: QCloseEvent):
        if self._settings.close_to_tray and self._tray.isVisible():
            self.hide()
            event.ignore()
        else:
            self._quit()
            event.accept()

    def changeEvent(self, event):
        super().changeEvent(event)
        if (event.type() == event.Type.WindowStateChange and
                self.isMinimized() and self._settings.minimize_to_tray):
            self.hide()
