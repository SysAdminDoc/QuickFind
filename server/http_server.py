"""
HTTP server for remote web browser access to QuickFind search.
Provides a lightweight web interface for searching the index remotely.
Supports optional Bearer, Basic, and same-origin cookie authentication.
"""

import base64
import binascii
import html
import json
import logging
import os
import secrets
import ssl
import time
import threading
from http.cookies import SimpleCookie
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional

from core.index import FileIndex
from core.search import SearchEngine, SearchOptions
from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.HTTPServer')

_SESSION_COOKIE_NAME = "qf_session"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
    background: rgba(49,50,68,0.55);
    border: 1px solid {surface0};
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
    border-radius: 999px;
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
            .then(r => r.json())
            .then(data => {{
                const n = data.count;
                countEl.textContent = n + ' result' + (n !== 1 ? 's' : '');
                document.getElementById('results').innerHTML = data.cards;
            }})
            .catch(() => {{ countEl.textContent = 'Search failed'; }});
    }}, 200);
}}
search.addEventListener('input', runSearch);
typeFilter.addEventListener('change', runSearch);
maxResults.addEventListener('change', runSearch);
search.select();
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


def _format_size(size):
    if size <= 0: return ""
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


class _RateLimiter:
    WINDOW = 60
    MAX_REQUESTS = 60

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def allow(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
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
    session_token: str = ""

    def log_message(self, format, *args):
        logger.debug(format % args)

    def _check_auth(self) -> bool:
        """Validate token if authentication is enabled."""
        if not self.auth_token:
            return True

        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            request_token = auth_header[7:]
            if secrets.compare_digest(request_token, self.auth_token):
                return True

        if auth_header.startswith('Basic '):
            password = self._basic_auth_password(auth_header[6:])
            if password and secrets.compare_digest(password, self.auth_token):
                return True

        session_cookie = self._session_cookie_value()
        return bool(
            self.session_token
            and session_cookie
            and secrets.compare_digest(session_cookie, self.session_token)
        )

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

    def _session_cookie_header(self) -> str:
        return f"{_SESSION_COOKIE_NAME}={self.session_token}; HttpOnly; Path=/; SameSite=Strict"

    def _send_security_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
        self.send_header('X-Content-Type-Options', 'nosniff')

    def _send_unauthorized(self):
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
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests'}).encode('utf-8'))
            return

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if not self._check_auth():
            if parsed.path == '/' or parsed.path == '':
                self._handle_login_page()
            else:
                self._send_unauthorized()
            return

        if parsed.path == '/api/search':
            self._handle_api_search(params)
        elif parsed.path == '/' or parsed.path == '':
            self._handle_page(params)
        else:
            self.send_error(404)

    def do_POST(self):
        client_ip = self.client_address[0]
        if not _rate_limiter.allow(client_ip):
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests'}).encode('utf-8'))
            return

        parsed = urlparse(self.path)
        if parsed.path != '/auth':
            self.send_error(404)
            return
        self._handle_auth_post()

    def _handle_auth_post(self):
        if not self.auth_token:
            self.send_error(404)
            return

        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if length > 4096:
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
            self.send_response(303)
            self.send_header('Location', '/')
            self.send_header('Set-Cookie', self._session_cookie_header())
            self._send_security_headers()
            self.end_headers()
            return

        self._handle_login_page(error="Invalid token", status=401)

    def _handle_api_search(self, params):
        """JSON API for AJAX search."""
        query = params.get('q', [''])[0]
        type_filter = params.get('type', ['all'])[0]
        try:
            max_results = int(params.get('max', ['1000'])[0])
        except (ValueError, IndexError):
            max_results = 1000

        search_query = _query_with_remote_filters(query, type_filter)
        results = self.search_engine.search(
            search_query, max_results=min(max_results, 10000)
        )

        cards_html = self._build_result_cards(results)

        response = json.dumps({
            'count': len(results),
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
        try:
            max_results = int(params.get('max', ['1000'])[0])
        except (ValueError, IndexError):
            max_results = 1000

        search_query = _query_with_remote_filters(query, type_filter)
        results = self.search_engine.search(
            search_query,
            max_results=min(max_results, 10000),
        ) if search_query else []
        cards_html = self._build_result_cards(results)

        page_html = HTML_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'], mantle=MOCHA['mantle'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            subtext0=MOCHA['subtext0'], overlay0=MOCHA['overlay0'],
            accent=MOCHA['blue'],
            query=html.escape(query, quote=True),
            type_all='selected' if type_filter not in ('files', 'folders') else '',
            type_files='selected' if type_filter == 'files' else '',
            type_folders='selected' if type_filter == 'folders' else '',
            max_results=max(1, min(max_results, 10000)),
            count=len(results),
            cards=cards_html,
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

    def _build_result_cards(self, results):
        """Build read-only result cards from search results."""
        if not results:
            return '<div class="empty">Type a query to search your files</div>'

        cards = []
        for entry in results[:1000]:
            path = self.file_index.resolve_parent_path(entry.drive, entry.parent_frn)
            full_path = entry.get_path(self.file_index)

            size = ""
            if not entry.is_dir:
                try:
                    s = os.path.getsize(full_path) if os.path.exists(full_path) else 0
                    size = _format_size(s)
                except OSError:
                    pass

            dm = entry.date_modified.strftime('%Y-%m-%d %H:%M') if entry.date_modified else ''
            kind = "Folder" if entry.is_dir else (entry.extension.upper() + " file" if entry.extension else "File")

            name_escaped = html.escape(entry.name, quote=True)
            path_escaped = html.escape(path, quote=True)
            full_path_escaped = html.escape(full_path, quote=True)
            kind_escaped = html.escape(kind, quote=True)
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
                 use_https: bool = False, certfile: str = '', keyfile: str = ''):
        self._host = host
        self._port = port
        self._use_https = use_https
        self._certfile = certfile
        self._keyfile = keyfile
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Inject dependencies into handler class
        SearchHandler.file_index = file_index
        SearchHandler.search_engine = search_engine
        SearchHandler.auth_token = auth_token
        SearchHandler.session_token = secrets.token_urlsafe(32) if auth_token else ""

    def start(self):
        """Start the HTTP server in a background thread."""
        try:
            self._server = HTTPServer((self._host, self._port), SearchHandler)
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
            auth_status = " (auth enabled)" if SearchHandler.auth_token else ""
            logger.info(f"{self.scheme.upper()} server started on {self._host}:{self._port}{auth_status}")
            return True
        except Exception as e:
            if self._server:
                self._server.server_close()
                self._server = None
            logger.error(f"Failed to start {self.scheme.upper()} server: {e}")
            return False

    def stop(self):
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("HTTP server stopped")

    @property
    def url(self) -> str:
        return f"{self.scheme}://{self._host}:{self._port}"

    @property
    def scheme(self) -> str:
        return "https" if self._use_https else "http"
