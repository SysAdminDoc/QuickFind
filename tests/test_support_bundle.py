"""Tests for redacted diagnostics support bundle export."""

import json
import zipfile
from dataclasses import dataclass, field

from core.support_bundle import (
    REDACTED,
    collect_support_diagnostics,
    default_support_bundle_name,
    write_support_bundle,
)


class FakeIndex:
    def index_diagnostics(self):
        return {
            "source": "test",
            "total_entries": 3,
            "drives": [{"drive": "C", "state": "online"}],
        }


@dataclass
class FakeContentStats:
    scanned: int = 3
    indexed: int = 1
    adapter_failures: dict[str, int] = field(default_factory=lambda: {"pdf:timeout": 1})
    last_error: str = "token=top-secret-token"


def test_support_bundle_redacts_settings_logs_and_content_stats(tmp_path):
    log_file = tmp_path / "quickfind.log"
    log_file.write_text(
        "Authorization: Bearer top-secret-token\n"
        "password=hunter2 token=top-secret-token\n"
        "normal diagnostic line\n",
        encoding="utf-8",
    )

    payload = collect_support_diagnostics(
        index=FakeIndex(),
        settings={
            "http_auth_token": "top-secret-token",
            "network_password": "hunter2",
            "https_key_file": "C:\\secret\\quickfind.key",
            "http_bind": "127.0.0.1",
        },
        cache_diag={
            "db_exists": True,
            "entry_count": 3,
            "content": {"count": 1, "text_bytes": 128},
        },
        service_diag={"available": False, "state": "unreachable"},
        runtime={"Python": "3.11.9"},
        content_index_stats=FakeContentStats(),
        log_file=log_file,
    )

    encoded = json.dumps(payload, sort_keys=True)

    assert "top-secret-token" not in encoded
    assert "hunter2" not in encoded
    assert "quickfind.key" not in encoded
    assert payload["settings"]["http_auth_token"] == REDACTED
    assert payload["settings"]["network_password"] == REDACTED
    assert payload["settings"]["https_key_file"] == REDACTED
    assert payload["settings"]["http_bind"] == "127.0.0.1"
    assert "Bearer [REDACTED]" in "\n".join(payload["log_tail"])
    assert payload["content"]["last_index_job"]["adapter_failures"]["pdf:timeout"] == 1
    assert payload["content"]["last_index_job"]["last_error"] == f"token={REDACTED}"


def test_write_support_bundle_zip_contains_redacted_json_and_log_tail(tmp_path):
    log_file = tmp_path / "quickfind.log"
    log_file.write_text("auth_token=abc123\n", encoding="utf-8")
    target = tmp_path / "bundle.zip"

    write_support_bundle(
        target,
        settings={"http_auth_token": "abc123"},
        cache_diag={"content": {}},
        service_diag={},
        runtime={},
        log_file=log_file,
    )

    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
        support_json = archive.read("quickfind-support.json").decode("utf-8")
        log_tail = archive.read("logs/quickfind.log.tail.txt").decode("utf-8")

    assert names == {"quickfind-support.json", "logs/quickfind.log.tail.txt"}
    assert "abc123" not in support_json
    assert "abc123" not in log_tail
    assert REDACTED in support_json
    assert REDACTED in log_tail


def test_write_support_bundle_json_uses_plain_json(tmp_path):
    target = tmp_path / "bundle.json"

    write_support_bundle(
        target,
        settings={"http_auth_token": "abc123"},
        cache_diag={"content": {}},
        service_diag={},
        runtime={},
        log_file=tmp_path / "missing.log",
    )

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["settings"]["http_auth_token"] == REDACTED


def test_default_support_bundle_name_is_zip():
    assert default_support_bundle_name().startswith("quickfind-support-")
    assert default_support_bundle_name().endswith(".zip")
