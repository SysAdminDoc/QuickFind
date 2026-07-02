"""Offline help and search cheat sheet dialog."""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

from core.localization import tr
from core.version import APP_TITLE
from gui.accessibility import describe_widget
from gui.theme import MOCHA


SEARCH_MODIFIERS = (
    ("*.ext / ext:pdf", "Filter by file extension."),
    ("size:>1mb", "Filter by size using kb, mb, or gb."),
    ("dm:today / dc:>2024-01-01", "Filter by modified or created date."),
    ("parent:folder", "Match a parent directory name."),
    ("len:>10", "Filter by filename length."),
    ("attrib:H", "Filter by file attributes such as R, H, S, D, or A."),
    ("dupe:name / dupe:hash", "Find duplicates by filename or by content hash."),
    ("broken:link / broken:shortcut", "Find broken reparse links or shortcuts."),
    ("git:dirty", "Find files inside dirty Git worktrees."),
    ("content:text", "Search extracted text cached from supported document types."),
    ("archive:report", "Search cached ZIP and 7z member metadata."),
    ("@slot", "Expand a saved bookmark query slot."),
)

WORKFLOWS = (
    ("Fast path search", "Type a name, wildcard, or modifier; results update after the configured debounce."),
    ("Constrain roots", "Use Workspace roots to limit a tab to semicolon-separated folders."),
    ("Inspect matches", "Use Details, Columns, Thumbnails, Preview Pane, or Quick Preview to inspect results."),
    ("Save repeats", "Bookmark recurring searches and reuse them as @slot aliases in GUI or CLI queries."),
    ("Recover trust", "Use Tools > Index Diagnostics to inspect cache health, stale drives, services, and content cache."),
)

TROUBLESHOOTING = (
    ("Missing NTFS results", "Run elevated for direct MFT access or check the index mode and drive freshness badges."),
    ("Stale removable drive results", "Open Index Diagnostics and refresh the affected drive when it is online."),
    ("No content hits", "Enable content indexing, check adapter status, roots, extensions, quotas, and file-size limits."),
    ("Remote access fails", "Check bind address, port, HTTPS certificate/key paths, auth token, and browser session state."),
)


def _rows(items: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(
        f"<tr><td><code>{left}</code></td><td>{right}</td></tr>"
        for left, right in items
    )


def build_offline_help_html(app_title: str = APP_TITLE) -> str:
    """Return the offline help HTML styled with the active theme palette."""
    border = MOCHA['surface1']
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: Segoe UI, sans-serif; line-height: 1.45; }}
    h1, h2 {{ margin-bottom: 0.35rem; }}
    table {{ border-collapse: collapse; width: 100%; margin: 0.5rem 0 1rem; }}
    td {{ border-bottom: 1px solid {border}; padding: 0.35rem 0.45rem; vertical-align: top; }}
    code {{ font-family: Cascadia Code, Consolas, monospace; }}
  </style>
</head>
<body>
  <h1>{app_title} Offline Help</h1>
  <p>{tr("help.intro", "This cheat sheet is bundled with QuickFind and does not require network access.")}</p>

  <h2>{tr("help.search_syntax", "Search Syntax")}</h2>
  <table>{_rows(SEARCH_MODIFIERS)}</table>

  <h2>{tr("help.workflows", "Core Workflows")}</h2>
  <table>{_rows(WORKFLOWS)}</table>

  <h2>{tr("help.troubleshooting", "Troubleshooting")}</h2>
  <table>{_rows(TROUBLESHOOTING)}</table>
</body>
</html>"""


class OfflineHelpDialog(QDialog):
    """Modal offline help dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("help.title", "QuickFind Offline Help"))
        self.setMinimumSize(760, 560)
        describe_widget(
            self,
            "Offline help",
            "Bundled QuickFind search syntax, workflows, and troubleshooting help.",
        )

        layout = QVBoxLayout(self)

        self._viewer = QTextEdit()
        describe_widget(
            self._viewer,
            "Offline help content",
            "Read-only QuickFind cheat sheet and troubleshooting reference.",
        )
        self._viewer.setReadOnly(True)
        self._viewer.setHtml(build_offline_help_html())
        layout.addWidget(self._viewer)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        describe_widget(buttons, "Close offline help")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
