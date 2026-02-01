"""
Secure API key storage using the system keychain.

Uses the `keyring` library when available. Falls back to no storage if missing.
"""

from __future__ import annotations

from typing import Optional


SERVICE_NAME = "CommentaryGenerator"
ACCOUNT_NAME = "openai_api_key"

try:
    import keyring  # type: ignore
    from keyring.errors import PasswordDeleteError  # type: ignore

    _KEYRING_AVAILABLE = True
except Exception:  # pragma: no cover - environment dependent
    keyring = None
    PasswordDeleteError = Exception  # type: ignore
    _KEYRING_AVAILABLE = False


def keyring_available() -> bool:
    """Return True if the keyring backend is available."""
    return _KEYRING_AVAILABLE


def get_api_key() -> str:
    """Get the API key from the system keychain."""
    if not _KEYRING_AVAILABLE:
        return ""
    try:
        value = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
        return value or ""
    except Exception:
        return ""


def set_api_key(api_key: str) -> bool:
    """Store the API key in the system keychain."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, api_key)
        return True
    except Exception:
        return False


def delete_api_key() -> bool:
    """Delete the API key from the system keychain."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)
        return True
    except PasswordDeleteError:
        return True
    except Exception:
        return False
