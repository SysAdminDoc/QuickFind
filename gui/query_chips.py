"""Visual query builder: extract, display, and compose modifier chips."""

from __future__ import annotations

import re
from dataclasses import dataclass


CHIP_MODIFIERS = [
    ("ext", "Extension"),
    ("size", "Size"),
    ("dm", "Modified"),
    ("dc", "Created"),
    ("parent", "Parent"),
    ("len", "Length"),
    ("attrib", "Attribute"),
    ("dupe", "Duplicate"),
    ("content", "Content"),
    ("archive", "Archive"),
    ("file", "Files only"),
    ("folder", "Folders only"),
    ("git", "Git"),
    ("broken", "Broken"),
]

MODIFIER_NAMES = frozenset(name for name, _ in CHIP_MODIFIERS)


@dataclass(frozen=True)
class QueryChip:
    modifier: str
    value: str
    label: str
    raw: str

    @property
    def display(self) -> str:
        return f"{self.modifier}:{self.value}" if self.value else self.modifier


def extract_chips(query: str) -> tuple[list[QueryChip], str]:
    """Split a query into modifier chips and the remaining free-text.

    Returns (chips, remaining_text).
    """
    chips: list[QueryChip] = []
    remaining: list[str] = []

    tokens = _tokenize(query)
    for token in tokens:
        chip = _parse_chip(token)
        if chip:
            chips.append(chip)
        else:
            remaining.append(token)

    return chips, " ".join(remaining)


def compose_query(chips: list[QueryChip], free_text: str) -> str:
    """Rebuild a query string from chips and free text."""
    parts = [chip.raw for chip in chips]
    if free_text.strip():
        parts.append(free_text.strip())
    return " ".join(parts)


def add_chip(query: str, modifier: str, value: str) -> str:
    """Add a modifier chip to a query string."""
    chip_str = f"{modifier}:{value}" if value else f"{modifier}:"
    return f"{query.strip()} {chip_str}".strip()


def remove_chip(query: str, chip: QueryChip) -> str:
    """Remove a specific chip from a query string."""
    chips, free_text = extract_chips(query)
    chips = [c for c in chips if c != chip]
    return compose_query(chips, free_text)


def available_modifiers() -> list[tuple[str, str]]:
    """Return (modifier_name, display_label) pairs for the UI."""
    return list(CHIP_MODIFIERS)


def validate_chip(modifier: str, value: str) -> str | None:
    """Return an error message if the chip is invalid, or None if valid."""
    if modifier not in MODIFIER_NAMES:
        return f"Unknown modifier: {modifier}"
    if modifier in ("ext", "parent", "content", "archive",
                     "git", "attrib") and not value:
        return f"{modifier}: requires a value"
    if modifier == "size" and value:
        if not re.match(r'^[<>=!]*\d+(\.\d+)?\s*(b|kb|mb|gb|tb)?$', value.lower()):
            return f"Invalid size: {value}"
    return None


def _tokenize(query: str) -> list[str]:
    """Split query into tokens, preserving quoted strings."""
    tokens = []
    current = ""
    in_quote = False
    for char in query:
        if char == '"':
            in_quote = not in_quote
            current += char
        elif char == ' ' and not in_quote:
            if current:
                tokens.append(current)
            current = ""
        else:
            current += char
    if current:
        tokens.append(current)
    return tokens


def _parse_chip(token: str) -> QueryChip | None:
    """Try to parse a token as a modifier chip."""
    if ':' not in token:
        return None
    mod, _, value = token.partition(':')
    mod_lower = mod.lower()
    if mod_lower not in MODIFIER_NAMES:
        return None
    label = next((lbl for name, lbl in CHIP_MODIFIERS if name == mod_lower), mod_lower)
    return QueryChip(
        modifier=mod_lower,
        value=value,
        label=label,
        raw=token,
    )
