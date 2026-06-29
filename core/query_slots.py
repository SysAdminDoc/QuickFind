"""Saved query slot expansion for @name search aliases."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger('QuickFind.QuerySlots')

BOOKMARKS_FILE = Path.home() / '.quickfind' / 'bookmarks.json'
SLOT_TOKEN_RE = re.compile(r'(?<!\S)@([A-Za-z0-9][A-Za-z0-9_-]{0,63})(?!\S)')


@dataclass(frozen=True)
class QuerySlotExpansion:
    expanded_query: str
    expanded_slots: tuple[str, ...] = ()
    unresolved_slots: tuple[str, ...] = ()
    recursive_slots: tuple[str, ...] = ()


def normalize_query_slot_name(name: str) -> str:
    """Normalize a bookmark name or explicit slot into @slot syntax."""
    normalized = name.strip().lower().lstrip('@')
    normalized = re.sub(r'[^a-z0-9_-]+', '-', normalized)
    normalized = re.sub(r'-{2,}', '-', normalized).strip('-_')
    return normalized


def query_slots_from_bookmarks(bookmarks: Sequence[Any]) -> dict[str, str]:
    """Build a slot map from persisted bookmark records or Bookmark objects."""
    slots: dict[str, str] = {}
    for bookmark in bookmarks:
        query = str(_record_value(bookmark, 'query', '')).strip()
        if not query:
            continue

        candidates = (
            str(_record_value(bookmark, 'slot', '')),
            str(_record_value(bookmark, 'name', '')),
        )
        for candidate in candidates:
            slot = normalize_query_slot_name(candidate)
            if slot and slot not in slots:
                slots[slot] = query
    return slots


def load_saved_query_slots(bookmarks_file: Path = BOOKMARKS_FILE) -> dict[str, str]:
    try:
        if not bookmarks_file.exists():
            return {}
        data = json.loads(bookmarks_file.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            return {}
        return query_slots_from_bookmarks(data)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.debug(f"Failed to load saved query slots: {exc}")
        return {}


def expand_query_slots(raw_query: str,
                       slots: Mapping[str, str] | None,
                       max_depth: int = 8) -> QuerySlotExpansion:
    """Expand whitespace-delimited @slot tokens using a normalized slot map."""
    if not raw_query or not slots:
        return QuerySlotExpansion(raw_query)

    slot_map = _normalize_slot_map(slots)
    if not slot_map:
        return QuerySlotExpansion(raw_query)

    expanded_slots: list[str] = []
    unresolved_slots: list[str] = []
    recursive_slots: list[str] = []

    def expand_text(text: str, stack: tuple[str, ...]) -> str:
        def replace_slot(match: re.Match[str]) -> str:
            requested = normalize_query_slot_name(match.group(1))
            if not requested:
                return match.group(0)
            if requested not in slot_map:
                _append_unique(unresolved_slots, requested)
                return match.group(0)
            if requested in stack:
                _append_unique(recursive_slots, requested)
                return match.group(0)

            _append_unique(expanded_slots, requested)
            replacement = slot_map[requested]
            if len(stack) + 1 >= max_depth:
                _append_unique(recursive_slots, requested)
                return replacement
            return expand_text(replacement, stack + (requested,))

        return SLOT_TOKEN_RE.sub(replace_slot, text)

    return QuerySlotExpansion(
        expanded_query=expand_text(raw_query, ()),
        expanded_slots=tuple(expanded_slots),
        unresolved_slots=tuple(unresolved_slots),
        recursive_slots=tuple(recursive_slots),
    )


def _normalize_slot_map(slots: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in slots.items():
        slot = normalize_query_slot_name(str(key))
        query = str(value).strip()
        if slot and query and slot not in normalized:
            normalized[slot] = query
    return normalized


def _record_value(record: Any, key: str, default: Any) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _append_unique(items: list[str], value: str):
    if value not in items:
        items.append(value)
