"""
Catppuccin Mocha dark theme for QuickFind.
Everything-inspired compact, information-dense styling.
"""

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPalette, QColor, QFont
from PyQt6.QtCore import Qt

# Catppuccin Mocha palette
MOCHA = {
    'rosewater': '#f5e0dc',
    'flamingo': '#f2cdcd',
    'pink': '#f5c2e7',
    'mauve': '#cba6f7',
    'red': '#f38ba8',
    'maroon': '#eba0ac',
    'peach': '#fab387',
    'yellow': '#f9e2af',
    'green': '#a6e3a1',
    'teal': '#94e2d5',
    'sky': '#89dceb',
    'sapphire': '#74c7ec',
    'blue': '#89b4fa',
    'lavender': '#b4befe',
    'text': '#cdd6f4',
    'subtext1': '#bac2de',
    'subtext0': '#a6adc8',
    'overlay2': '#9399b2',
    'overlay1': '#7f849c',
    'overlay0': '#6c7086',
    'surface2': '#585b70',
    'surface1': '#45475a',
    'surface0': '#313244',
    'base': '#1e1e2e',
    'mantle': '#181825',
    'crust': '#11111b',
}

# Accent color
ACCENT = MOCHA['blue']
ACCENT_HOVER = MOCHA['sapphire']
ACCENT_DIM = '#4a6da7'

STYLESHEET = f"""
/* ── Global ───────────────────────────────────────────── */
QWidget {{
    background-color: {MOCHA['base']};
    color: {MOCHA['text']};
    font-family: "Segoe UI", sans-serif;
    font-size: 12px;
    selection-background-color: {ACCENT_DIM};
    selection-color: {MOCHA['text']};
}}

/* ── Main Window ──────────────────────────────────────── */
QMainWindow {{
    background-color: {MOCHA['base']};
}}
QMainWindow::separator {{
    background: {MOCHA['surface0']};
    width: 1px;
    height: 1px;
}}

/* ── Menu Bar ─────────────────────────────────────────── */
QMenuBar {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['text']};
    border-bottom: 1px solid {MOCHA['surface0']};
    padding: 0;
    font-size: 12px;
}}
QMenuBar::item {{
    padding: 4px 8px;
    margin: 0;
}}
QMenuBar::item:selected {{
    background-color: {MOCHA['surface0']};
}}
QMenu {{
    background-color: {MOCHA['mantle']};
    border: 1px solid {MOCHA['surface0']};
    padding: 2px 0;
}}
QMenu::item {{
    padding: 4px 24px 4px 8px;
    margin: 0;
}}
QMenu::item:selected {{
    background-color: {MOCHA['surface0']};
}}
QMenu::separator {{
    height: 1px;
    background: {MOCHA['surface0']};
    margin: 2px 0;
}}
QMenu::icon {{
    padding-left: 4px;
}}

/* ── Toolbar ──────────────────────────────────────────── */
QToolBar {{
    background-color: {MOCHA['mantle']};
    border-bottom: 1px solid {MOCHA['surface0']};
    spacing: 2px;
    padding: 1px 2px;
}}
QToolBar::separator {{
    width: 1px;
    background: {MOCHA['surface0']};
    margin: 2px 4px;
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 2px;
    padding: 2px 6px;
    color: {MOCHA['subtext1']};
    font-size: 11px;
}}
QToolButton:hover {{
    background-color: {MOCHA['surface0']};
    color: {MOCHA['text']};
}}
QToolButton:pressed {{
    background-color: {MOCHA['surface1']};
}}
QToolButton:checked {{
    background-color: {ACCENT_DIM};
    color: {MOCHA['text']};
}}

/* ── Search Bar ───────────────────────────────────────── */
QLineEdit {{
    background-color: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 0px;
    padding: 2px 4px;
    color: {MOCHA['text']};
    font-size: 12px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

/* ── Table / Tree / List Views ────────────────────────── */
QTableView, QTreeView, QListView {{
    background-color: {MOCHA['base']};
    alternate-background-color: {MOCHA['mantle']};
    border: none;
    gridline-color: {MOCHA['surface0']};
    outline: none;
    font-size: 12px;
}}
QTableView::item, QTreeView::item, QListView::item {{
    padding: 1px 4px;
    border: none;
}}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background-color: {ACCENT_DIM};
    color: {MOCHA['text']};
}}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{
    background-color: {MOCHA['surface0']};
}}

QHeaderView {{
    background-color: {MOCHA['mantle']};
    border: none;
    font-size: 11px;
}}
QHeaderView::section {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['subtext0']};
    border: none;
    border-right: 1px solid {MOCHA['surface0']};
    border-bottom: 1px solid {MOCHA['surface0']};
    padding: 3px 6px;
    font-weight: 600;
}}
QHeaderView::section:hover {{
    background-color: {MOCHA['surface0']};
    color: {MOCHA['text']};
}}

/* ── Scrollbars ───────────────────────────────────────── */
QScrollBar:vertical {{
    background: {MOCHA['mantle']};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {MOCHA['surface1']};
    min-height: 24px;
    border-radius: 4px;
    margin: 1px;
}}
QScrollBar::handle:vertical:hover {{
    background: {MOCHA['overlay0']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {MOCHA['mantle']};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {MOCHA['surface1']};
    min-width: 24px;
    border-radius: 4px;
    margin: 1px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {MOCHA['overlay0']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Status Bar ───────────────────────────────────────── */
QStatusBar {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['subtext0']};
    border-top: 1px solid {MOCHA['surface0']};
    font-size: 11px;
    padding: 0 4px;
    min-height: 18px;
    max-height: 20px;
}}
QStatusBar::item {{
    border: none;
}}

/* ── Splitter ─────────────────────────────────────────── */
QSplitter::handle {{
    background: {MOCHA['surface0']};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}

/* ── Tab Widget ───────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {MOCHA['surface0']};
    background: {MOCHA['base']};
}}
QTabBar::tab {{
    background: {MOCHA['mantle']};
    color: {MOCHA['subtext0']};
    border: 1px solid {MOCHA['surface0']};
    border-bottom: none;
    padding: 4px 12px;
    margin-right: 1px;
}}
QTabBar::tab:selected {{
    background: {MOCHA['base']};
    color: {MOCHA['text']};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background: {MOCHA['surface0']};
}}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {{
    background-color: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 3px;
    padding: 4px 12px;
    color: {MOCHA['text']};
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: {MOCHA['surface1']};
    border-color: {MOCHA['overlay0']};
}}
QPushButton:pressed {{
    background-color: {MOCHA['surface2']};
}}
QPushButton:disabled {{
    color: {MOCHA['overlay0']};
    background-color: {MOCHA['mantle']};
}}

/* Primary accent button */
QPushButton[accent="true"] {{
    background-color: {ACCENT};
    border: none;
    color: {MOCHA['crust']};
    font-weight: 600;
}}
QPushButton[accent="true"]:hover {{
    background-color: {ACCENT_HOVER};
}}

/* ── ComboBox ─────────────────────────────────────────── */
QComboBox {{
    background-color: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 0px;
    padding: 2px 6px;
    color: {MOCHA['text']};
    font-size: 12px;
    min-width: 60px;
}}
QComboBox:hover {{
    border-color: {MOCHA['overlay0']};
}}
QComboBox::drop-down {{
    border: none;
    width: 16px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {MOCHA['subtext0']};
    margin-right: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {MOCHA['mantle']};
    border: 1px solid {MOCHA['surface0']};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}

/* ── CheckBox / Radio ─────────────────────────────────── */
QCheckBox, QRadioButton {{
    color: {MOCHA['text']};
    spacing: 4px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {MOCHA['surface2']};
    border-radius: 2px;
    background: {MOCHA['surface0']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}

/* ── Group Box ────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {MOCHA['surface0']};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 14px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    color: {MOCHA['subtext1']};
}}

/* ── SpinBox ──────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 0px;
    padding: 2px 6px;
    color: {MOCHA['text']};
}}

/* ── Dialogs ──────────────────────────────────────────── */
QDialog {{
    background-color: {MOCHA['base']};
}}

/* ── Progress Bar ─────────────────────────────────────── */
QProgressBar {{
    background: {MOCHA['surface0']};
    border: none;
    border-radius: 2px;
    height: 4px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 2px;
}}

/* ── Tooltip ──────────────────────────────────────────── */
QToolTip {{
    background-color: {MOCHA['surface0']};
    color: {MOCHA['text']};
    border: 1px solid {MOCHA['surface1']};
    padding: 2px 6px;
    font-size: 11px;
}}

/* ── Dock Widget ──────────────────────────────────────── */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {MOCHA['mantle']};
    padding: 4px;
    border-bottom: 1px solid {MOCHA['surface0']};
}}

/* ── TextEdit / PlainTextEdit ─────────────────────────── */
QTextEdit, QPlainTextEdit {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['text']};
    border: 1px solid {MOCHA['surface0']};
    border-radius: 0px;
    padding: 4px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}}

/* ── Filter ComboBox override ─────────────────────────── */
QComboBox#filterCombo {{
    min-width: 100px;
    padding: 2px 6px;
}}
"""


def apply_theme(app: QApplication):
    """Apply the Catppuccin Mocha theme to the application."""
    app.setStyleSheet(STYLESHEET)

    # Set palette for native dialogs
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(MOCHA['base']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(MOCHA['text']))
    palette.setColor(QPalette.ColorRole.Base, QColor(MOCHA['mantle']))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(MOCHA['surface0']))
    palette.setColor(QPalette.ColorRole.Text, QColor(MOCHA['text']))
    palette.setColor(QPalette.ColorRole.Button, QColor(MOCHA['surface0']))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(MOCHA['text']))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(MOCHA['crust']))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(MOCHA['surface0']))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(MOCHA['text']))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MOCHA['overlay0']))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(palette)

    # Compact font
    font = QFont("Segoe UI", 9)
    app.setFont(font)
