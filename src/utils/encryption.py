"""
Encryption utilities for securing sensitive data at rest.
Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).

The encryption key is derived from the application's SECRET_KEY.
"""
import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """
    Derive a Fernet key from the app SECRET_KEY.
    
    Fernet requires a 32-byte URL-safe base64-encoded key.
    We derive it by hashing the SECRET_KEY with SHA-256.
    """
    raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt_value(plaintext: Optional[str]) -> Optional[str]:
    """
    Encrypt a plaintext string. Returns URL-safe base64-encoded ciphertext.
    Returns None if input is None or empty.
    """
    if not plaintext:
        return plaintext
    
    try:
        f = _get_fernet()
        return f.encrypt(plaintext.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt_value(ciphertext: Optional[str]) -> Optional[str]:
    """
    Decrypt a Fernet ciphertext string back to plaintext.
    Returns None if input is None or empty.
    
    If decryption fails (e.g. data was stored before encryption was enabled),
    returns the original value as-is and logs a warning. This allows graceful
    migration of pre-existing plaintext data.
    """
    if not ciphertext:
        return ciphertext
    
    try:
        f = _get_fernet()
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Likely a pre-existing plaintext value from before encryption was enabled.
        # Return as-is so existing configs don't break.
        logger.warning("Decryption failed — value may be stored as plaintext (pre-encryption migration). Returning as-is.")
        return ciphertext
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise


def mask_value(value: Optional[str], visible_chars: int = 4) -> Optional[str]:
    """
    Mask a sensitive value, keeping only the first and last N characters visible.
    Example: 'abc123xyz789' → 'abc1••••••89'
    """
    if not value:
        return value
    
    if len(value) <= visible_chars * 2:
        return "•" * len(value)
    
    return value[:visible_chars] + "•" * (len(value) - visible_chars * 2) + value[-visible_chars:]
