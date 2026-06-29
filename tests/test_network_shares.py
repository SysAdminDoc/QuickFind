"""Tests for SMB network share helpers."""

from core.network_shares import (
    credential_target,
    network_share_root,
    network_source_key,
    normalize_network_root,
)


def test_normalize_network_root_accepts_unc_subfolders():
    assert normalize_network_root("//server/share/folder/") == "\\\\server\\share\\folder"


def test_network_share_root_extracts_server_share():
    assert network_share_root("\\\\server\\share\\folder") == "\\\\server\\share"


def test_network_source_key_is_stable_and_case_insensitive():
    assert network_source_key("\\\\SERVER\\Share") == network_source_key("\\\\server\\share")


def test_credential_target_uses_share_root():
    assert credential_target("\\\\server\\share\\folder") == "QuickFind SMB:\\\\server\\share"
