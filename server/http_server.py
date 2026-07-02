"""
HTTP server for remote web browser access to QuickFind search.
Provides a lightweight web interface for searching the index remotely.
Supports optional Bearer, Basic, and same-origin cookie authentication.
"""

import base64
import binascii
import hashlib
import html
import json
import logging
import os
import secrets
import ssl
import time
import threading
from http.cookies import SimpleCookie
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Any, Callable, Optional
from urllib.parse import urlparse, parse_qs

from core.index import FileIndex
from core.search import SearchEngine, SearchOptions
from core.version import VERSION
from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.HTTPServer')
audit_logger = logging.getLogger('QuickFind.Audit')

_SESSION_COOKIE_NAME = "qf_session"


def _derive_audit_salt() -> bytes:
    """Derive a stable per-machine audit salt from hostname and config directory."""
    import platform
    from pathlib import Path
    seed = f"QuickFind-audit:{platform.node()}:{Path.home()}"
    return hashlib.sha256(seed.encode("utf-8")).digest()[:16]


_AUDIT_SALT = _derive_audit_salt()


def _hash_pii(value: str) -> str:
    return hashlib.sha256(_AUDIT_SALT + value.encode("utf-8")).hexdigest()[:12]


class AuditLog:
    """Privacy-preserving structured audit trail for remote access events."""

    def __init__(self, emitter: Callable[[dict[str, Any]], None] | None = None):
        self._emitter = emitter or self._default_emit

    @staticmethod
    def _default_emit(record: dict[str, Any]) -> None:
        audit_logger.info(json.dumps(record, separators=(",", ":")))

    def _record(self, event: str, **fields: Any) -> dict[str, Any]:
        record = {"ts": time.time(), "event": event, **fields}
        self._emitter(record)
        return record

    def auth_failure(self, client_ip: str, endpoint: str, method: str = "") -> dict[str, Any]:
        return self._record(
            "auth_failure",
            client=_hash_pii(client_ip),
            endpoint=endpoint,
            method=method,
        )

    def rate_limit(self, client_ip: str, endpoint: str) -> dict[str, Any]:
        return self._record(
            "rate_limit",
            client=_hash_pii(client_ip),
            endpoint=endpoint,
        )

    def search(self, client_ip: str, query_hash: str, result_count: int) -> dict[str, Any]:
        return self._record(
            "search",
            client=_hash_pii(client_ip),
            query_hash=query_hash,
            result_count=result_count,
        )

    def denied_path(self, client_ip: str, endpoint: str, reason: str = "") -> dict[str, Any]:
        return self._record(
            "denied_path",
            client=_hash_pii(client_ip),
            endpoint=endpoint,
            reason=reason,
        )


_audit = AuditLog()


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="{accent}">
<title>QuickFind</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {bg};
    color: {text};
    font-family: 'Segoe UI', -apple-system, system-ui, sans-serif;
    min-height: 100vh;
    -webkit-font-smoothing: antialiased;
}}
.header {{
    background: {mantle};
    border-bottom: 1px solid {surface0};
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 10;
}}
.header h1 {{
    font-size: 16px;
    color: {accent};
    font-weight: 600;
    letter-spacing: -0.2px;
    white-space: nowrap;
}}
.search-box {{
    flex: 1;
    max-width: 640px;
    background: {surface0};
    border: 1.5px solid {surface1};
    border-radius: 8px;
    padding: 9px 16px;
    color: {text};
    font-size: 14px;
    outline: none;
    transition: border-color 0.15s ease;
}}
.search-box:focus {{ border-color: {accent}; }}
.search-box::placeholder {{ color: {overlay0}; }}
.controls {{
    display: flex;
    align-items: center;
    gap: 8px;
}}
select, .max-input {{
    background: {surface0};
    border: 1px solid {surface1};
    border-radius: 6px;
    color: {text};
    font-size: 13px;
    padding: 8px 10px;
}}
.max-input {{ width: 86px; }}
.meta-bar {{
    color: {subtext0};
    font-size: 12px;
    padding: 6px 24px;
    background: {mantle};
    border-bottom: 1px solid {surface0};
    display: flex;
    align-items: center;
    gap: 12px;
}}
.results {{
    display: grid;
    gap: 8px;
    padding: 12px 16px 24px;
}}
.result-card {{
    background: {surface0};
    border: 1px solid {surface1};
    border-radius: 8px;
    padding: 10px 12px;
}}
.result-title {{
    color: {text};
    font-size: 14px;
    font-weight: 600;
    overflow-wrap: anywhere;
}}
.result-path {{
    color: {subtext0};
    font-size: 12px;
    margin-top: 4px;
    overflow-wrap: anywhere;
}}
.result-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 8px;
    color: {overlay0};
    font-size: 11px;
}}
.badge {{
    border: 1px solid {surface1};
    border-radius: 6px;
    padding: 2px 7px;
    color: {subtext0};
}}
.empty {{ padding: 48px 24px; text-align: center; color: {overlay0}; font-size: 14px; }}
</style>
</head>
<body>
<div class="header">
    <h1>QuickFind</h1>
    <input class="search-box" type="text" id="search" placeholder="Search files and folders…"
           value="{query}" autofocus aria-label="Search">
    <div class="controls" aria-label="Filters">
        <select id="typeFilter" aria-label="Result type filter">
            <option value="all" {type_all}>All</option>
            <option value="files" {type_files}>Files</option>
            <option value="folders" {type_folders}>Folders</option>
        </select>
        <input class="max-input" id="maxResults" type="number" min="1" max="10000"
               value="{max_results}" aria-label="Maximum results">
    </div>
</div>
<div class="meta-bar" id="count">{count} results</div>
<main class="results" id="results">{cards}</main>
<script>
let timer;
const search = document.getElementById('search');
const countEl = document.getElementById('count');
const typeFilter = document.getElementById('typeFilter');
const maxResults = document.getElementById('maxResults');
function runSearch() {{
    clearTimeout(timer);
    countEl.textContent = 'Searching…';
    timer = setTimeout(() => {{
        const params = new URLSearchParams({{
            q: search.value,
            type: typeFilter.value,
            max: maxResults.value
        }});
        fetch('/api/search?' + params, {{ credentials: 'same-origin' }})
            .then(r => {{
                if (r.status === 401) {{ window.location.reload(); throw new Error('Session expired'); }}
                if (r.status === 429) {{ throw new Error('Too many requests — slow down'); }}
                if (!r.ok) {{ throw new Error('Search failed'); }}
                return r.json();
            }})
            .then(data => {{
                const n = data.count;
                countEl.textContent = n + ' result' + (n !== 1 ? 's' : '');
                document.getElementById('results').innerHTML = data.cards;
            }})
            .catch(err => {{ countEl.textContent = err.message || 'Search failed'; }});
    }}, 200);
}}
search.addEventListener('input', runSearch);
typeFilter.addEventListener('change', runSearch);
maxResults.addEventListener('change', runSearch);
search.select();
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {{}});
</script>
</body>
</html>"""


LOGIN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuickFind Login</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {bg};
    color: {text};
    font-family: 'Segoe UI', -apple-system, system-ui, sans-serif;
    min-height: 100vh;
    display: grid;
    place-items: center;
}}
form {{
    width: min(360px, calc(100vw - 32px));
    display: grid;
    gap: 12px;
}}
h1 {{ color: {accent}; font-size: 18px; font-weight: 600; }}
input {{
    background: {surface0};
    border: 1.5px solid {surface1};
    border-radius: 8px;
    color: {text};
    font-size: 14px;
    padding: 10px 12px;
}}
button {{
    background: {accent};
    border: 0;
    border-radius: 8px;
    color: {bg};
    cursor: pointer;
    font-weight: 700;
    padding: 10px 12px;
}}
.error {{ color: {red}; min-height: 18px; font-size: 13px; }}
</style>
</head>
<body>
<form method="post" action="/auth">
    <h1>QuickFind</h1>
    <input name="token" type="password" autocomplete="current-password"
           placeholder="Auth token" aria-label="Auth token" autofocus>
    <button type="submit">Sign in</button>
    <div class="error">{error}</div>
</form>
</body>
</html>"""


API_DOCS_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuickFind API</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {bg};
    color: {text};
    font-family: 'Segoe UI', -apple-system, system-ui, sans-serif;
    line-height: 1.5;
    min-height: 100vh;
    padding: 28px;
}}
main {{ max-width: 880px; margin: 0 auto; display: grid; gap: 20px; }}
h1 {{ color: {accent}; font-size: 24px; font-weight: 650; }}
h2 {{ color: {text}; font-size: 17px; margin-bottom: 8px; }}
p, li {{ color: {subtext0}; font-size: 14px; }}
a {{ color: {accent}; }}
section {{
    border: 1px solid {surface1};
    border-radius: 8px;
    padding: 16px;
    background: {surface0};
}}
code, pre {{
    background: {surface0};
    border: 1px solid {surface1};
    border-radius: 6px;
    color: {text};
    font-family: Consolas, 'Cascadia Code', monospace;
}}
code {{ padding: 1px 5px; }}
pre {{ overflow-x: auto; padding: 12px; font-size: 12px; }}
ul {{ display: grid; gap: 6px; padding-left: 18px; }}
</style>
</head>
<body>
<main>
    <h1>QuickFind REST API</h1>
    <section>
        <h2>Authentication</h2>
        <p>When an auth token is configured, use one of: <code>Authorization: Bearer &lt;token&gt;</code>, HTTP Basic auth with the token as the password, or the browser session cookie created by <code>POST /auth</code>.</p>
    </section>
    <section>
        <h2>Search</h2>
        <p><code>GET /api/search</code> searches the active index and returns structured results plus the HTML cards used by the web UI.</p>
        <ul>
            <li><code>q</code>: search query using QuickFind syntax.</li>
            <li><code>type</code>: <code>all</code>, <code>files</code>, or <code>folders</code>.</li>
            <li><code>max</code>: result cap from 1 to 10000; defaults to 1000.</li>
        </ul>
        <pre>curl -H "Authorization: Bearer &lt;token&gt;" "{base_url}/api/search?q=report&type=files&max=25"</pre>
    </section>
    <section>
        <h2>OpenAPI</h2>
        <p>The machine-readable OpenAPI 3.1 export is available at <a href="/openapi.json">/openapi.json</a>.</p>
    </section>
</main>
</body>
</html>"""


def _format_size(size):
    if size < 0: return ""
    if size < 1024: return f"{size} B"
    if size < 1048576: return f"{size/1024:.1f} KB"
    if size < 1073741824: return f"{size/1048576:.1f} MB"
    return f"{size/1073741824:.2f} GB"


def _query_with_remote_filters(query: str, type_filter: str) -> str:
    clean_query = (query or "").strip()
    if type_filter == "files":
        return f"file: {clean_query}".strip()
    if type_filter == "folders":
        return f"folder: {clean_query}".strip()
    return clean_query


def _coerce_remote_max_results(value: str | int | None, default: int = 1000) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, 10000))


def _pwa_manifest() -> dict:
    return {
        "name": "QuickFind",
        "short_name": "QuickFind",
        "description": "Lightning-fast file search",
        "start_url": "/",
        "display": "standalone",
        "background_color": MOCHA['base'],
        "theme_color": MOCHA['blue'],
        "icons": [
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }


def _pwa_icon_svg() -> str:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
        '<rect width="512" height="512" rx="96" fill="#1e1e2e"/>'
        '<circle cx="220" cy="220" r="100" fill="none" stroke="#89b4fa" stroke-width="32"/>'
        '<line x1="290" y1="290" x2="400" y2="400" stroke="#89b4fa" stroke-width="32" stroke-linecap="round"/>'
        '</svg>'
    )


_SERVICE_WORKER_JS = """
self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;
  event.respondWith(
    fetch(event.request).catch(() =>
      new Response(
        '<html><body style="background:#1e1e2e;color:#cdd6f4;font-family:sans-serif;padding:48px;text-align:center">'
        + '<h1>QuickFind Offline</h1><p>The search server is not reachable.</p></body></html>',
        { headers: { 'Content-Type': 'text/html' }, status: 503 }
      )
    )
  );
});
"""


def _openapi_spec() -> dict:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "QuickFind Remote API",
            "version": VERSION,
            "description": "Read-only search API for the active QuickFind index.",
        },
        "servers": [{"url": "/"}],
        "paths": {
            "/api/search": {
                "get": {
                    "summary": "Search indexed files and folders",
                    "description": (
                        "Returns structured result metadata plus the HTML cards used "
                        "by the built-in read-only web UI."
                    ),
                    "security": [
                        {"bearerAuth": []},
                        {"basicAuth": []},
                        {"sessionCookie": []},
                        {},
                    ],
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "schema": {"type": "string", "default": ""},
                            "description": "QuickFind search query.",
                        },
                        {
                            "name": "type",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": ["all", "files", "folders"],
                                "default": "all",
                            },
                            "description": "Optional file/folder filter.",
                        },
                        {
                            "name": "max",
                            "in": "query",
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10000,
                                "default": 1000,
                            },
                            "description": "Maximum number of results to return.",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "Search results.",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["count", "results", "cards", "rows"],
                                        "properties": {
                                            "count": {"type": "integer", "minimum": 0},
                                            "results": {
                                                "type": "array",
                                                "items": {"$ref": "#/components/schemas/SearchResult"},
                                            },
                                            "cards": {
                                                "type": "string",
                                                "description": "Escaped HTML result cards for the built-in UI.",
                                            },
                                            "rows": {
                                                "type": "string",
                                                "deprecated": True,
                                                "description": "Backward-compatible alias for cards.",
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                        "429": {"$ref": "#/components/responses/TooManyRequests"},
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "Export the OpenAPI document",
                    "security": [
                        {"bearerAuth": []},
                        {"basicAuth": []},
                        {"sessionCookie": []},
                        {},
                    ],
                    "responses": {
                        "200": {
                            "description": "OpenAPI 3.1 document.",
                            "content": {"application/json": {"schema": {"type": "object"}}},
                        },
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                        "429": {"$ref": "#/components/responses/TooManyRequests"},
                    },
                }
            },
            "/api/docs": {
                "get": {
                    "summary": "Serve the human-readable API documentation",
                    "security": [
                        {"bearerAuth": []},
                        {"basicAuth": []},
                        {"sessionCookie": []},
                        {},
                    ],
                    "responses": {
                        "200": {"description": "HTML API documentation."},
                        "401": {"$ref": "#/components/responses/Unauthorized"},
                        "429": {"$ref": "#/components/responses/TooManyRequests"},
                    },
                }
            },
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer"},
                "basicAuth": {"type": "http", "scheme": "basic"},
                "sessionCookie": {
                    "type": "apiKey",
                    "in": "cookie",
                    "name": _SESSION_COOKIE_NAME,
                },
            },
            "responses": {
                "Unauthorized": {
                    "description": "Authentication failed or is required.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    },
                },
                "TooManyRequests": {
                    "description": "Rate limit exceeded.",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    },
                },
            },
            "schemas": {
                "Error": {
                    "type": "object",
                    "required": ["error"],
                    "properties": {"error": {"type": "string"}},
                },
                "SearchResult": {
                    "type": "object",
                    "required": ["name", "path", "parent_path", "type", "kind", "is_dir"],
                    "properties": {
                        "name": {"type": "string"},
                        "path": {"type": "string", "description": "Full resolved path."},
                        "parent_path": {"type": "string"},
                        "drive": {"type": "string"},
                        "type": {"type": "string", "enum": ["file", "folder"]},
                        "kind": {"type": "string"},
                        "extension": {"type": "string"},
                        "is_dir": {"type": "boolean"},
                        "size_bytes": {"type": ["integer", "null"], "minimum": 0},
                        "size": {"type": "string"},
                        "date_modified": {"type": ["string", "null"], "format": "date-time"},
                        "date_modified_display": {"type": "string"},
                    },
                },
            },
        },
    }


class _RateLimiter:
    WINDOW = 60
    MAX_REQUESTS = 60
    _CLEANUP_INTERVAL = 300

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}
        self._last_cleanup = 0.0

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if now - self._last_cleanup > self._CLEANUP_INTERVAL:
                cutoff = now - self.WINDOW
                self._hits = {
                    k: [t for t in v if t > cutoff]
                    for k, v in self._hits.items()
                    if any(t > cutoff for t in v)
                }
                self._last_cleanup = now
            cutoff = now - self.WINDOW
            timestamps = [t for t in self._hits.get(ip, []) if t > cutoff]
            if len(timestamps) >= self.MAX_REQUESTS:
                self._hits[ip] = timestamps
                return False
            timestamps.append(now)
            self._hits[ip] = timestamps
            return True


_rate_limiter = _RateLimiter()


class SearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for search API."""

    file_index: FileIndex = None
    search_engine: SearchEngine = None
    auth_token: str = ""
    session_token: str = ""  # legacy single-token (tests/back-compat); prod uses _sessions
    use_https: bool = False
    shared_config = None  # Optional server.acl.SharedServerConfig
    SESSION_TTL_SECONDS: int = 3600
    _sessions: dict = {}  # per-client session token -> expiry epoch
    _sessions_lock = threading.Lock()

    def log_message(self, format, *args):
        logger.debug(format % args)

    def _presented_token(self) -> str:
        """Return the raw Bearer/Basic token the client presented, if any."""
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:]
        if auth_header.startswith('Basic '):
            return self._basic_auth_password(auth_header[6:])
        return ''

    def _resolve_token_acl(self):
        """Resolve the presented token to its ACL when shared mode is enabled."""
        config = self.shared_config
        if config is None or not getattr(config, "enabled", False):
            return None
        token = self._presented_token()
        return config.acl_for_token(token) if token else None

    def _apply_acl(self, payloads):
        """Filter result payloads by the request's token ACL (shared mode only)."""
        acl = self._resolve_token_acl()
        if acl is None:
            return payloads
        from server.acl import filter_results_by_acl
        outcome = filter_results_by_acl(payloads, acl)
        if outcome.denied_count:
            _audit.denied_path(
                self.client_address[0],
                self.path,
                reason=f"{outcome.denied_count} results outside token roots",
            )
        return outcome.allowed

    def _check_auth(self) -> bool:
        """Validate token if authentication is enabled."""
        config = self.shared_config
        shared_enabled = config is not None and getattr(config, "enabled", False)
        if not self.auth_token and not shared_enabled:
            return True

        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            request_token = auth_header[7:]
            if self.auth_token and secrets.compare_digest(request_token, self.auth_token):
                return True
            if shared_enabled and config.acl_for_token(request_token) is not None:
                return True

        if auth_header.startswith('Basic '):
            password = self._basic_auth_password(auth_header[6:])
            if password and self.auth_token and secrets.compare_digest(password, self.auth_token):
                return True
            if password and shared_enabled and config.acl_for_token(password) is not None:
                return True

        return self._session_valid(self._session_cookie_value())

    def _create_session(self) -> str:
        """Mint a per-client session token with a bounded lifetime."""
        token = secrets.token_urlsafe(32)
        with self._sessions_lock:
            self._prune_sessions_locked()
            self._sessions[token] = time.time() + self.SESSION_TTL_SECONDS
        return token

    def _prune_sessions_locked(self):
        now = time.time()
        for expired in [t for t, exp in self._sessions.items() if exp <= now]:
            self._sessions.pop(expired, None)

    def _session_valid(self, token: str) -> bool:
        if not token:
            return False
        # Legacy single-token path (used by tests / back-compat; unset in prod).
        if self.session_token and secrets.compare_digest(token, self.session_token):
            return True
        with self._sessions_lock:
            expiry = self._sessions.get(token)
            if expiry is None:
                return False
            if expiry <= time.time():
                self._sessions.pop(token, None)
                return False
            return True

    def _clear_session(self, token: str):
        if token:
            with self._sessions_lock:
                self._sessions.pop(token, None)

    def _basic_auth_password(self, encoded_credentials: str) -> str:
        try:
            decoded = base64.b64decode(encoded_credentials, validate=True).decode(
                'utf-8',
                errors='strict',
            )
        except (binascii.Error, UnicodeDecodeError):
            return ''
        _username, sep, password = decoded.partition(':')
        return password if sep else ''

    def _session_cookie_value(self) -> str:
        raw_cookie = self.headers.get('Cookie', '')
        if not raw_cookie:
            return ''
        try:
            cookie = SimpleCookie()
            cookie.load(raw_cookie)
            morsel = cookie.get(_SESSION_COOKIE_NAME)
            return morsel.value if morsel else ''
        except Exception:
            return ''

    def _session_cookie_header(self, token: str | None = None) -> str:
        value = token if token is not None else self.session_token
        parts = [
            f"{_SESSION_COOKIE_NAME}={value}",
            "HttpOnly",
            "Path=/",
            "SameSite=Strict",
            f"Max-Age={self.SESSION_TTL_SECONDS}",
        ]
        if self.use_https:
            parts.append("Secure")
        return "; ".join(parts)

    def _expired_cookie_header(self) -> str:
        parts = [
            f"{_SESSION_COOKIE_NAME}=",
            "HttpOnly",
            "Path=/",
            "SameSite=Strict",
            "Max-Age=0",
        ]
        if self.use_https:
            parts.append("Secure")
        return "; ".join(parts)

    def _send_security_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; worker-src 'self'; img-src 'self' data:")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        if self.use_https:
            self.send_header('Strict-Transport-Security', 'max-age=31536000')

    def _send_unauthorized(self, endpoint: str = "", method: str = ""):
        _audit.auth_failure(self.client_address[0], endpoint or self.path, method)
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        if self.auth_token:
            self.send_header('WWW-Authenticate', 'Basic realm="QuickFind", charset="UTF-8"')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))

    def do_GET(self):
        client_ip = self.client_address[0]
        if not _rate_limiter.allow(client_ip):
            _audit.rate_limit(client_ip, self.path)
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests'}).encode('utf-8'))
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        # PWA shell assets carry no sensitive data and must load without a
        # session: the browser fetches the manifest credential-less, and the
        # service worker registers before login, so gating them breaks install.
        if parsed.path == '/manifest.json':
            self._handle_pwa_manifest()
            return
        elif parsed.path == '/icon.svg':
            self._handle_pwa_icon()
            return
        elif parsed.path == '/sw.js':
            self._handle_service_worker()
            return

        if not self._check_auth():
            if parsed.path == '/' or parsed.path == '':
                self._handle_login_page()
            else:
                self._send_unauthorized(parsed.path, "GET")
            return

        if parsed.path == '/api/search':
            self._handle_api_search(params)
        elif parsed.path == '/openapi.json':
            self._handle_openapi_spec()
        elif parsed.path in ('/api/docs', '/docs'):
            self._handle_api_docs()
        elif parsed.path == '/' or parsed.path == '':
            self._handle_page(params)
        else:
            self.send_error(404)

    def do_POST(self):
        client_ip = self.client_address[0]
        if not _rate_limiter.allow(client_ip):
            _audit.rate_limit(client_ip, self.path)
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests'}).encode('utf-8'))
            return

        parsed = urlparse(self.path)
        if parsed.path == '/logout':
            self._handle_logout()
            return
        if parsed.path != '/auth':
            self.send_error(404)
            return
        self._handle_auth_post()

    def _handle_logout(self):
        """Invalidate this client's session and clear its cookie."""
        self._clear_session(self._session_cookie_value())
        self.send_response(303)
        self.send_header('Location', '/')
        self.send_header('Set-Cookie', self._expired_cookie_header())
        self._send_security_headers()
        self.end_headers()

    def _handle_auth_post(self):
        if not self.auth_token:
            self.send_error(404)
            return
        if not self._origin_or_referer_allowed():
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self._send_security_headers()
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Cross-origin auth rejected'}).encode('utf-8'))
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if length < 0 or length > 4096:
            self.send_response(413)
            self.end_headers()
            return

        body = self.rfile.read(length).decode('utf-8', errors='replace')
        submitted_token = ''
        content_type = self.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            try:
                payload = json.loads(body)
                submitted_token = str(payload.get('token', ''))
            except json.JSONDecodeError:
                submitted_token = ''
        else:
            submitted_token = parse_qs(body).get('token', [''])[0]

        if secrets.compare_digest(submitted_token, self.auth_token):
            token = self._create_session()
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', self._session_cookie_header(token))
            self._send_security_headers()
            self.end_headers()
            return

        _audit.auth_failure(self.client_address[0], "/auth", "POST")
        self._handle_login_page(error="Invalid token", status=401)

    def _origin_or_referer_allowed(self) -> bool:
        expected = self._request_origin()
        checked = False
        for header in ('Origin', 'Referer'):
            value = self.headers.get(header, '')
            if not value:
                continue
            checked = True
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.netloc:
                return False
            actual = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            if actual != expected:
                return False
        return checked

    def _request_origin(self) -> str:
        host = self.headers.get('Host', '')
        if not host:
            server = getattr(self, 'server', None)
            host, port = getattr(server, 'server_address', ('127.0.0.1', 8080))
            host = f"{host}:{port}"
        scheme = 'https' if self.use_https else 'http'
        return f"{scheme}://{host.lower()}"

    def _handle_api_search(self, params):
        """JSON API for AJAX search."""
        query = params.get('q', [''])[0]
        type_filter = params.get('type', ['all'])[0]
        max_results = _coerce_remote_max_results(params.get('max', ['1000'])[0])

        search_query = _query_with_remote_filters(query, type_filter)
        results = self.search_engine.search(
            search_query, max_results=max_results
        )

        _audit.search(
            self.client_address[0],
            _hash_pii(search_query) if search_query else "",
            len(results),
        )

        result_items = self._apply_acl(self._build_result_payloads(results))
        cards_html = self._build_result_cards_from_payloads(result_items)

        response = json.dumps({
            'count': len(result_items),
            'results': result_items,
            'cards': cards_html,
            'rows': cards_html,
        })

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _handle_page(self, params):
        """Serve the main search page."""
        query = params.get('q', [''])[0]
        type_filter = params.get('type', ['all'])[0]
        max_results = _coerce_remote_max_results(params.get('max', ['1000'])[0])

        search_query = _query_with_remote_filters(query, type_filter)
        results = self.search_engine.search(
            search_query,
            max_results=max_results,
        ) if search_query else []
        page_items = self._apply_acl(self._build_result_payloads(results))
        cards_html = self._build_result_cards_from_payloads(page_items)

        page_html = HTML_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'], mantle=MOCHA['mantle'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            subtext0=MOCHA['subtext0'], overlay0=MOCHA['overlay0'],
            accent=MOCHA['blue'],
            query=html.escape(query, quote=True),
            type_all='selected' if type_filter not in ('files', 'folders') else '',
            type_files='selected' if type_filter == 'files' else '',
            type_folders='selected' if type_filter == 'folders' else '',
            max_results=max_results,
            count=len(page_items),
            cards=cards_html,
        )

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(page_html.encode('utf-8'))

    def _handle_openapi_spec(self):
        response = json.dumps(_openapi_spec(), indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _handle_pwa_manifest(self):
        response = json.dumps(_pwa_manifest(), indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/manifest+json')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _handle_service_worker(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/javascript')
        self.send_header('Service-Worker-Allowed', '/')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(_SERVICE_WORKER_JS.encode('utf-8'))

    def _handle_pwa_icon(self):
        svg = _pwa_icon_svg()
        self.send_response(200)
        self.send_header('Content-Type', 'image/svg+xml')
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(svg.encode('utf-8'))

    def _handle_api_docs(self):
        host = self.headers.get('Host', '127.0.0.1:8080')
        server_socket = getattr(getattr(self, 'server', None), 'socket', None)
        scheme = 'https' if isinstance(server_socket, ssl.SSLSocket) else 'http'
        page_html = API_DOCS_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            subtext0=MOCHA['subtext0'], accent=MOCHA['blue'],
            base_url=f"{scheme}://{html.escape(host, quote=True)}",
        )

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(page_html.encode('utf-8'))

    def _handle_login_page(self, error: str = "", status: int = 200):
        page_html = LOGIN_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            accent=MOCHA['blue'], red=MOCHA['red'],
            error=html.escape(error, quote=True),
        )

        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(page_html.encode('utf-8'))

    def _build_result_payloads(self, results):
        """Build structured JSON-safe result payloads from search results."""
        payloads = []
        # results is already bounded by the search's max_results (coerced to the
        # documented maximum); re-slicing here silently dropped requested rows.
        for entry in results:
            parent_path = self.file_index.resolve_parent_path(entry.drive, entry.parent_frn)
            full_path = entry.get_path(self.file_index)

            size_bytes = None
            size_label = ""
            if not entry.is_dir:
                try:
                    if os.path.exists(full_path):
                        size_bytes = os.path.getsize(full_path)
                        size_label = _format_size(size_bytes)
                    else:
                        size_bytes = 0
                except OSError:
                    size_bytes = None

            date_modified = entry.date_modified.isoformat(timespec='seconds') if entry.date_modified else None
            date_modified_display = entry.date_modified.strftime('%Y-%m-%d %H:%M') if entry.date_modified else ''
            kind = "Folder" if entry.is_dir else (entry.extension.upper() + " file" if entry.extension else "File")

            payloads.append({
                "name": entry.name,
                "path": full_path,
                "parent_path": parent_path,
                "drive": entry.drive,
                "type": "folder" if entry.is_dir else "file",
                "kind": kind,
                "extension": entry.extension,
                "is_dir": bool(entry.is_dir),
                "size_bytes": size_bytes,
                "size": size_label,
                "date_modified": date_modified,
                "date_modified_display": date_modified_display,
            })
        return payloads

    def _build_result_cards_from_payloads(self, payloads):
        """Build read-only result cards from structured result payloads."""
        if not payloads:
            return '<div class="empty">Type a query to search your files</div>'

        cards = []
        for item in payloads:
            name_escaped = html.escape(item["name"], quote=True)
            path_escaped = html.escape(item["parent_path"], quote=True)
            full_path_escaped = html.escape(item["path"], quote=True)
            kind_escaped = html.escape(item["kind"], quote=True)
            size = item["size"]
            dm = item["date_modified_display"]
            size_badge = f'<span class="badge">{html.escape(size)}</span>' if size else ''
            date_badge = f'<span class="badge">{html.escape(dm)}</span>' if dm else ''

            cards.append(
                '<article class="result-card">'
                f'<div class="result-title">{name_escaped}</div>'
                f'<div class="result-path" title="{full_path_escaped}">{path_escaped}</div>'
                '<div class="result-meta">'
                f'<span class="badge">{kind_escaped}</span>{size_badge}{date_badge}'
                '</div></article>'
            )

        return '\n'.join(cards)


class QuickFindHTTPServer:
    """Wrapper to run the HTTP server in a background thread."""

    def __init__(self, file_index: FileIndex, search_engine: SearchEngine,
                 host: str = '127.0.0.1', port: int = 8080, auth_token: str = '',
                 use_https: bool = False, certfile: str = '', keyfile: str = '',
                 shared_config=None):
        self._host = host
        self._port = port
        self._use_https = use_https
        self._certfile = certfile
        self._keyfile = keyfile
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        self._handler_class = type(
            "BoundSearchHandler",
            (SearchHandler,),
            {
                "file_index": file_index,
                "search_engine": search_engine,
                "auth_token": auth_token,
                # Per-client sessions are minted on /auth; no shared token.
                "session_token": "",
                "_sessions": {},
                "use_https": use_https,
                "shared_config": shared_config,
            },
        )

    def start(self):
        """Start the HTTP server in a background thread."""
        try:
            # ThreadingHTTPServer so one slow client (or the per-result stat loop)
            # cannot block every other request on the single accept thread.
            self._server = ThreadingHTTPServer((self._host, self._port), self._handler_class)
            if self._use_https:
                if not self._certfile:
                    raise ValueError("HTTPS requires a TLS certificate file")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(
                    certfile=self._certfile,
                    keyfile=self._keyfile or None,
                )
                self._server.socket = context.wrap_socket(
                    self._server.socket,
                    server_side=True,
                )
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            auth_status = " (auth enabled)" if self._handler_class.auth_token else ""
            logger.info(f"{self.scheme.upper()} server started on {self._host}:{self._port}{auth_status}")
            return True
        except Exception as e:
            if self._server:
                self._server.server_close()
                self._server = None
            logger.error(f"Failed to start {self.scheme.upper()} server: {e}")
            return False

    def stop(self):
        """Stop the HTTP server and release the listening socket."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("HTTP server stopped")

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self._host}:{self._port}"

    @property
    def scheme(self) -> str:
        return "https" if self._use_https else "http"
