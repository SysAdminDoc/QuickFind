"""Local status socket for the QuickFind indexing service."""

import json
import socket
import socketserver
import threading
from typing import Callable, Optional


SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 47873


class _StatusHandler(socketserver.StreamRequestHandler):
    def handle(self):
        command = self.rfile.readline(256).decode("utf-8", errors="ignore").strip()
        if command != "status":
            self.wfile.write(b'{"ok": false, "error": "unknown command"}\n')
            return
        status_provider = self.server.status_provider
        payload = status_provider()
        payload["ok"] = True
        self.wfile.write((json.dumps(payload, default=str) + "\n").encode("utf-8"))


class _ThreadingStatusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, status_provider):
        super().__init__(server_address, handler_class)
        self.status_provider = status_provider


class ServiceStatusServer:
    def __init__(self, status_provider: Callable[[], dict],
                 host: str = SERVICE_HOST, port: int = SERVICE_PORT):
        self._status_provider = status_provider
        self._host = host
        self._port = port
        self._server: Optional[_ThreadingStatusServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._server is not None:
            return
        self._server = _ThreadingStatusServer(
            (self._host, self._port),
            _StatusHandler,
            self._status_provider,
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="QuickFindServiceStatus",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None


def query_service_status(timeout: float = 0.25,
                         host: str = SERVICE_HOST,
                         port: int = SERVICE_PORT) -> Optional[dict]:
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(b"status\n")
            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        if not chunks:
            return None
        return json.loads(b"".join(chunks).decode("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
