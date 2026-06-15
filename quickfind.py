#!/usr/bin/env python3
"""QuickFind v0.7.0 - Lightning-fast file search for Windows"""

import sys
import os
from pathlib import Path


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


def _bootstrap():
    """Auto-install all dependencies before any imports."""
    required = ['PyQt6']
    import subprocess
    for pkg in required:
        try:
            __import__(pkg.replace('-', '_').split('[')[0])
        except ImportError:
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', pkg,
                '--break-system-packages', '-q'
            ])

_bootstrap()

import ctypes
import logging
import logging.handlers
import traceback
from datetime import datetime

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QFont

# Crash logging
LOG_DIR = Path.home() / '.quickfind'
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / 'quickfind.log'

# Configure root logger with both file and console handlers
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.DEBUG)

# File handler -- detailed debug log
_file_handler = logging.handlers.RotatingFileHandler(
    str(LOG_FILE), encoding='utf-8', maxBytes=5*1024*1024, backupCount=3
)
_file_handler.setLevel(logging.DEBUG)
_file_handler.setFormatter(logging.Formatter(
    '%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
_root_logger.addHandler(_file_handler)

# Console handler -- info and above
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setLevel(logging.INFO)
_console_handler.setFormatter(logging.Formatter(
    '[%(levelname)-5s] %(name)s: %(message)s'
))
_root_logger.addHandler(_console_handler)

logger = logging.getLogger('QuickFind')

VERSION = "0.7.1"
APP_NAME = "QuickFind"


def excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler - log and show messagebox."""
    msg = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical(f"Unhandled exception:\n{msg}")
    try:
        QMessageBox.critical(None, "QuickFind - Fatal Error", msg[:2000])
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = excepthook


def is_admin():
    """Check if running with admin privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def try_elevate() -> bool:
    """Attempt to re-launch as admin. Returns False if user declined or it failed."""
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable,
            ' '.join([f'"{arg}"' for arg in sys.argv]),
            None, 1
        )
        # ShellExecuteW returns > 32 on success
        if result > 32:
            sys.exit(0)
        return False
    except Exception:
        return False


def main():
    admin = is_admin()
    if not admin:
        logger.info("Not running as admin - attempting elevation for MFT access...")
        if not try_elevate():
            logger.warning("UAC declined or elevation failed - running in non-admin mode "
                           "(MFT scanning disabled, using os.scandir fallback)")

    # Hide console window
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

    app = QApplication(sys.argv)

    branding_icon = QIcon(str(_branding_icon_path()))

    app.setWindowIcon(branding_icon)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)

    # Import here after bootstrap
    from gui.theme import apply_theme
    from gui.main_window import MainWindow
    from gui.tray import get_app_icon, generate_ico_file

    apply_theme(app)

    # Generate icon on first run
    generate_ico_file()
    app.setWindowIcon(get_app_icon())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
