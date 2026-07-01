"""Redacted diagnostics support bundle export."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.cache import cache_diagnostics
from core.content import adapter_diagnostics
from core.runtime_info import runtime_matrix
from core.version import APP_NAME, VERSION
from service.ipc import service_health

LOG_FILE = Path.home() / ".quickfind" / "quickfind.log"
REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "token",
    "password",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "session",
)
_SENSITIVE_KEY_NAMES = {
    "https_key_file",
    "key_file",
    "private_key",
    "tls_private_key",
}
_AUTH_HEADER_RE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_SECRET_PAIR_RE = re.compile(
    r"\b(token|password|secret|auth_token|cookie|session)\b"
    r"(\s*[:=]\s*)([^&\s,;]+)",
    re.IGNORECASE,
)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:token|password|secret|auth_token|session)=)([^&#\s]+)",
    re.IGNORECASE,
)


def default_support_bundle_name(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"quickfind-support-{timestamp}.zip"


def collect_support_diagnostics(
    *,
    index: Any | None = None,
    settings: Any | None = None,
    cache_diag: dict[str, Any] | None = None,
    service_diag: dict[str, Any] | None = None,
    runtime: dict[str, str] | None = None,
    content_index_stats: Any | None = None,
    log_file: str | Path | None = None,
    log_line_limit: int = 200,
) -> dict[str, Any]:
    """Collect support diagnostics without raw secrets or cached document text."""
    settings_data = _settings_payload(settings)
    secret_values = _collect_secret_values(settings_data)
    cache_payload = cache_diag if cache_diag is not None else cache_diagnostics()

    payload = {
        "bundle_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "app": {
            "name": APP_NAME,
            "version": VERSION,
        },
        "runtime": runtime if runtime is not None else runtime_matrix(),
        "settings": settings_data,
        "index": _index_diagnostics(index),
        "cache": cache_payload,
        "service": service_diag if service_diag is not None else service_health(),
        "content": {
            "cache": cache_payload.get("content", {}) if isinstance(cache_payload, dict) else {},
            "adapters": _adapter_payload(),
            "last_index_job": _plain_value(content_index_stats),
        },
        "log_tail": _tail_log(log_file or LOG_FILE, log_line_limit),
    }
    return _redact_value(payload, secret_values=secret_values)


def write_support_bundle(
    path: str | Path,
    *,
    index: Any | None = None,
    settings: Any | None = None,
    cache_diag: dict[str, Any] | None = None,
    service_diag: dict[str, Any] | None = None,
    runtime: dict[str, str] | None = None,
    content_index_stats: Any | None = None,
    log_file: str | Path | None = None,
) -> Path:
    """Write a redacted support bundle as JSON or ZIP based on the file suffix."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = collect_support_diagnostics(
        index=index,
        settings=settings,
        cache_diag=cache_diag,
        service_diag=service_diag,
        runtime=runtime,
        content_index_stats=content_index_stats,
        log_file=log_file,
    )
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)

    if target.suffix.lower() == ".json":
        target.write_text(text + "\n", encoding="utf-8")
        return target

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("quickfind-support.json", text + "\n")
        archive.writestr("logs/quickfind.log.tail.txt", "\n".join(payload.get("log_tail", [])) + "\n")
    return target


def _settings_payload(settings: Any | None) -> dict[str, Any]:
    if settings is None:
        try:
            from gui.settings_dialog import Settings

            settings = Settings.load()
        except Exception:
            return {"available": False}
    value = _plain_value(settings)
    return value if isinstance(value, dict) else {"value": value}


def _index_diagnostics(index: Any | None) -> dict[str, Any]:
    if index is None or not hasattr(index, "index_diagnostics"):
        return {"available": False}
    try:
        result = index.index_diagnostics()
        return result if isinstance(result, dict) else {"value": result}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _adapter_payload() -> list[dict[str, Any]]:
    try:
        return [_plain_value(item) for item in adapter_diagnostics()]
    except Exception as exc:
        return [{"available": False, "detail": str(exc)}]


def _tail_log(path: str | Path, limit: int) -> list[str]:
    source = Path(path)
    if limit <= 0 or not source.exists():
        return []
    try:
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-limit:]


def _plain_value(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain_value(item) for item in value]
    return value


def _collect_secret_values(value: Any, key: str = "") -> set[str]:
    secrets: set[str] = set()
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            secrets.update(_collect_secret_values(child_value, str(child_key)))
        return secrets
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            secrets.update(_collect_secret_values(item, key))
        return secrets
    if _is_sensitive_key(key) and isinstance(value, str) and value:
        secrets.add(value)
    return secrets


def _redact_value(value: Any, *, key: str = "", secret_values: set[str]) -> Any:
    if _is_sensitive_key(key):
        if value in ("", None, False):
            return "" if isinstance(value, str) else value
        return REDACTED
    if isinstance(value, dict):
        return {
            str(child_key): _redact_value(child_value, key=str(child_key), secret_values=secret_values)
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item, key=key, secret_values=secret_values) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item, key=key, secret_values=secret_values) for item in value]
    if isinstance(value, str):
        return _redact_text(value, secret_values)
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    if normalized in _SENSITIVE_KEY_NAMES or normalized.endswith("_key_file"):
        return True
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_text(text: str, secret_values: set[str]) -> str:
    redacted = text
    for secret in sorted((item for item in secret_values if item), key=len, reverse=True):
        redacted = redacted.replace(secret, REDACTED)
    redacted = _AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    redacted = _SECRET_PAIR_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}{REDACTED}", redacted)
    redacted = _SECRET_QUERY_RE.sub(lambda match: f"{match.group(1)}{REDACTED}", redacted)
    home = str(Path.home())
    if home:
        redacted = redacted.replace(home, "~")
    return redacted
