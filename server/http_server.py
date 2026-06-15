"""
HTTP server for remote web browser access to QuickFind search.
Provides a lightweight web interface for searching the index remotely.
Supports optional token-based authentication.
"""

import html
import json
import logging
import os
import secrets
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional

from core.index import FileIndex
from core.search import SearchEngine, SearchOptions
from gui.theme import MOCHA

logger = logging.getLogger('QuickFind.HTTPServer')


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
table {{
    width: 100%;
    border-collapse: collapse;
}}
th {{
    background: {mantle};
    color: {subtext0};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    text-align: left;
    padding: 8px 14px;
    border-bottom: 1px solid {surface0};
    position: sticky;
    top: 49px;
    z-index: 5;
}}
td {{
    padding: 7px 14px;
    border-bottom: 1px solid {surface0};
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 420px;
}}
tr {{ transition: background 0.1s ease; }}
tr:hover {{ background: {surface0}; }}
tr:nth-child(even) {{ background: rgba(24,24,37,0.4); }}
tr:nth-child(even):hover {{ background: {surface0}; }}
.size {{ text-align: right; font-variant-numeric: tabular-nums; }}
.date {{ font-variant-numeric: tabular-nums; color: {subtext0}; }}
.empty {{ padding: 48px 24px; text-align: center; color: {overlay0}; font-size: 14px; }}
</style>
</head>
<body>
<div class="header">
    <h1>QuickFind</h1>
    <input class="search-box" type="text" id="search" placeholder="Search files and folders…"
           value="{query}" autofocus aria-label="Search">
</div>
<div class="meta-bar" id="count">{count} results</div>
<table>
<thead><tr><th>Name</th><th>Path</th><th class="size">Size</th><th>Modified</th></tr></thead>
<tbody id="results">{rows}</tbody>
</table>
<script>
let timer;
const search = document.getElementById('search');
const countEl = document.getElementById('count');
const token = new URLSearchParams(window.location.search).get('token') || '';
search.addEventListener('input', () => {{
    clearTimeout(timer);
    countEl.textContent = 'Searching…';
    timer = setTimeout(() => {{
        const params = new URLSearchParams({{q: search.value}});
        if (token) params.set('token', token);
        fetch('/api/search?' + params)
            .then(r => r.json())
            .then(data => {{
                const n = data.count;
                countEl.textContent = n + ' result' + (n !== 1 ? 's' : '');
                document.getElementById('results').innerHTML = data.rows;
            }})
            .catch(() => {{ countEl.textContent = 'Search failed'; }});
    }}, 200);
}});
search.select();
</script>
</body>
</html>"""


def _format_size(size):
    if size <= 0: return ""
    if size < 1024: return f"{size} B"
    if size < 1048576: return f"{size/1024:.1f} KB"
    if size < 1073741824: return f"{size/1048576:.1f} MB"
    return f"{size/1073741824:.2f} GB"


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

    def log_message(self, format, *args):
        logger.debug(format % args)

    def _check_auth(self, params) -> bool:
        """Validate token if authentication is enabled."""
        if not self.auth_token:
            return True
        request_token = params.get('token', [''])[0]
        if not request_token:
            # Also check Authorization header
            auth_header = self.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                request_token = auth_header[7:]
        return secrets.compare_digest(request_token, self.auth_token)

    def _send_security_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'")
        self.send_header('X-Content-Type-Options', 'nosniff')

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

        if not self._check_auth(params):
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
            return

        if parsed.path == '/api/search':
            self._handle_api_search(params)
        elif parsed.path == '/' or parsed.path == '':
            self._handle_page(params)
        else:
            self.send_error(404)

    def _handle_api_search(self, params):
        """JSON API for AJAX search."""
        query = params.get('q', [''])[0]
        try:
            max_results = int(params.get('max', ['1000'])[0])
        except (ValueError, IndexError):
            max_results = 1000

        results = self.search_engine.search(
            query, max_results=min(max_results, 10000)
        )

        rows_html = self._build_rows(results)

        response = json.dumps({
            'count': len(results),
            'rows': rows_html,
        })

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _handle_page(self, params):
        """Serve the main search page."""
        query = params.get('q', [''])[0]

        results = self.search_engine.search(query, max_results=1000) if query else []
        rows_html = self._build_rows(results)

        page_html = HTML_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'], mantle=MOCHA['mantle'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            subtext0=MOCHA['subtext0'], overlay0=MOCHA['overlay0'],
            accent=MOCHA['blue'],
            query=html.escape(query, quote=True),
            count=len(results),
            rows=rows_html,
        )

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(page_html.encode('utf-8'))

    def _build_rows(self, results):
        """Build HTML table rows from search results."""
        if not results:
            return '<tr><td colspan="4" class="empty">Type a query to search your files</td></tr>'

        rows = []
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

            name_escaped = html.escape(entry.name)
            path_escaped = html.escape(path)

            rows.append(
                f'<tr><td>{name_escaped}</td><td>{path_escaped}</td>'
                f'<td class="size">{size}</td><td class="date">{dm}</td></tr>'
            )

        return '\n'.join(rows)


class QuickFindHTTPServer:
    """Wrapper to run the HTTP server in a background thread."""

    def __init__(self, file_index: FileIndex, search_engine: SearchEngine,
                 host: str = '127.0.0.1', port: int = 8080, auth_token: str = ''):
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Inject dependencies into handler class
        SearchHandler.file_index = file_index
        SearchHandler.search_engine = search_engine
        SearchHandler.auth_token = auth_token

    def start(self):
        """Start the HTTP server in a background thread."""
        try:
            self._server = HTTPServer((self._host, self._port), SearchHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            auth_status = " (auth enabled)" if SearchHandler.auth_token else ""
            logger.info(f"HTTP server started on {self._host}:{self._port}{auth_status}")
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")

    def stop(self):
        """Stop the HTTP server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("HTTP server stopped")

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}"
