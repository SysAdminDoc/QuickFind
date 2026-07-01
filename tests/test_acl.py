"""Tests for shared read-only search server ACL boundary."""

from server.acl import (
    ACLFilterResult,
    SharedServerConfig,
    TokenACL,
    filter_results_by_acl,
    path_within_roots,
    validate_config,
)


def test_path_within_roots_matches_subdirectory():
    assert path_within_roots("C:\\docs\\report.pdf", ["C:\\docs"])
    assert path_within_roots("C:\\docs\\sub\\file.txt", ["C:\\docs"])


def test_path_outside_roots_denied():
    assert not path_within_roots("C:\\private\\secret.txt", ["C:\\docs"])


def test_path_within_any_root():
    roots = ["C:\\docs", "D:\\shared"]
    assert path_within_roots("D:\\shared\\file.txt", roots)
    assert not path_within_roots("E:\\other\\file.txt", roots)


def test_empty_roots_allows_everything():
    assert path_within_roots("C:\\anything\\here.txt", [])


def test_filter_results_without_acl_allows_all():
    results = [{"path": "C:\\a.txt"}, {"path": "D:\\b.txt"}]
    filtered = filter_results_by_acl(results, None)
    assert len(filtered.allowed) == 2
    assert filtered.denied_count == 0


def test_filter_results_with_acl_blocks_outside_roots():
    acl = TokenACL(token="abc", allowed_roots=("C:\\docs",))
    results = [
        {"path": "C:\\docs\\report.pdf"},
        {"path": "C:\\private\\secret.txt"},
        {"path": "C:\\docs\\sub\\notes.txt"},
    ]
    filtered = filter_results_by_acl(results, acl)
    assert len(filtered.allowed) == 2
    assert filtered.denied_count == 1
    assert all("docs" in r["path"] for r in filtered.allowed)


def test_filter_results_with_empty_roots_allows_all():
    acl = TokenACL(token="abc", allowed_roots=())
    results = [{"path": "C:\\a.txt"}, {"path": "D:\\b.txt"}]
    filtered = filter_results_by_acl(results, acl)
    assert len(filtered.allowed) == 2


def test_config_acl_for_token_lookup():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="token_a", label="Team A", allowed_roots=("C:\\team_a",)),
        TokenACL(token="token_b", label="Team B", allowed_roots=("D:\\team_b",)),
    ])
    acl = config.acl_for_token("token_a")
    assert acl is not None
    assert acl.label == "Team A"

    assert config.acl_for_token("unknown") is None


def test_shared_mode_disabled_by_default():
    config = SharedServerConfig()
    assert not config.enabled
    assert config.token_acls == []


def test_validate_disabled_config_passes():
    config = SharedServerConfig(enabled=False)
    errors = validate_config(config)
    assert errors == []


def test_validate_enabled_but_no_tokens():
    config = SharedServerConfig(enabled=True, token_acls=[])
    errors = validate_config(config)
    assert any("no token ACLs" in e for e in errors)


def test_validate_empty_token():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="", allowed_roots=("C:\\docs",)),
    ])
    errors = validate_config(config)
    assert any("empty token" in e for e in errors)


def test_validate_no_roots_warns():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="abc", allowed_roots=()),
    ])
    errors = validate_config(config)
    assert any("no allowed roots" in e for e in errors)


def test_validate_relative_root_rejected():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="abc", allowed_roots=("relative/path",)),
    ])
    errors = validate_config(config)
    assert any("absolute" in e for e in errors)


def test_validate_duplicate_tokens():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="same", allowed_roots=("C:\\a",)),
        TokenACL(token="same", allowed_roots=("C:\\b",)),
    ])
    errors = validate_config(config)
    assert any("duplicate" in e for e in errors)


def test_validate_good_config():
    config = SharedServerConfig(enabled=True, token_acls=[
        TokenACL(token="token_a", label="Team A", allowed_roots=("C:\\team_a",)),
        TokenACL(token="token_b", label="Team B", allowed_roots=("D:\\team_b",)),
    ])
    errors = validate_config(config)
    assert errors == []


def test_denied_paths_never_leak_in_results():
    acl = TokenACL(token="reader", allowed_roots=("C:\\public",))
    results = [
        {"path": "C:\\public\\readme.txt", "name": "readme.txt"},
        {"path": "C:\\secret\\passwords.txt", "name": "passwords.txt"},
        {"path": "C:\\public\\docs\\guide.pdf", "name": "guide.pdf"},
    ]
    filtered = filter_results_by_acl(results, acl)
    for r in filtered.allowed:
        assert "secret" not in r["path"]
        assert "passwords" not in r["name"]
    assert filtered.denied_count == 1
