"""
System tray icon with global hotkey support and proper .ico generation.
"""

import ctypes
import ctypes.wintypes as wintypes
import logging
import struct
import sys
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction, QImage
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QBuffer, QIODevice

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

if sys.platform == "win32":
    user32 = ctypes.windll.user32
    RegisterHotKey = user32.RegisterHotKey
    UnregisterHotKey = user32.UnregisterHotKey
    PeekMessageW = user32.PeekMessageW
else:
    RegisterHotKey = None
    UnregisterHotKey = None
    PeekMessageW = None
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
        if RegisterHotKey is None:
            logger.info("Global hotkey unavailable on this platform")
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


def _render_icon_pixmap(size: int) -> QPixmap:
    """Render the QuickFind 'Q' icon at the given size."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = max(1, size // 16)
    painter.setBrush(QColor(ACCENT))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(margin, margin, size - margin * 2, size - margin * 2)

    painter.setPen(QColor(MOCHA['crust']))
    font_size = max(8, int(size * 0.44))
    font = QFont("Segoe UI", font_size, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Q")

    painter.end()
    return pixmap


def _create_programmatic_icon() -> QIcon:
    """Create a multi-size tray icon programmatically as fallback."""
    icon = QIcon()
    for sz in [16, 32, 48, 64, 128, 256]:
        icon.addPixmap(_render_icon_pixmap(sz))
    return icon


def _pixmap_to_png_bytes(pixmap: QPixmap) -> bytes:
    """Convert a QPixmap to PNG bytes."""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return bytes(buf.data())


def _build_ico_file(sizes: list[int]) -> bytes:
    """
    Build a proper .ico file with real ICO headers.
    Uses PNG-compressed images (supported by Windows Vista+).
    """
    images = []
    for sz in sizes:
        pixmap = _render_icon_pixmap(sz)
        png_data = _pixmap_to_png_bytes(pixmap)
        images.append((sz, png_data))

    # ICO header: reserved(2) + type(2) + count(2)
    num_images = len(images)
    header = struct.pack('<HHH', 0, 1, num_images)

    # Each directory entry is 16 bytes
    dir_entries_size = num_images * 16
    data_offset = 6 + dir_entries_size

    dir_entries = b''
    image_data = b''

    for sz, png_data in images:
        w = 0 if sz >= 256 else sz
        h = 0 if sz >= 256 else sz

        entry = struct.pack('<BBBBHHII',
                            w, h, 0, 0,
                            1, 32,
                            len(png_data),
                            data_offset + len(image_data))
        dir_entries += entry
        image_data += png_data

    return header + dir_entries + image_data


def get_app_icon() -> QIcon:
    """Get the app icon - .ico file if available, otherwise programmatic."""
    if ICO_PATH.exists():
        icon = QIcon(str(ICO_PATH))
        if not icon.isNull():
            return icon
    return _create_programmatic_icon()


def generate_ico_file():
    """Generate a proper .ico file with multi-size images and save to assets/."""
    ASSETS_DIR.mkdir(exist_ok=True)
    if ICO_PATH.exists():
        return

    try:
        ico_data = _build_ico_file([16, 32, 48, 64, 128, 256])
        with open(ICO_PATH, 'wb') as f:
            f.write(ico_data)
        logger.info(f"Generated app icon: {ICO_PATH} ({len(ico_data):,} bytes)")
    except Exception as e:
        logger.warning(f"Failed to generate .ico file: {e}")
        # Fallback: save 256px PNG
        try:
            _render_icon_pixmap(256).save(str(ICO_PATH), 'PNG')
        except Exception:
            pass


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

    def update_tooltip(self, text: str):
        """Update tray tooltip (e.g., with indexing progress)."""
        self.setToolTip(text)
