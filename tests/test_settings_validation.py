"""Tests for persisted settings validation."""

from gui.settings_validation import sanitize_settings_data


DEFAULTS = {
    "http_port": 8080,
    "usn_poll_interval_ms": 1000,
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
}


def test_invalid_port_resets_to_default():
    sanitized, warnings = sanitize_settings_data({"http_port": 70000}, DEFAULTS)

    assert sanitized["http_port"] == 8080
    assert any("http_port reset" in warning for warning in warnings)


def test_blank_bind_resets_to_loopback():
    sanitized, warnings = sanitize_settings_data({"http_bind": "   "}, DEFAULTS)

    assert sanitized["http_bind"] == "127.0.0.1"
    assert any("http_bind reset" in warning for warning in warnings)


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
