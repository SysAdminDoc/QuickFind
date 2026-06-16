"""Tests for remote HTTP/HTTPS server configuration."""

from unittest.mock import MagicMock, patch

from server.http_server import QuickFindHTTPServer


def test_default_server_url_uses_http_scheme():
    server = QuickFindHTTPServer(MagicMock(), MagicMock(), host="127.0.0.1", port=8080)

    assert server.scheme == "http"
    assert server.url == "http://127.0.0.1:8080"


def test_https_server_wraps_socket_with_tls_context():
    httpd = MagicMock()
    original_socket = httpd.socket
    wrapped_socket = object()

    with (
        patch("server.http_server.HTTPServer", return_value=httpd),
        patch("server.http_server.ssl.SSLContext") as context_cls,
        patch("server.http_server.threading.Thread") as thread_cls,
    ):
        context = context_cls.return_value
        context.wrap_socket.return_value = wrapped_socket

        server = QuickFindHTTPServer(
            MagicMock(),
            MagicMock(),
            host="0.0.0.0",
            port=9443,
            use_https=True,
            certfile="cert.pem",
            keyfile="key.pem",
        )

        assert server.start() is True
        context.load_cert_chain.assert_called_once_with(
            certfile="cert.pem",
            keyfile="key.pem",
        )
        context.wrap_socket.assert_called_once_with(original_socket, server_side=True)
        assert httpd.socket is wrapped_socket
        thread_cls.return_value.start.assert_called_once()
        assert server.scheme == "https"
        assert server.url == "https://0.0.0.0:9443"


def test_https_server_requires_certificate_file():
    httpd = MagicMock()

    with patch("server.http_server.HTTPServer", return_value=httpd):
        server = QuickFindHTTPServer(
            MagicMock(),
            MagicMock(),
            use_https=True,
            certfile="",
        )

        assert server.start() is False
        httpd.server_close.assert_called_once()
