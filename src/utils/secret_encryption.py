"""
Optional Fernet encryption for sensitive connection config fields (e.g. WhatsApp tokens).
When SECRET_ENCRYPTION_KEY is not set, values are stored as-is (legacy behaviour).
"""
from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


def _fernet():
    try:
        from cryptography.fernet import Fernet
        from ..config import settings

        raw = getattr(settings, "SECRET_ENCRYPTION_KEY", None) or ""
        if not raw:
            return None
        # Derive 32-byte url-safe key from configured secret
        digest = hashlib.sha256(raw.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
        return Fernet(key)
    except Exception as exc:
        logger.debug("Token encryption unavailable: %s", exc)
        return None


def encrypt_value(value: Optional[str]) -> Optional[str]:
    if not value or str(value).startswith(_PREFIX):
        return value
    f = _fernet()
    if not f:
        return value
    try:
        token = f.encrypt(str(value).encode()).decode()
        return f"{_PREFIX}{token}"
    except Exception:
        return value


def decrypt_value(value: Optional[str]) -> Optional[str]:
    if not value or not str(value).startswith(_PREFIX):
        return value
    f = _fernet()
    if not f:
        logger.warning("Encrypted token present but SECRET_ENCRYPTION_KEY not configured")
        return value
    try:
        payload = str(value)[len(_PREFIX):]
        return f.decrypt(payload.encode()).decode()
    except Exception:
        return value


def encrypt_connection_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Encrypt access_token in connection config before DB persist."""
    if not config:
        return config
    out = dict(config)
    if "access_token" in out and out["access_token"]:
        out["access_token"] = encrypt_value(str(out["access_token"]))
    return out


def decrypt_connection_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Decrypt access_token when reading connection config."""
    if not config:
        return config
    out = dict(config)
    if "access_token" in out and out["access_token"]:
        out["access_token"] = decrypt_value(str(out["access_token"]))
    return out
