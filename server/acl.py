"""Explicit ACL boundary for shared read-only search server.

Each token maps to a set of allowed filesystem roots. Results outside
the token's roots are filtered before returning. Denied paths are logged
through the audit system. Shared mode is disabled by default.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True)
class TokenACL:
    """Access control entry for a single auth token."""
    token: str
    label: str = ""
    allowed_roots: tuple[str, ...] = ()
    read_only: bool = True

    @property
    def normalized_roots(self) -> tuple[str, ...]:
        return tuple(
            os.path.normcase(os.path.abspath(root)) for root in self.allowed_roots
        )


@dataclass
class SharedServerConfig:
    """Configuration for shared search mode. Disabled by default."""
    enabled: bool = False
    token_acls: list[TokenACL] = field(default_factory=list)

    def acl_for_token(self, token: str) -> TokenACL | None:
        for acl in self.token_acls:
            if secrets.compare_digest(acl.token, token):
                return acl
        return None


@dataclass(frozen=True)
class ACLFilterResult:
    allowed: list[dict] = field(default_factory=list)
    denied_count: int = 0


def path_within_roots(path: str, roots: Sequence[str]) -> bool:
    """Check if a resolved path falls within any of the allowed roots."""
    if not roots:
        return True
    norm_path = os.path.normcase(os.path.realpath(path))
    for root in roots:
        norm_root = os.path.normcase(os.path.realpath(root))
        if not norm_root.endswith(os.sep):
            norm_root += os.sep
        if norm_path.startswith(norm_root) or norm_path == norm_root.rstrip(os.sep):
            return True
    return False


def filter_results_by_acl(
    results: Sequence[dict],
    acl: TokenACL | None,
) -> ACLFilterResult:
    """Filter search result payloads by the token's allowed roots."""
    if acl is None or not acl.allowed_roots:
        return ACLFilterResult(allowed=list(results), denied_count=0)

    roots = acl.normalized_roots
    allowed = []
    denied = 0
    for result in results:
        path = result.get("path", "")
        if path_within_roots(path, roots):
            allowed.append(result)
        else:
            denied += 1

    return ACLFilterResult(allowed=allowed, denied_count=denied)


def validate_config(config: SharedServerConfig) -> list[str]:
    """Validate a shared server config. Returns list of error messages."""
    errors = []
    if not config.enabled:
        return errors

    if not config.token_acls:
        errors.append("Shared mode enabled but no token ACLs configured")
        return errors

    seen_tokens = set()
    for i, acl in enumerate(config.token_acls):
        if not acl.token:
            errors.append(f"Token ACL {i}: empty token")
        if acl.token in seen_tokens:
            errors.append(f"Token ACL {i}: duplicate token")
        seen_tokens.add(acl.token)
        if not acl.allowed_roots:
            errors.append(f"Token ACL {i} ({acl.label or acl.token[:8]}): no allowed roots")
        for root in acl.allowed_roots:
            if not os.path.isabs(root):
                errors.append(f"Token ACL {i}: root must be absolute: {root}")

    return errors
