"""Shared utility functions used across core modules."""

import re

_NATURAL_SPLIT = re.compile(r'(\d+)')


def natural_key(text: str) -> list:
    """Key for human/natural ordering so 'file2' sorts before 'file10'.

    re.split on a digit group always yields non-digit segments at even indices
    and digit segments at odd indices, so the resulting keys are type-consistent
    position-by-position (str vs str, int vs int) and safe to compare.
    """
    return [
        int(part) if part.isdigit() else part.lower()
        for part in _NATURAL_SPLIT.split(text or "")
    ]


def natural_collation(a: str, b: str) -> int:
    """SQLite collation callback implementing natural order."""
    ka, kb = natural_key(a), natural_key(b)
    if ka < kb:
        return -1
    return 1 if ka > kb else 0


def parse_size(size_str: str) -> int:
    """Parse a size string like '1mb', '500kb', '2gb' into bytes."""
    size_str = size_str.strip().lower()
    multipliers = {
        'b': 1, 'kb': 1024, 'mb': 1024**2, 'gb': 1024**3, 'tb': 1024**4,
        'k': 1024, 'm': 1024**2, 'g': 1024**3, 't': 1024**4,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(suffix):
            try:
                return int(float(size_str[:-len(suffix)]) * mult)
            except ValueError:
                return 0
    try:
        return int(size_str)
    except ValueError:
        return 0
