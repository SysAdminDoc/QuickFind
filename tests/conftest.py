"""Mock PyQt6 so tests can run without the GUI framework installed."""

import sys
import types
from unittest.mock import MagicMock

_QT_MODULES = [
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtWidgets', 'PyQt6.QtGui',
]

for mod_name in _QT_MODULES:
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
