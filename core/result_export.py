"""Export search results in CSV, JSON, and HTML report formats."""

from __future__ import annotations

import csv
import html
import io
import json
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ExportableResult:
    name: str
    path: str
    parent_path: str
    kind: str
    extension: str
    size_bytes: int | None = None
    size_display: str = ""
    date_modified: str = ""
    content_snippet: str = ""


@dataclass(frozen=True)
class ExportMetadata:
    query: str = ""
    result_count: int = 0
    export_format: str = ""
    app_version: str = ""


_CSV_INJECTION_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value):
    """Neutralize spreadsheet formula/DDE injection from attacker-controlled
    filenames by prefixing risky leading characters with a single quote."""
    if isinstance(value, str) and value and value[0] in _CSV_INJECTION_PREFIXES:
        return "'" + value
    return value


def export_csv(results: Sequence[ExportableResult], metadata: ExportMetadata | None = None) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Name", "Path", "Parent", "Type", "Extension", "Size", "Modified", "Snippet"])
    for r in results:
        writer.writerow([
            _csv_safe(r.name), _csv_safe(r.path), _csv_safe(r.parent_path),
            _csv_safe(r.kind), _csv_safe(r.extension),
            r.size_bytes if r.size_bytes is not None else "",
            _csv_safe(r.date_modified),
            _csv_safe(r.content_snippet),
        ])
    return buf.getvalue()


def export_json(results: Sequence[ExportableResult], metadata: ExportMetadata | None = None) -> str:
    items = []
    for r in results:
        item = {
            "name": r.name,
            "path": r.path,
            "parent_path": r.parent_path,
            "type": r.kind,
            "extension": r.extension,
            "size_bytes": r.size_bytes,
            "date_modified": r.date_modified,
        }
        if r.content_snippet:
            item["content_snippet"] = r.content_snippet
        items.append(item)
    payload: dict = {"results": items, "count": len(items)}
    if metadata:
        payload["query"] = metadata.query
        payload["app_version"] = metadata.app_version
    return json.dumps(payload, indent=2, ensure_ascii=False)


_DEFAULT_THEME = {
    'base': '#1e1e2e', 'text': '#cdd6f4', 'blue': '#89b4fa',
    'subtext0': '#a6adc8', 'surface1': '#45475a', 'surface0': '#313244',
}


def export_html(results: Sequence[ExportableResult], metadata: ExportMetadata | None = None,
                theme: dict[str, str] | None = None) -> str:
    meta = metadata or ExportMetadata()
    t = theme or _DEFAULT_THEME
    query_escaped = html.escape(meta.query, quote=True)
    has_snippets = any(r.content_snippet for r in results)
    rows = []
    for r in results:
        snippet_cell = f"<td>{html.escape(r.content_snippet)}</td>" if has_snippets else ""
        rows.append(
            "<tr>"
            f"<td>{html.escape(r.name)}</td>"
            f"<td>{html.escape(r.path)}</td>"
            f"<td>{html.escape(r.kind)}</td>"
            f"<td>{html.escape(r.size_display)}</td>"
            f"<td>{html.escape(r.date_modified)}</td>"
            f"{snippet_cell}"
            "</tr>"
        )
    snippet_header = "<th>Snippet</th>" if has_snippets else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>QuickFind Export</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 24px; background: {t['base']}; color: {t['text']}; }}
h1 {{ font-size: 18px; color: {t['blue']}; }}
.meta {{ color: {t['subtext0']}; font-size: 13px; margin-bottom: 16px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid {t['surface1']}; padding: 6px 10px; text-align: left; font-size: 13px; }}
th {{ background: {t['surface0']}; color: {t['text']}; }}
tr:nth-child(even) {{ background: {t['surface0']}40; }}
</style>
</head>
<body>
<h1>QuickFind Results</h1>
<div class="meta">Query: {query_escaped} &mdash; {meta.result_count} results</div>
<table>
<thead><tr><th>Name</th><th>Path</th><th>Type</th><th>Size</th><th>Modified</th>{snippet_header}</tr></thead>
<tbody>
{"".join(rows)}
</tbody>
</table>
</body>
</html>"""
