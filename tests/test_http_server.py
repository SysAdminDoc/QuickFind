"""Tests for remote HTTP/HTTPS server configuration."""

from io import BytesIO
from unittest.mock import MagicMock, patch

from server.http_server import QuickFindHTTPServer, SearchHandler, _SESSION_COOKIE_NAME


def _handler(headers=None) -> SearchHandler:
    handler = SearchHandler.__new__(SearchHandler)
    handler.headers = headers or {}
    handler.auth_token = "secret"
    handler.session_token = "session"
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()
    handler.wfile = BytesIO()
    handler.rfile = BytesIO()
    handler.search_engine = MagicMock()
    handler.file_index = MagicMock()
    return handler


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


def test_query_string_tokens_are_ignored_for_auth():
    handler = _handler()
    handler.path = "/api/search?token=secret"

    assert handler._check_auth() is False


def test_bearer_authorization_is_accepted():
    handler = _handler({"Authorization": "Bearer secret"})

    assert handler._check_auth() is True


def test_session_cookie_is_accepted():
    handler = _handler({"Cookie": f"{_SESSION_COOKIE_NAME}=session"})

    assert handler._check_auth() is True


def test_successful_auth_post_sets_same_origin_session_cookie():
    body = b"token=secret"
    handler = _handler({
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    })
    handler.rfile = BytesIO(body)

    handler._handle_auth_post()

    handler.send_response.assert_called_once_with(303)
    handler.send_header.assert_any_call("Location", "/")
    handler.send_header.assert_any_call(
        "Set-Cookie",
        f"{_SESSION_COOKIE_NAME}=session; HttpOnly; Path=/; SameSite=Strict",
    )


def test_api_search_omits_wildcard_cors_header():
    handler = _handler()
    handler.search_engine.search.return_value = []

    handler._handle_api_search({"q": ["readme"]})

    header_calls = [call.args for call in handler.send_header.call_args_list]
    assert ("Access-Control-Allow-Origin", "*") not in header_calls
    assert ("Content-Type", "application/json") in header_calls
