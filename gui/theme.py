"""
Catppuccin Mocha dark theme for QuickFind.
Everything-inspired compact, information-dense styling with premium polish.
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

MACCHIATO = {
    'rosewater': '#f4dbd6', 'flamingo': '#f0c6c6', 'pink': '#f5bde6',
    'mauve': '#c6a0f6', 'red': '#ed8796', 'maroon': '#ee99a0',
    'peach': '#f5a97f', 'yellow': '#eed49f', 'green': '#a6da95',
    'teal': '#8bd5ca', 'sky': '#91d7e3', 'sapphire': '#7dc4e4',
    'blue': '#8aadf4', 'lavender': '#b7bdf8', 'text': '#cad3f5',
    'subtext1': '#b8c0e0', 'subtext0': '#a5adcb', 'overlay2': '#939ab7',
    'overlay1': '#8087a2', 'overlay0': '#6e738d', 'surface2': '#5b6078',
    'surface1': '#494d64', 'surface0': '#363a4f', 'base': '#24273a',
    'mantle': '#1e2030', 'crust': '#181926',
}

FRAPPE = {
    'rosewater': '#f2d5cf', 'flamingo': '#eebebe', 'pink': '#f4b8e4',
    'mauve': '#ca9ee6', 'red': '#e78284', 'maroon': '#ea999c',
    'peach': '#ef9f76', 'yellow': '#e5c890', 'green': '#a6d189',
    'teal': '#81c8be', 'sky': '#99d1db', 'sapphire': '#85c1dc',
    'blue': '#8caaee', 'lavender': '#babbf1', 'text': '#c6d0f5',
    'subtext1': '#b5bfe2', 'subtext0': '#a5adce', 'overlay2': '#949cbb',
    'overlay1': '#838ba7', 'overlay0': '#737994', 'surface2': '#626880',
    'surface1': '#51576d', 'surface0': '#414559', 'base': '#303446',
    'mantle': '#292c3c', 'crust': '#232634',
}

LATTE = {
    'rosewater': '#dc8a78', 'flamingo': '#dd7878', 'pink': '#ea76cb',
    'mauve': '#8839ef', 'red': '#d20f39', 'maroon': '#e64553',
    'peach': '#fe640b', 'yellow': '#df8e1d', 'green': '#40a02b',
    'teal': '#179299', 'sky': '#04a5e5', 'sapphire': '#209fb5',
    'blue': '#1e66f5', 'lavender': '#7287fd', 'text': '#4c4f69',
    'subtext1': '#5c5f77', 'subtext0': '#6c6f85', 'overlay2': '#7c7f93',
    'overlay1': '#8c8fa1', 'overlay0': '#9ca0b0', 'surface2': '#acb0be',
    'surface1': '#bcc0cc', 'surface0': '#ccd0da', 'base': '#eff1f5',
    'mantle': '#e6e9ef', 'crust': '#dce0e8',
}

THEME_PACKS = {
    'mocha': dict(MOCHA),
    'macchiato': dict(MACCHIATO),
    'frappe': dict(FRAPPE),
    'latte': dict(LATTE),
}
THEME_LABELS = {
    'mocha': 'Catppuccin Mocha',
    'macchiato': 'Catppuccin Macchiato',
    'frappe': 'Catppuccin Frappe',
    'latte': 'Catppuccin Latte',
}
ACCENT_DIM_BY_THEME = {
    'mocha': '#4a6da7',
    'macchiato': '#4d68a5',
    'frappe': '#5068a1',
    'latte': '#d8e2ff',
}
ACTIVE_THEME = 'mocha'

# Accent color
ACCENT = MOCHA['blue']
ACCENT_HOVER = MOCHA['sapphire']
ACCENT_DIM = '#4a6da7'

def available_themes() -> tuple[tuple[str, str], ...]:
    return tuple((name, THEME_LABELS[name]) for name in THEME_PACKS)


def normalize_theme_name(name: str) -> str:
    return name if isinstance(name, str) and name in THEME_PACKS else 'mocha'


def set_active_theme(name: str) -> str:
    global ACTIVE_THEME, ACCENT, ACCENT_HOVER, ACCENT_DIM, STYLESHEET
    ACTIVE_THEME = normalize_theme_name(name)
    MOCHA.clear()
    MOCHA.update(THEME_PACKS[ACTIVE_THEME])
    ACCENT = MOCHA['blue']
    ACCENT_HOVER = MOCHA.get('sapphire', ACCENT)
    ACCENT_DIM = ACCENT_DIM_BY_THEME.get(ACTIVE_THEME, MOCHA['surface2'])
    STYLESHEET = build_stylesheet()
    return ACTIVE_THEME


def active_theme_name() -> str:
    return ACTIVE_THEME


def build_stylesheet() -> str:
    return f"""
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
    padding: 5px 10px;
    margin: 0;
    border-radius: 3px;
}}
QMenuBar::item:selected {{
    background-color: {MOCHA['surface0']};
}}
QMenu {{
    background-color: {MOCHA['mantle']};
    border: 1px solid {MOCHA['surface0']};
    border-radius: 6px;
    padding: 4px 0;
}}
QMenu::item {{
    padding: 5px 28px 5px 12px;
    margin: 1px 4px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {MOCHA['surface0']};
}}
QMenu::separator {{
    height: 1px;
    background: {MOCHA['surface0']};
    margin: 4px 8px;
}}
QMenu::icon {{
    padding-left: 4px;
}}

/* ── Toolbar ──────────────────────────────────────────── */
QToolBar {{
    background-color: {MOCHA['mantle']};
    border-bottom: 1px solid {MOCHA['surface0']};
    spacing: 2px;
    padding: 2px 4px;
}}
QToolBar::separator {{
    width: 1px;
    background: {MOCHA['surface0']};
    margin: 4px 6px;
}}
QToolButton {{
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 3px 8px;
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
    border-radius: 4px;
    padding: 3px 6px;
    color: {MOCHA['text']};
    font-size: 12px;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled {{
    color: {MOCHA['overlay0']};
    background-color: {MOCHA['mantle']};
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
    padding: 2px 4px;
    border: none;
}}
QTableView::item:selected, QTreeView::item:selected, QListView::item:selected {{
    background-color: {ACCENT_DIM};
    color: {MOCHA['text']};
}}
QTableView::item:hover, QTreeView::item:hover, QListView::item:hover {{
    background-color: {MOCHA['surface0']};
}}
QTableView::item:selected:hover, QTreeView::item:selected:hover {{
    background-color: {ACCENT_DIM};
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
    padding: 4px 8px;
    font-weight: 600;
}}
QHeaderView::section:hover {{
    background-color: {MOCHA['surface0']};
    color: {MOCHA['text']};
}}

/* ── Scrollbars ───────────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
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
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
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
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}

/* ── Status Bar ───────────────────────────────────────── */
QStatusBar {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['subtext0']};
    border-top: 1px solid {MOCHA['surface0']};
    font-size: 11px;
    padding: 0 4px;
    min-height: 20px;
    max-height: 22px;
}}
QStatusBar::item {{
    border: none;
}}

/* ── Splitter ─────────────────────────────────────────── */
QSplitter::handle {{
    background: {MOCHA['surface0']};
}}
QSplitter::handle:hover {{
    background: {MOCHA['surface1']};
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
    padding: 5px 14px;
    margin-right: 1px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QTabBar::tab:selected {{
    background: {MOCHA['base']};
    color: {MOCHA['text']};
    border-bottom: 2px solid {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background: {MOCHA['surface0']};
    color: {MOCHA['subtext1']};
}}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {{
    background-color: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 4px;
    padding: 5px 14px;
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
    border-color: {MOCHA['surface0']};
}}
QPushButton:focus {{
    border-color: {ACCENT};
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
QPushButton[accent="true"]:pressed {{
    background-color: {MOCHA['blue']};
}}

/* ── ComboBox ─────────────────────────────────────────── */
QComboBox {{
    background-color: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 4px;
    padding: 3px 8px;
    color: {MOCHA['text']};
    font-size: 12px;
    min-width: 60px;
}}
QComboBox:hover {{
    border-color: {MOCHA['overlay0']};
}}
QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {MOCHA['subtext0']};
    margin-right: 5px;
}}
QComboBox QAbstractItemView {{
    background-color: {MOCHA['mantle']};
    border: 1px solid {MOCHA['surface0']};
    border-radius: 4px;
    selection-background-color: {ACCENT_DIM};
    outline: none;
    padding: 2px;
}}

/* ── CheckBox / Radio ─────────────────────────────────── */
QCheckBox, QRadioButton {{
    color: {MOCHA['text']};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {MOCHA['surface2']};
    border-radius: 3px;
    background: {MOCHA['surface0']};
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {MOCHA['overlay0']};
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
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 16px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: {MOCHA['subtext1']};
}}

/* ── SpinBox ──────────────────────────────────────────── */
QSpinBox, QDoubleSpinBox {{
    background: {MOCHA['surface0']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 4px;
    padding: 3px 6px;
    color: {MOCHA['text']};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {ACCENT};
}}

/* ── Dialogs ──────────────────────────────────────────── */
QDialog {{
    background-color: {MOCHA['base']};
}}

/* ── Progress Bar ─────────────────────────────────────── */
QProgressBar {{
    background: {MOCHA['surface0']};
    border: none;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

/* ── Tooltip ──────────────────────────────────────────── */
QToolTip {{
    background-color: {MOCHA['surface0']};
    color: {MOCHA['text']};
    border: 1px solid {MOCHA['surface1']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 11px;
}}

/* ── Dock Widget ──────────────────────────────────────── */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}
QDockWidget::title {{
    background: {MOCHA['mantle']};
    padding: 6px 8px;
    border-bottom: 1px solid {MOCHA['surface0']};
}}

/* ── TextEdit / PlainTextEdit ─────────────────────────── */
QTextEdit, QPlainTextEdit {{
    background-color: {MOCHA['mantle']};
    color: {MOCHA['text']};
    border: 1px solid {MOCHA['surface0']};
    border-radius: 4px;
    padding: 6px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 12px;
}}
QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}

/* ── Dialog Buttons ───────────────────────────────────── */
QDialogButtonBox QPushButton {{
    min-width: 80px;
}}

/* ── Filter ComboBox override ─────────────────────────── */
QComboBox#filterCombo {{
    min-width: 100px;
    padding: 3px 8px;
}}
"""

STYLESHEET = build_stylesheet()


def apply_theme(app: QApplication, theme_name: str | None = None):
    """Apply the active QuickFind theme to the application."""
    if theme_name is not None:
        set_active_theme(theme_name)
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
