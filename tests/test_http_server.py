"""Tests for remote HTTP/HTTPS server configuration."""

import base64
import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from core.index import FileEntry
from core.ntfs import FILE_ATTRIBUTE_DIRECTORY
from server.http_server import QuickFindHTTPServer, SearchHandler, _SESSION_COOKIE_NAME
from server.http_server import _coerce_remote_max_results, _openapi_spec, _pwa_manifest
from server.http_server import _query_with_remote_filters
from server.http_server import AuditLog, _hash_pii, _audit


def _handler(headers=None) -> SearchHandler:
    handler = SearchHandler.__new__(SearchHandler)
    handler.headers = headers or {}
    handler.auth_token = "secret"
    handler.session_token = "session"
    handler.use_https = False
    handler.client_address = ("192.0.2.1", 54321)
    handler.send_response = MagicMock()
    handler.send_header = MagicMock()
    handler.end_headers = MagicMock()
    handler.send_error = MagicMock()
    handler.wfile = BytesIO()
    handler.rfile = BytesIO()
    handler.search_engine = MagicMock()
    handler.file_index = MagicMock()
    handler.path = "/"
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


def test_basic_authorization_accepts_token_as_password():
    credentials = base64.b64encode(b"quickfind:secret").decode("ascii")
    handler = _handler({"Authorization": f"Basic {credentials}"})

    assert handler._check_auth() is True


def test_basic_authorization_rejects_invalid_password():
    credentials = base64.b64encode(b"quickfind:wrong").decode("ascii")
    handler = _handler({"Authorization": f"Basic {credentials}"})

    assert handler._check_auth() is False


def test_session_cookie_is_accepted():
    handler = _handler({"Cookie": f"{_SESSION_COOKIE_NAME}=session"})

    assert handler._check_auth() is True


def test_successful_auth_post_sets_same_origin_session_cookie():
    body = b"token=secret"
    handler = _handler({
        "Host": "127.0.0.1:8080",
        "Origin": "http://127.0.0.1:8080",
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


def test_https_auth_cookie_sets_secure_flag():
    handler = _handler()
    handler.use_https = True

    assert handler._session_cookie_header() == (
        f"{_SESSION_COOKIE_NAME}=session; HttpOnly; Path=/; SameSite=Strict; Secure"
    )


def test_auth_post_rejects_cross_origin_submit():
    body = b"token=secret"
    handler = _handler({
        "Host": "quickfind.local:8080",
        "Origin": "https://evil.example",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    })
    handler.rfile = BytesIO(body)

    handler._handle_auth_post()

    handler.send_response.assert_called_once_with(403)
    header_calls = [call.args for call in handler.send_header.call_args_list]
    assert not any(name == "Set-Cookie" for name, _value in header_calls)
    assert json.loads(handler.wfile.getvalue().decode("utf-8"))["error"] == "Cross-origin auth rejected"


def test_auth_post_rejects_cross_origin_referer():
    body = b"token=secret"
    handler = _handler({
        "Host": "quickfind.local:8080",
        "Referer": "http://quickfind.local:8081/login",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": str(len(body)),
    })
    handler.rfile = BytesIO(body)

    handler._handle_auth_post()

    handler.send_response.assert_called_once_with(403)


def test_security_headers_disable_browser_storage_and_referrers():
    handler = _handler()

    handler._send_security_headers()

    handler.send_header.assert_any_call("Cache-Control", "no-store")
    handler.send_header.assert_any_call("Referrer-Policy", "no-referrer")


def test_api_search_omits_wildcard_cors_header():
    handler = _handler()
    handler.search_engine.search.return_value = []

    handler._handle_api_search({"q": ["readme"]})

    header_calls = [call.args for call in handler.send_header.call_args_list]
    assert ("Access-Control-Allow-Origin", "*") not in header_calls
    assert ("Content-Type", "application/json") in header_calls


def test_remote_type_filter_rewrites_query_for_existing_search_engine():
    assert _query_with_remote_filters("report", "files") == "file: report"
    assert _query_with_remote_filters("report", "folders") == "folder: report"
    assert _query_with_remote_filters("report", "all") == "report"


def test_remote_max_results_are_clamped_for_documented_api_bounds():
    assert _coerce_remote_max_results("25") == 25
    assert _coerce_remote_max_results("0") == 1
    assert _coerce_remote_max_results("20000") == 10000
    assert _coerce_remote_max_results("not-a-number") == 1000


def test_result_cards_escape_paths_and_include_badges():
    handler = _handler()
    entry = FileEntry(10, 5, "alpha <report>.txt", "C")
    entry._path = "C:\\docs\\alpha <report>.txt"
    handler.file_index.resolve_parent_path.return_value = "C:\\docs"

    html = handler._build_result_cards([entry])

    assert 'class="result-card"' in html
    assert "alpha &lt;report&gt;.txt" in html
    assert "TXT file" in html
    assert "<tr>" not in html


def test_api_search_returns_card_payload_and_applies_filters():
    handler = _handler()
    folder = FileEntry(11, 5, "Docs", "C", attributes=FILE_ATTRIBUTE_DIRECTORY)
    folder._path = "C:\\Docs"
    handler.search_engine.search.return_value = [folder]
    handler.file_index.resolve_parent_path.return_value = "C:\\"

    handler._handle_api_search({"q": ["docs"], "type": ["folders"], "max": ["25"]})

    handler.search_engine.search.assert_called_once_with("folder: docs", max_results=25)
    body = handler.wfile.getvalue().decode("utf-8")
    payload = json.loads(body)
    assert payload["results"][0]["type"] == "folder"
    assert payload["results"][0]["path"] == "C:\\Docs"
    assert '"cards"' in body
    assert '"rows"' in body
    assert "result-card" in body


def test_openapi_export_documents_search_response_and_auth():
    spec = _openapi_spec()

    assert spec["openapi"] == "3.1.0"
    assert "/api/search" in spec["paths"]
    assert "/openapi.json" in spec["paths"]
    assert "results" in spec["paths"]["/api/search"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    assert "bearerAuth" in spec["components"]["securitySchemes"]
    assert "basicAuth" in spec["components"]["securitySchemes"]
    assert "sessionCookie" in spec["components"]["securitySchemes"]


def test_api_docs_page_links_openapi_export():
    handler = _handler({"Host": "quickfind.local:8080"})

    handler._handle_api_docs()

    body = handler.wfile.getvalue().decode("utf-8")
    assert "QuickFind REST API" in body
    assert "/openapi.json" in body
    assert "quickfind.local:8080/api/search" in body


def test_unauthorized_response_includes_basic_challenge():
    handler = _handler()

    handler._send_unauthorized()

    handler.send_response.assert_called_once_with(401)
    handler.send_header.assert_any_call(
        "WWW-Authenticate",
        'Basic realm="QuickFind", charset="UTF-8"',
    )


def test_audit_log_emits_structured_records():
    records = []
    audit = AuditLog(emitter=records.append)

    rec = audit.auth_failure("10.0.0.1", "/api/search", "GET")

    assert rec["event"] == "auth_failure"
    assert "ts" in rec
    assert rec["endpoint"] == "/api/search"
    assert rec["method"] == "GET"


def test_audit_log_hashes_client_ip():
    records = []
    audit = AuditLog(emitter=records.append)

    audit.auth_failure("192.168.1.100", "/api/search", "GET")

    rec = records[0]
    assert rec["client"] != "192.168.1.100"
    assert len(rec["client"]) == 12


def test_audit_search_records_query_hash_and_count():
    records = []
    audit = AuditLog(emitter=records.append)

    audit.search("10.0.0.1", _hash_pii("budget report 2025"), 42)

    rec = records[0]
    assert rec["event"] == "search"
    assert rec["result_count"] == 42
    assert "budget" not in rec["query_hash"]
    assert "report" not in rec["query_hash"]
    assert "2025" not in rec["query_hash"]


def test_audit_records_never_contain_raw_tokens_or_passwords():
    records = []
    audit = AuditLog(emitter=records.append)

    audit.auth_failure("10.0.0.1", "/auth", "POST")
    audit.rate_limit("10.0.0.1", "/api/search")
    audit.search("10.0.0.1", _hash_pii("secret query"), 5)
    audit.denied_path("10.0.0.1", "/api/search", "outside allowed roots")

    serialized = json.dumps(records)
    assert "10.0.0.1" not in serialized
    assert "secret query" not in serialized


def test_audit_records_never_contain_full_paths():
    records = []
    audit = AuditLog(emitter=records.append)

    audit.denied_path("10.0.0.1", "/api/search", "outside allowed roots")

    rec = records[0]
    assert rec["event"] == "denied_path"
    assert rec["reason"] == "outside allowed roots"
    serialized = json.dumps(rec)
    assert "C:\\" not in serialized
    assert "Users" not in serialized


def test_audit_rate_limit_records_endpoint():
    records = []
    audit = AuditLog(emitter=records.append)

    audit.rate_limit("10.0.0.1", "/api/search")

    rec = records[0]
    assert rec["event"] == "rate_limit"
    assert rec["endpoint"] == "/api/search"


def test_handler_search_emits_audit_record(monkeypatch):
    records = []
    test_audit = AuditLog(emitter=records.append)
    monkeypatch.setattr("server.http_server._audit", test_audit)

    handler = _handler()
    handler.search_engine.search.return_value = []

    handler._handle_api_search({"q": ["readme"]})

    assert len(records) == 1
    assert records[0]["event"] == "search"
    assert records[0]["result_count"] == 0
    serialized = json.dumps(records[0])
    assert "readme" not in serialized


def test_handler_auth_failure_emits_audit_record(monkeypatch):
    records = []
    test_audit = AuditLog(emitter=records.append)
    monkeypatch.setattr("server.http_server._audit", test_audit)

    handler = _handler()
    handler._send_unauthorized("/api/search", "GET")

    assert len(records) == 1
    assert records[0]["event"] == "auth_failure"
    assert records[0]["endpoint"] == "/api/search"


def test_pwa_manifest_includes_app_identity():
    manifest = _pwa_manifest()
    assert manifest["name"] == "QuickFind"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert any(icon["sizes"] == "192x192" for icon in manifest["icons"])


def test_pwa_manifest_endpoint_serves_json():
    handler = _handler()
    handler._handle_pwa_manifest()
    body = handler.wfile.getvalue().decode("utf-8")
    data = json.loads(body)
    assert data["name"] == "QuickFind"
    header_calls = [call.args for call in handler.send_header.call_args_list]
    assert ("Content-Type", "application/manifest+json") in header_calls


def test_service_worker_endpoint_serves_javascript():
    handler = _handler()
    handler._handle_service_worker()
    body = handler.wfile.getvalue().decode("utf-8")
    assert "serviceWorker" in body or "fetch" in body
    header_calls = [call.args for call in handler.send_header.call_args_list]
    assert ("Content-Type", "application/javascript") in header_calls
    assert ("Service-Worker-Allowed", "/") in header_calls


def test_html_template_includes_pwa_manifest_link():
    handler = _handler()
    handler.search_engine.search.return_value = []
    handler._handle_page({})
    body = handler.wfile.getvalue().decode("utf-8")
    assert 'rel="manifest"' in body
    assert "/manifest.json" in body
    assert 'name="theme-color"' in body
