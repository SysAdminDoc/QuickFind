"""Root conftest — mock PyQt6 if not available, disable pytest-qt."""

import sys
import types
from unittest.mock import MagicMock

try:
    import PyQt6.QtCore
except (ImportError, ModuleNotFoundError):
    for mod_name in ['PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui']:
        if mod_name not in sys.modules:
            mock = types.ModuleType(mod_name)
            mock.__dict__.update({
                'QObject': MagicMock,
                'pyqtSignal': MagicMock(return_value=MagicMock()),
                'QThread': MagicMock,
                'QTimer': MagicMock,
                'Qt': MagicMock(),
                'QApplication': MagicMock,
                'QMessageBox': MagicMock,
                'QIcon': MagicMock,
                'QFont': MagicMock,
                'QMenu': MagicMock,
                'QAction': MagicMock,
                'QDesktopServices': MagicMock,
                'QUrl': MagicMock,
                'QInputDialog': MagicMock,
            })
            sys.modules[mod_name] = mock
    pyqt6 = sys.modules['PyQt6']
    pyqt6.QtCore = sys.modules['PyQt6.QtCore']
    pyqt6.QtWidgets = sys.modules['PyQt6.QtWidgets']
    pyqt6.QtGui = sys.modules['PyQt6.QtGui']
