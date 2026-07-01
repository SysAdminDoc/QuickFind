"""Mock missing PyQt6 symbols so tests can run without the GUI framework installed."""

import sys
import types
from unittest.mock import MagicMock

_QT_ATTRS = {
    'PyQt6.QtCore': [
        'QObject', 'pyqtSignal', 'QThread', 'QTimer', 'Qt', 'QSize',
        'pyqtSlot', 'QStringListModel', 'QPoint', 'QAbstractTableModel',
        'QModelIndex', 'QSortFilterProxyModel', 'QVariant', 'QFileInfo',
        'QUrl', 'QMimeData', 'QRect', 'QBuffer', 'QIODevice',
    ],
    'PyQt6.QtWidgets': [
        'QApplication', 'QMessageBox', 'QMenu', 'QInputDialog',
        'QMainWindow', 'QWidget', 'QVBoxLayout', 'QHBoxLayout', 'QLineEdit',
        'QSplitter', 'QStatusBar', 'QLabel', 'QMenuBar', 'QComboBox',
        'QProgressBar', 'QTabWidget', 'QTabBar', 'QCompleter', 'QToolTip',
        'QToolButton', 'QButtonGroup',
        'QTableView', 'QTableWidget', 'QTableWidgetItem',
        'QAbstractItemView', 'QHeaderView', 'QListView',
        'QPlainTextEdit', 'QScrollArea', 'QStackedWidget', 'QTextEdit',
        'QStyledItemDelegate', 'QStyle',
        'QFileIconProvider', 'QDialog', 'QFormLayout', 'QCheckBox',
        'QSpinBox', 'QGroupBox', 'QPushButton', 'QDialogButtonBox',
        'QListWidget', 'QListWidgetItem', 'QTreeWidget', 'QTreeWidgetItem',
        'QFileDialog', 'QSystemTrayIcon',
    ],
    'PyQt6.QtGui': [
        'QIcon', 'QPalette', 'QColor', 'QFont', 'QAction',
        'QDesktopServices', 'QPixmap', 'QPainter', 'QImage', 'QDrag',
        'QFontMetrics', 'QPen', 'QKeyEvent', 'QTextDocument',
        'QAbstractTextDocumentLayout', 'QTextCharFormat', 'QTextFormat',
        'QKeySequence', 'QCloseEvent',
    ],
}


try:
    import PyQt6.QtCore  # noqa: F401
    import PyQt6.QtWidgets  # noqa: F401
    import PyQt6.QtGui  # noqa: F401
except (ImportError, ModuleNotFoundError):
    if 'PyQt6' not in sys.modules:
        sys.modules['PyQt6'] = types.ModuleType('PyQt6')

for mod_name, attrs in _QT_ATTRS.items():
    if mod_name not in sys.modules:
        mock = types.ModuleType(mod_name)
        sys.modules[mod_name] = mock

    module = sys.modules[mod_name]
    for attr in attrs:
        if not hasattr(module, attr):
            setattr(module, attr, MagicMock(return_value=MagicMock()) if attr == 'pyqtSignal' else MagicMock)

pyqt6 = sys.modules.get('PyQt6')
if pyqt6 is not None:
    pyqt6.QtCore = sys.modules['PyQt6.QtCore']
    pyqt6.QtWidgets = sys.modules['PyQt6.QtWidgets']
    pyqt6.QtGui = sys.modules['PyQt6.QtGui']
