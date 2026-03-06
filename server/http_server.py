"""
HTTP server for remote web browser access to QuickFind search.
Provides a lightweight web interface for searching the index remotely.
"""

import json
import logging
import os
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
<title>QuickFind - Remote Search</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {bg};
    color: {text};
    font-family: 'Segoe UI', -apple-system, sans-serif;
    min-height: 100vh;
}}
.header {{
    background: {mantle};
    border-bottom: 1px solid {surface0};
    padding: 16px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
}}
.header h1 {{
    font-size: 18px;
    color: {accent};
    font-weight: 600;
}}
.search-box {{
    flex: 1;
    max-width: 600px;
    background: {surface0};
    border: 2px solid {surface1};
    border-radius: 8px;
    padding: 8px 16px;
    color: {text};
    font-size: 15px;
    outline: none;
    transition: border-color 0.2s;
}}
.search-box:focus {{ border-color: {accent}; }}
.results-count {{
    color: {subtext0};
    font-size: 13px;
    padding: 8px 24px;
    background: {mantle};
    border-bottom: 1px solid {surface0};
}}
table {{
    width: 100%;
    border-collapse: collapse;
}}
th {{
    background: {mantle};
    color: {subtext0};
    font-weight: 600;
    font-size: 12px;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid {surface0};
    position: sticky;
    top: 0;
}}
td {{
    padding: 6px 12px;
    border-bottom: 1px solid {surface0};
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 400px;
}}
tr:hover {{ background: {surface0}; }}
tr:nth-child(even) {{ background: {mantle}; }}
tr:nth-child(even):hover {{ background: {surface0}; }}
a {{ color: {accent}; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
.size {{ text-align: right; }}
.empty {{ padding: 40px; text-align: center; color: {overlay0}; font-size: 15px; }}
</style>
</head>
<body>
<div class="header">
    <h1>QuickFind</h1>
    <input class="search-box" type="text" id="search" placeholder="Search files and folders..."
           value="{query}" autofocus>
</div>
<div class="results-count" id="count">{count} results</div>
<table>
<thead><tr><th>Name</th><th>Path</th><th class="size">Size</th><th>Modified</th></tr></thead>
<tbody id="results">{rows}</tbody>
</table>
<script>
let timer;
const search = document.getElementById('search');
search.addEventListener('input', () => {{
    clearTimeout(timer);
    timer = setTimeout(() => {{
        fetch('/api/search?q=' + encodeURIComponent(search.value))
            .then(r => r.json())
            .then(data => {{
                document.getElementById('count').textContent = data.count + ' results';
                document.getElementById('results').innerHTML = data.rows;
            }});
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


class SearchHandler(BaseHTTPRequestHandler):
    """HTTP request handler for search API."""

    file_index: FileIndex = None
    search_engine: SearchEngine = None

    def log_message(self, format, *args):
        logger.debug(format % args)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == '/api/search':
            self._handle_api_search(params)
        elif parsed.path == '/' or parsed.path == '':
            self._handle_page(params)
        else:
            self.send_error(404)

    def _handle_api_search(self, params):
        """JSON API for AJAX search."""
        query = params.get('q', [''])[0]
        max_results = int(params.get('max', ['1000'])[0])

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
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _handle_page(self, params):
        """Serve the main search page."""
        query = params.get('q', [''])[0]

        results = self.search_engine.search(query, max_results=1000) if query else []
        rows_html = self._build_rows(results)

        html = HTML_TEMPLATE.format(
            bg=MOCHA['base'], text=MOCHA['text'], mantle=MOCHA['mantle'],
            surface0=MOCHA['surface0'], surface1=MOCHA['surface1'],
            subtext0=MOCHA['subtext0'], overlay0=MOCHA['overlay0'],
            accent=MOCHA['blue'],
            query=query.replace('"', '&quot;'),
            count=len(results),
            rows=rows_html,
        )

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def _build_rows(self, results):
        """Build HTML table rows from search results."""
        if not results:
            return '<tr><td colspan="4" class="empty">No results</td></tr>'

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

            name_escaped = entry.name.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            path_escaped = path.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            rows.append(
                f'<tr><td>{name_escaped}</td><td>{path_escaped}</td>'
                f'<td class="size">{size}</td><td>{dm}</td></tr>'
            )

        return '\n'.join(rows)


class QuickFindHTTPServer:
    """Wrapper to run the HTTP server in a background thread."""

    def __init__(self, file_index: FileIndex, search_engine: SearchEngine,
                 host: str = '127.0.0.1', port: int = 8080):
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

        # Inject dependencies into handler class
        SearchHandler.file_index = file_index
        SearchHandler.search_engine = search_engine

    def start(self):
        """Start the HTTP server in a background thread."""
        try:
            self._server = HTTPServer((self._host, self._port), SearchHandler)
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            logger.info(f"HTTP server started on {self._host}:{self._port}")
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
