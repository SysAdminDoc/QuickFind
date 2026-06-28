"""Validation helpers for persisted and imported settings data."""

from pathlib import Path
from typing import Any, Mapping


INT_RANGES = {
    "http_port": (1, 65535),
    "usn_poll_interval_ms": (100, 10000),
    "default_max_results": (0, 10000000),
    "search_delay_ms": (0, 2000),
    "window_width": (640, 10000),
    "window_height": (480, 10000),
}

STRING_FIELDS = {
    "http_bind",
    "http_auth_token",
    "https_cert_file",
    "https_key_file",
}


def _path_exists(path: str) -> bool:
    return Path(path).expanduser().exists()


def _coerce_int(name: str, value: Any, default: int, warnings: list[str]) -> int:
    minimum, maximum = INT_RANGES[name]
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        warnings.append(f"{name} reset to {default} because it was not a number.")
        return default

    if coerced < minimum or coerced > maximum:
        warnings.append(f"{name} reset to {default} because it must be between {minimum} and {maximum}.")
        return default
    return coerced


def sanitize_settings_data(
    data: Mapping[str, Any],
    defaults: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Return settings data with invalid values replaced by safe defaults."""
    sanitized = dict(defaults)
    warnings: list[str] = []

    for key in defaults:
        if key in data:
            sanitized[key] = data[key]

    for name in INT_RANGES:
        sanitized[name] = _coerce_int(name, sanitized.get(name), defaults[name], warnings)

    for name in STRING_FIELDS:
        value = sanitized.get(name, "")
        sanitized[name] = value.strip() if isinstance(value, str) else ""

    if not sanitized["http_bind"]:
        sanitized["http_bind"] = defaults["http_bind"]
        warnings.append(f"http_bind reset to {defaults['http_bind']} because it was blank.")

    for name in ("https_cert_file", "https_key_file"):
        path = sanitized[name]
        if path and not _path_exists(path):
            sanitized[name] = ""
            warnings.append(f"{name} cleared because the file does not exist: {path}")

    if sanitized.get("http_use_https") and (
        not sanitized["https_cert_file"] or not sanitized["https_key_file"]
    ):
        sanitized["http_use_https"] = False
        warnings.append("http_use_https disabled because both TLS certificate and private key files are required.")

    efu_files = sanitized.get("efu_files", [])
    valid_efu_files = []
    if isinstance(efu_files, list):
        for path in efu_files:
            if not isinstance(path, str) or not path.strip():
                warnings.append("Ignored an empty or invalid EFU file path.")
                continue
            cleaned = path.strip()
            if _path_exists(cleaned):
                valid_efu_files.append(cleaned)
            else:
                warnings.append(f"Ignored missing EFU file: {cleaned}")
    else:
        warnings.append("efu_files reset because it was not a list.")
    sanitized["efu_files"] = valid_efu_files

    return sanitized, warnings
