"""Windows service entrypoint for background QuickFind indexing."""

import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import win32event
import win32service
import win32serviceutil
import servicemanager
from PyQt6.QtCore import QCoreApplication, QTimer

from core.index import FileIndex
from service.ipc import ServiceStatusServer


SERVICE_NAME = "QuickFindIndexService"
SERVICE_DISPLAY_NAME = "QuickFind Index Service"
SERVICE_DESCRIPTION = "Maintains the QuickFind file index in the background."

logger = logging.getLogger("QuickFind.Service")


def build_service_status(index: FileIndex, state: str, started_at: datetime) -> dict:
    stats = index.stats
    return {
        "state": state,
        "started_at": started_at.isoformat(timespec="seconds"),
        "entries": len(index.all_entries),
        "files": stats.total_files,
        "folders": stats.total_folders,
        "admin_mode": index.is_admin_mode,
        "last_update": stats.last_update.isoformat(timespec="seconds") if stats.last_update else "",
    }


def run_index_service(stop_event: threading.Event):
    app = QCoreApplication.instance() or QCoreApplication([])
    index = FileIndex()
    state = {"value": "starting"}
    started_at = datetime.now()

    status_server = ServiceStatusServer(
        lambda: build_service_status(index, state["value"], started_at)
    )
    status_server.start()

    def stop_if_requested():
        if stop_event.is_set():
            app.quit()

    timer = QTimer()
    timer.setInterval(1000)
    timer.timeout.connect(stop_if_requested)
    timer.start()

    try:
        state["value"] = "loading-cache"
        if not index.load_from_cache():
            state["value"] = "indexing"
            index.index_all_drives()
            index.save_to_cache()
        else:
            state["value"] = "catching-up"
            index.usn_catchup()
            index.save_to_cache()

        state["value"] = "monitoring"
        index.start_monitoring()
        app.exec()
    finally:
        state["value"] = "stopping"
        try:
            index.save_to_cache()
        except Exception as exc:
            logger.debug(f"Service cache save failed during stop: {exc}")
        index.shutdown()
        status_server.stop()


class QuickFindWindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self._stop_event = threading.Event()
        self._win32_stop_event = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()
        win32event.SetEvent(self._win32_stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{SERVICE_NAME} starting")
        try:
            run_index_service(self._stop_event)
        except Exception as exc:
            servicemanager.LogErrorMsg(f"{SERVICE_NAME} failed: {exc}")
            raise
        finally:
            servicemanager.LogInfoMsg(f"{SERVICE_NAME} stopped")


def install_service() -> int:
    if getattr(sys, "frozen", False):
        exe_name = sys.executable
        exe_args = "--run-service"
    else:
        exe_name = sys.executable
        exe_args = f'"{Path(sys.argv[0]).resolve()}" --run-service'

    win32serviceutil.InstallService(
        "service.windows_service.QuickFindWindowsService",
        SERVICE_NAME,
        SERVICE_DISPLAY_NAME,
        startType=win32service.SERVICE_AUTO_START,
        exeName=exe_name,
        exeArgs=exe_args,
        description=SERVICE_DESCRIPTION,
    )
    return 0


def remove_service() -> int:
    win32serviceutil.RemoveService(SERVICE_NAME)
    return 0


def start_service() -> int:
    win32serviceutil.StartService(SERVICE_NAME)
    return 0


def stop_service() -> int:
    win32serviceutil.StopService(SERVICE_NAME)
    return 0


def run_service_dispatcher() -> int:
    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(QuickFindWindowsService)
    servicemanager.StartServiceCtrlDispatcher()
    return 0


def run_foreground_service() -> int:
    stop_event = threading.Event()
    try:
        run_index_service(stop_event)
    except KeyboardInterrupt:
        stop_event.set()
        time.sleep(0.2)
    return 0
