"""Query-time synonym expansion.

A user-editable JSON file at ~/.quickfind/synonyms.json maps a term to a list of
synonyms, e.g. {"car": ["automobile", "vehicle"]}. When present, a query term is
expanded into an OR group so any synonym matches. The feature is inert (disabled)
until the file exists, so it costs nothing by default.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("QuickFind.Synonyms")

CONFIG_DIR = Path.home() / ".quickfind"
SYNONYMS_FILE = CONFIG_DIR / "synonyms.json"


def load_synonyms(path: Path | None = None) -> dict[str, list[str]]:
    """Load the term -> [synonyms] map. Returns {} if absent or malformed."""
    if path is None:
        path = SYNONYMS_FILE
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, values in raw.items():
        if not isinstance(values, list):
            continue
        syns = [str(v).strip() for v in values if str(v).strip()]
        term = str(key).strip().lower()
        if term and syns:
            out[term] = syns
    return out


def expand_query_terms(terms: list[str], synonyms: dict[str, list[str]]):
    """Split terms into (unexpanded_terms, new_or_groups).

    A term with configured synonyms becomes an OR group [term, *synonyms];
    terms without synonyms are returned unchanged.
    """
    remaining: list[str] = []
    groups: list[list[str]] = []
    for term in terms:
        syns = synonyms.get(term.lower())
        if syns:
            groups.append([term, *syns])
        else:
            remaining.append(term)
    return remaining, groups
