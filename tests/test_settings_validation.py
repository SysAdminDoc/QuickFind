"""Tests for persisted settings validation."""

import json

import pytest

from core.ntfs import FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT
import gui.settings_dialog as settings_dialog
from gui.settings_dialog import (
    Settings,
    attribute_mask_to_text,
    attribute_text_to_mask,
    split_rule_text,
)
from gui.settings_validation import (
    SETTINGS_SCHEMA_VERSION,
    SettingsMigrationError,
    migrate_settings_data,
    sanitize_settings_data,
)


DEFAULTS = {
    "schema_version": SETTINGS_SCHEMA_VERSION,
    "http_port": 8080,
    "usn_poll_interval_ms": 1000,
    "drive_startup_delay_seconds": 0,
    "default_max_results": 0,
    "search_delay_ms": 0,
    "window_width": 1200,
    "window_height": 700,
    "http_bind": "127.0.0.1",
    "http_auth_token": "",
    "http_use_https": False,
    "https_cert_file": "",
    "https_key_file": "",
    "efu_files": [],
    "content_index_roots": [],
    "content_index_extensions": [],
    "content_index_max_cache_mb": 512,
    "content_index_max_file_mb": 10,
    "index_case_mode": "smart",
    "exclude_globs": [],
    "exclude_regexes": [],
    "exclude_attribute_mask": 0,
    "network_share_roots": [],
    "efu_refresh_interval_minutes": 0,
    "theme_name": "mocha",
    "language": "en",
}


def test_invalid_port_resets_to_default():
    sanitized, warnings = sanitize_settings_data({"http_port": 70000}, DEFAULTS)

    assert sanitized["http_port"] == 8080
    assert any("http_port reset" in warning for warning in warnings)


def test_blank_bind_resets_to_loopback():
    sanitized, warnings = sanitize_settings_data({"http_bind": "   "}, DEFAULTS)

    assert sanitized["http_bind"] == "127.0.0.1"
    assert any("http_bind reset" in warning for warning in warnings)


def test_invalid_drive_startup_delay_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"drive_startup_delay_seconds": 500},
        DEFAULTS,
    )

    assert sanitized["drive_startup_delay_seconds"] == 0
    assert any("drive_startup_delay_seconds reset" in warning for warning in warnings)


def test_missing_tls_files_disable_https():
    sanitized, warnings = sanitize_settings_data(
        {
            "http_use_https": True,
            "https_cert_file": "missing-cert.pem",
            "https_key_file": "missing-key.pem",
        },
        DEFAULTS,
    )

    assert sanitized["http_use_https"] is False
    assert sanitized["https_cert_file"] == ""
    assert sanitized["https_key_file"] == ""
    assert any("http_use_https disabled" in warning for warning in warnings)


def test_existing_tls_files_are_preserved(tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("cert")
    key.write_text("key")

    sanitized, warnings = sanitize_settings_data(
        {
            "http_use_https": True,
            "https_cert_file": str(cert),
            "https_key_file": str(key),
        },
        DEFAULTS,
    )

    assert sanitized["http_use_https"] is True
    assert sanitized["https_cert_file"] == str(cert)
    assert sanitized["https_key_file"] == str(key)
    assert warnings == []


def test_efu_files_keep_only_existing_paths(tmp_path):
    efu = tmp_path / "list.efu"
    efu.write_text("Filename,Size,Date Modified,Date Created,Attributes\n")

    sanitized, warnings = sanitize_settings_data(
        {"efu_files": [str(efu), str(tmp_path / "missing.efu"), ""]},
        DEFAULTS,
    )

    assert sanitized["efu_files"] == [str(efu)]
    assert any("Ignored missing EFU file" in warning for warning in warnings)
    assert any("empty or invalid EFU" in warning for warning in warnings)


def test_invalid_efu_refresh_interval_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"efu_refresh_interval_minutes": 2000},
        DEFAULTS,
    )

    assert sanitized["efu_refresh_interval_minutes"] == 0
    assert any("efu_refresh_interval_minutes reset" in warning for warning in warnings)


def test_content_index_settings_are_validated(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()

    sanitized, warnings = sanitize_settings_data(
        {
            "content_index_roots": [str(root), str(tmp_path / "missing"), ""],
            "content_index_extensions": [" TXT", ".Pdf", "", 42],
            "content_index_max_cache_mb": 0,
        },
        DEFAULTS,
    )

    assert sanitized["content_index_roots"] == [str(root)]
    assert sanitized["content_index_extensions"] == ["pdf", "txt"]
    assert sanitized["content_index_max_cache_mb"] == 512
    assert any("content_index_max_cache_mb reset" in warning for warning in warnings)
    assert any("Ignored missing content index root" in warning for warning in warnings)


def test_invalid_index_case_mode_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"index_case_mode": "folded"},
        DEFAULTS,
    )

    assert sanitized["index_case_mode"] == "smart"
    assert any("index_case_mode reset" in warning for warning in warnings)


def test_invalid_theme_name_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"theme_name": "solarized"},
        DEFAULTS,
    )

    assert sanitized["theme_name"] == "mocha"
    assert any("theme_name reset" in warning for warning in warnings)


def test_invalid_language_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"language": "pirate"},
        DEFAULTS,
    )

    assert sanitized["language"] == "en"
    assert any("language reset" in warning for warning in warnings)


def test_exclude_rule_settings_are_validated():
    sanitized, warnings = sanitize_settings_data(
        {
            "exclude_globs": [" *.tmp ", "", 7],
            "exclude_regexes": [r"cache\d+", "(", None],
            "exclude_attribute_mask": str(FILE_ATTRIBUTE_REPARSE_POINT),
        },
        DEFAULTS,
    )

    assert sanitized["exclude_globs"] == ["*.tmp"]
    assert sanitized["exclude_regexes"] == [r"cache\d+"]
    assert sanitized["exclude_attribute_mask"] == FILE_ATTRIBUTE_REPARSE_POINT
    assert any("invalid exclude_globs entry" in warning for warning in warnings)
    assert any("invalid exclude_regexes entry" in warning for warning in warnings)
    assert any("Ignored invalid exclude_regexes entry" in warning for warning in warnings)


def test_invalid_exclude_attribute_mask_resets_to_default():
    sanitized, warnings = sanitize_settings_data(
        {"exclude_attribute_mask": 0x1_0000_0000},
        DEFAULTS,
    )

    assert sanitized["exclude_attribute_mask"] == 0
    assert any("exclude_attribute_mask reset" in warning for warning in warnings)


def test_exclude_attribute_text_round_trips_codes_and_numeric_masks():
    mask = attribute_text_to_mask("H;L;0x20")

    assert mask == FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_REPARSE_POINT | 0x20
    assert split_rule_text(" *.tmp ;\ncache*;;") == ["*.tmp", "cache*"]
    assert attribute_mask_to_text(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_REPARSE_POINT) == "H;L"


def test_network_share_roots_are_normalized_without_online_check():
    sanitized, warnings = sanitize_settings_data(
        {
            "network_share_roots": [
                "//server/share/folder/",
                "C:\\not-a-share",
                "\\\\server-only",
            ]
        },
        DEFAULTS,
    )

    assert sanitized["network_share_roots"] == ["\\\\server\\share\\folder"]
    assert any("invalid network_share_roots entry" in warning for warning in warnings)


def test_migrate_legacy_settings_adds_schema_version():
    migrated, warnings = migrate_settings_data({"http_port": 9090}, DEFAULTS)

    assert migrated["schema_version"] == SETTINGS_SCHEMA_VERSION
    assert migrated["http_port"] == 9090
    assert any("schema version" in warning for warning in warnings)


def test_future_settings_schema_is_rejected():
    with pytest.raises(SettingsMigrationError):
        migrate_settings_data({"schema_version": SETTINGS_SCHEMA_VERSION + 1}, DEFAULTS)


def test_settings_export_includes_schema_version(tmp_path):
    settings = Settings(http_port=9090)
    target = tmp_path / "settings.json"

    settings.export_to_file(str(target))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["schema_version"] == SETTINGS_SCHEMA_VERSION
    assert data["http_port"] == 9090


def test_settings_load_migrates_legacy_file_with_backup(monkeypatch, tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"http_port": 9090}), encoding="utf-8")
    monkeypatch.setattr(settings_dialog, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings_dialog, "SETTINGS_FILE", settings_file)

    loaded = Settings.load()

    migrated = json.loads(settings_file.read_text(encoding="utf-8"))
    backups = list(tmp_path.glob("settings.json.*.bak"))
    assert loaded.schema_version == SETTINGS_SCHEMA_VERSION
    assert loaded.http_port == 9090
    assert migrated["schema_version"] == SETTINGS_SCHEMA_VERSION
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == {"http_port": 9090}


def test_settings_save_backs_up_existing_profile(monkeypatch, tmp_path):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps({"schema_version": SETTINGS_SCHEMA_VERSION, "http_port": 8080}), encoding="utf-8")
    monkeypatch.setattr(settings_dialog, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings_dialog, "SETTINGS_FILE", settings_file)

    Settings(http_port=9090).save()

    backups = list(tmp_path.glob("settings.json.*.bak"))
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))["http_port"] == 8080
    assert saved["http_port"] == 9090


def test_settings_import_rolls_back_on_invalid_profile(tmp_path):
    current = Settings(http_port=9090, http_bind="127.0.0.2")
    incoming = tmp_path / "future.json"
    incoming.write_text(
        json.dumps({"schema_version": SETTINGS_SCHEMA_VERSION + 1, "http_port": 7070}),
        encoding="utf-8",
    )

    restored, errors = Settings.import_with_rollback(str(incoming), current)

    assert restored.http_port == 9090
    assert restored.http_bind == "127.0.0.2"
    assert errors
