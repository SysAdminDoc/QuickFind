#!/usr/bin/env python3
"""QuickFind - Lightning-fast file search for Windows"""

import sys
import os
import importlib
import multiprocessing
from pathlib import Path


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


import ctypes
import logging
import logging.handlers
import traceback
from datetime import datetime


def _missing_dependency_message(module_name: str) -> str:
    if getattr(sys, "frozen", False):
        return (
            f"QuickFind is missing bundled dependency {module_name}. "
            "Rebuild the executable from an environment where requirements.txt is installed."
        )

    return (
        f"QuickFind requires {module_name}. Install dependencies before running from source:\n"
        "  python -m pip install -r requirements.txt"
    )


def _exit_missing_dependency(module_name: str, error: BaseException) -> None:
    print(_missing_dependency_message(module_name), file=sys.stderr)
    raise SystemExit(1) from error


def _load_qt_modules(import_module=importlib.import_module):
    try:
        widgets = import_module("PyQt6.QtWidgets")
        core = import_module("PyQt6.QtCore")
        gui = import_module("PyQt6.QtGui")
    except ModuleNotFoundError as exc:
        missing = exc.name or "PyQt6"
        if missing == "PyQt6" or missing.startswith("PyQt6."):
            _exit_missing_dependency(missing, exc)
        raise

    return (
        widgets.QApplication,
        widgets.QMessageBox,
        core.Qt,
        core.QTimer,
        gui.QIcon,
        gui.QFont,
    )


QApplication, QMessageBox, Qt, QTimer, QIcon, QFont = _load_qt_modules()

from core.version import APP_NAME, VERSION
from core.localization import set_language
from core.sqlite_compat import fts5_gate_status

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
logger.info("SQLite runtime: %s", fts5_gate_status())


def _handle_service_command(argv: list[str]) -> bool:
    service_commands = {
        "--install-service": "install_service",
        "--remove-service": "remove_service",
        "--start-service": "start_service",
        "--stop-service": "stop_service",
        "--run-service": "run_service_dispatcher",
        "--service-foreground": "run_foreground_service",
    }
    command = next((arg for arg in argv[1:] if arg in service_commands), None)
    if command is None:
        return False

    admin_commands = {
        "--install-service", "--remove-service", "--start-service", "--stop-service",
    }
    if command in admin_commands and not is_admin():
        logger.info("Service command requires admin rights - attempting elevation...")
        if try_elevate():
            return True

    from service import windows_service
    handler = getattr(windows_service, service_commands[command])
    sys.exit(handler())


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
    if _handle_service_command(sys.argv):
        return

    admin = is_admin() if sys.platform == "win32" else False
    if sys.platform == "win32" and not admin:
        logger.info("Not running as admin - attempting elevation for MFT access...")
        if not try_elevate():
            logger.warning("UAC declined or elevation failed - running in non-admin mode "
                           "(MFT scanning disabled, using os.scandir fallback)")
    elif sys.platform != "win32":
        logger.info("Running cross-platform index engine for %s", sys.platform)

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
    from gui.settings_dialog import Settings
    from gui.theme import apply_theme, set_active_theme
    startup_settings = Settings.load()
    set_active_theme(startup_settings.theme_name)
    set_language(startup_settings.language)
    apply_theme(app)

    from gui.main_window import MainWindow
    from gui.tray import get_app_icon, generate_ico_file

    # Generate icon on first run
    generate_ico_file()
    app.setWindowIcon(get_app_icon())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
