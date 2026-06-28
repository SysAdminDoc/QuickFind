"""Tests for QuickFind Windows service support."""

import socket
import types
from datetime import datetime

from service.ipc import ServiceStatusServer, query_service_status
from service import windows_service


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_service_status_socket_roundtrip():
    port = _free_port()
    server = ServiceStatusServer(
        lambda: {"state": "monitoring", "entries": 42},
        port=port,
    )
    try:
        server.start()
        status = query_service_status(port=port, timeout=1)
    finally:
        server.stop()

    assert status["ok"] is True
    assert status["state"] == "monitoring"
    assert status["entries"] == 42


def test_build_service_status_payload():
    stats = types.SimpleNamespace(
        total_files=7,
        total_folders=2,
        last_update=datetime(2026, 6, 28, 12, 0, 0),
    )
    index = types.SimpleNamespace(
        stats=stats,
        all_entries=[object(), object()],
        is_admin_mode=True,
    )

    payload = windows_service.build_service_status(
        index,
        "monitoring",
        datetime(2026, 6, 28, 11, 0, 0),
    )

    assert payload["state"] == "monitoring"
    assert payload["entries"] == 2
    assert payload["files"] == 7
    assert payload["folders"] == 2
    assert payload["admin_mode"] is True
    assert payload["last_update"] == "2026-06-28T12:00:00"


def test_install_service_uses_source_script_args(monkeypatch):
    calls = {}

    def fake_install(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr(windows_service.win32serviceutil, "InstallService", fake_install)
    monkeypatch.setattr(windows_service.sys, "argv", ["quickfind.py"])
    monkeypatch.setattr(windows_service.sys, "executable", "python.exe")
    monkeypatch.delattr(windows_service.sys, "frozen", raising=False)

    assert windows_service.install_service() == 0

    assert calls["args"][0] == "service.windows_service.QuickFindWindowsService"
    assert calls["args"][1] == windows_service.SERVICE_NAME
    assert calls["kwargs"]["exeName"] == "python.exe"
    assert "--run-service" in calls["kwargs"]["exeArgs"]


def test_service_command_elevates_before_install(monkeypatch):
    import quickfind

    monkeypatch.setattr(quickfind, "is_admin", lambda: False)
    monkeypatch.setattr(quickfind, "try_elevate", lambda: True)

    assert quickfind._handle_service_command(["quickfind.py", "--install-service"]) is True
