"""Tests for persisted settings validation."""

from core.ntfs import FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_REPARSE_POINT
from gui.settings_dialog import attribute_mask_to_text, attribute_text_to_mask, split_rule_text
from gui.settings_validation import sanitize_settings_data


DEFAULTS = {
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
