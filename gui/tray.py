"""
System tray icon with global hotkey support.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject

from gui.theme import MOCHA, ACCENT

logger = logging.getLogger('QuickFind.Tray')

# Win32 hotkey constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
VK_SPACE = 0x20
VK_F = 0x46
HOTKEY_ID = 9001

user32 = ctypes.windll.user32
RegisterHotKey = user32.RegisterHotKey
UnregisterHotKey = user32.UnregisterHotKey
PeekMessageW = user32.PeekMessageW
PM_REMOVE = 0x0001

# Icon paths
ASSETS_DIR = Path(__file__).parent.parent / 'assets'
ICO_PATH = ASSETS_DIR / 'quickfind.ico'


class HotkeyListener(QObject):
    """Listens for global hotkey (Ctrl+Shift+F) in a background thread."""
    hotkey_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._registered = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _listen(self):
        """Register hotkey and poll for messages."""
        # Register Ctrl+Shift+F
        result = RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_F)
        if not result:
            logger.warning("Failed to register global hotkey Ctrl+Shift+F")
            return

        self._registered = True
        logger.info("Registered global hotkey: Ctrl+Shift+F")

        msg = wintypes.MSG()
        while self._running:
            if PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, PM_REMOVE):
                if msg.wParam == HOTKEY_ID:
                    self.hotkey_pressed.emit()
            else:
                import time
                time.sleep(0.05)

        if self._registered:
            UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False
            logger.info("Unregistered global hotkey")


def _create_programmatic_icon() -> QIcon:
    """Create a simple tray icon programmatically as fallback."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Circle background
    painter.setBrush(QColor(ACCENT))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)

    # "Q" letter
    painter.setPen(QColor(MOCHA['crust']))
    font = QFont("Segoe UI", 28, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")

    painter.end()
    return QIcon(pixmap)


def get_app_icon() -> QIcon:
    """Get the app icon - .ico file if available, otherwise programmatic."""
    if ICO_PATH.exists():
        icon = QIcon(str(ICO_PATH))
        if not icon.isNull():
            return icon
    return _create_programmatic_icon()


def generate_ico_file():
    """Generate a .ico file from the programmatic icon and save to assets/."""
    ASSETS_DIR.mkdir(exist_ok=True)
    if ICO_PATH.exists():
        return

    # Create multiple sizes for ICO
    sizes = [16, 32, 48, 64, 128, 256]
    pixmaps = []
    for sz in sizes:
        pixmap = QPixmap(sz, sz)
        pixmap.fill(QColor(0, 0, 0, 0))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = max(1, sz // 16)
        painter.setBrush(QColor(ACCENT))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(margin, margin, sz - margin * 2, sz - margin * 2)

        painter.setPen(QColor(MOCHA['crust']))
        font_size = max(8, int(sz * 0.44))
        font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")

        painter.end()
        pixmaps.append(pixmap)

    # Save the largest as a PNG first, then use QIcon to save as ICO
    # PyQt6 doesn't directly write .ico, so save the 256px as PNG
    # and the icon will be loaded from that
    png_path = ASSETS_DIR / 'quickfind.png'
    pixmaps[-1].save(str(png_path), 'PNG')

    # Also try to save as .ico via the pixmap
    icon = QIcon()
    for pm in pixmaps:
        icon.addPixmap(pm)

    # Save the 256x256 version as the .ico (actually a PNG that QIcon can load)
    pixmaps[-1].save(str(ICO_PATH), 'PNG')
    logger.info(f"Generated app icon: {ICO_PATH}")


class SystemTray(QSystemTrayIcon):
    """System tray icon for QuickFind."""

    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(get_app_icon())
        self.setToolTip("QuickFind - File Search")

        self._hotkey = HotkeyListener()
        self._hotkey.hotkey_pressed.connect(self.show_requested)

        self._setup_menu()
        self.activated.connect(self._on_activated)

    def _setup_menu(self):
        menu = QMenu()

        show_action = menu.addAction("Show QuickFind")
        show_action.triggered.connect(self.show_requested)

        menu.addSeparator()

        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_requested)

        self.setContextMenu(menu)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_requested.emit()

    def start_hotkey(self):
        self._hotkey.start()

    def stop_hotkey(self):
        self._hotkey.stop()
