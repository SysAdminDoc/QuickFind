"""Shared utility functions used across core modules."""


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
