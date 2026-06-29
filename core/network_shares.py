"""SMB network share helpers for QuickFind indexing."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger('QuickFind.NetworkShares')


@dataclass(frozen=True)
class NetworkCredential:
    username: str
    password: str


def normalize_network_root(root: str) -> str:
    """Normalize a UNC root or subfolder path without requiring it to be online."""
    path = (root or "").strip().replace("/", "\\").rstrip("\\")
    if not path.startswith("\\\\"):
        raise ValueError("Network share must be a UNC path such as \\\\server\\share")

    parts = [part for part in path[2:].split("\\") if part]
    if len(parts) < 2:
        raise ValueError("Network share must include both server and share name")
    return "\\\\" + "\\".join(parts)


def network_share_root(root: str) -> str:
    """Return the SMB share root (\\\\server\\share) for a UNC path."""
    normalized = normalize_network_root(root)
    parts = normalized[2:].split("\\")
    return f"\\\\{parts[0]}\\{parts[1]}"


def network_source_key(root: str) -> str:
    """Return a stable cache/index source key for a UNC path."""
    normalized = normalize_network_root(root)
    digest = hashlib.sha1(normalized.lower().encode("utf-8")).hexdigest()[:12]
    return f"UNC:{digest}"


def credential_target(root: str) -> str:
    return f"QuickFind SMB:{network_share_root(root)}"


def _decode_credential_blob(blob) -> str:
    if blob is None:
        return ""
    if isinstance(blob, str):
        return blob
    for encoding in ("utf-16-le", "utf-8"):
        try:
            return bytes(blob).decode(encoding).rstrip("\x00")
        except UnicodeDecodeError:
            continue
    return ""


def read_network_credential(root: str) -> NetworkCredential | None:
    """Read a stored network credential from Windows Credential Manager."""
    try:
        import win32cred
    except ImportError:
        return None

    try:
        credential = win32cred.CredRead(
            credential_target(root),
            win32cred.CRED_TYPE_GENERIC,
        )
    except Exception:
        return None

    username = credential.get("UserName") or ""
    password = _decode_credential_blob(credential.get("CredentialBlob"))
    if not username and not password:
        return None
    return NetworkCredential(username=username, password=password)


def save_network_credential(root: str, username: str, password: str) -> None:
    """Store an SMB credential in Windows Credential Manager."""
    try:
        import win32cred
    except ImportError as exc:
        raise RuntimeError("Windows Credential Manager support requires pywin32") from exc

    target = credential_target(root)
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": target,
            "UserName": username.strip(),
            "CredentialBlob": (password or "").encode("utf-16-le"),
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
        },
        0,
    )


def delete_network_credential(root: str) -> None:
    """Delete a stored SMB credential if present."""
    try:
        import win32cred
    except ImportError:
        return

    try:
        win32cred.CredDelete(credential_target(root), win32cred.CRED_TYPE_GENERIC)
    except Exception:
        return


def connect_network_share(root: str) -> bool:
    """Temporarily connect to a UNC share using stored credentials, if any."""
    credential = read_network_credential(root)
    if credential is None:
        return False

    try:
        import pywintypes
        import win32netcon
        import win32wnet
    except ImportError as exc:
        raise RuntimeError("SMB credential connection requires pywin32") from exc

    share = network_share_root(root)
    resource = win32wnet.NETRESOURCE()
    resource.dwType = win32netcon.RESOURCETYPE_DISK
    resource.lpRemoteName = share
    try:
        win32wnet.WNetAddConnection2(
            resource,
            credential.password,
            credential.username or None,
            win32netcon.CONNECT_TEMPORARY,
        )
        return True
    except pywintypes.error as exc:
        if getattr(exc, "winerror", 0) in {85, 1219}:
            logger.debug("Network share already connected: %s", share)
            return True
        raise
