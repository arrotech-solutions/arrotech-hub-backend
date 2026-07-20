"""
Tests for src/utils/encryption.py — encrypt, decrypt, mask utilities.
"""
import pytest


class TestGetFernet:
    """Tests for internal _get_fernet key derivation."""

    def test_fernet_returns_instance(self):
        from src.utils.encryption import _get_fernet
        f = _get_fernet()
        assert f is not None

    def test_fernet_consistent_key(self):
        """Same SECRET_KEY should produce same Fernet instance behavior."""
        from src.utils.encryption import _get_fernet
        f1 = _get_fernet()
        f2 = _get_fernet()
        # Both should encrypt/decrypt compatibly
        ct = f1.encrypt(b"test")
        assert f2.decrypt(ct) == b"test"


class TestEncryptValue:
    def test_encrypt_none_returns_none(self):
        from src.utils.encryption import encrypt_value
        assert encrypt_value(None) is None

    def test_encrypt_empty_returns_empty(self):
        from src.utils.encryption import encrypt_value
        assert encrypt_value("") == ""

    def test_encrypt_returns_different_value(self):
        from src.utils.encryption import encrypt_value
        result = encrypt_value("secret123")
        assert result != "secret123"
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encrypt_is_nondeterministic(self):
        from src.utils.encryption import encrypt_value
        r1 = encrypt_value("test")
        r2 = encrypt_value("test")
        # Fernet produces different ciphertexts each time (due to timestamp)
        assert r1 != r2

    def test_encrypt_different_inputs(self):
        from src.utils.encryption import encrypt_value
        r1 = encrypt_value("secret1")
        r2 = encrypt_value("secret2")
        assert r1 != r2

    def test_encrypt_long_string(self):
        from src.utils.encryption import encrypt_value
        long_str = "a" * 10000
        result = encrypt_value(long_str)
        assert result is not None
        assert len(result) > 0

    def test_encrypt_special_characters(self):
        from src.utils.encryption import encrypt_value
        special = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = encrypt_value(special)
        assert result is not None
        assert result != special

    def test_encrypt_whitespace(self):
        from src.utils.encryption import encrypt_value
        result = encrypt_value("   ")
        assert result is not None
        assert result != "   "

    def test_encrypt_newlines(self):
        from src.utils.encryption import encrypt_value
        result = encrypt_value("line1\nline2\nline3")
        assert result is not None


class TestDecryptValue:
    def test_decrypt_none_returns_none(self):
        from src.utils.encryption import decrypt_value
        assert decrypt_value(None) is None

    def test_decrypt_empty_returns_empty(self):
        from src.utils.encryption import decrypt_value
        assert decrypt_value("") == ""

    def test_encrypt_then_decrypt_roundtrip(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = "my-secret-api-key-12345"
        encrypted = encrypt_value(original)
        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_decrypt_plaintext_returns_as_is(self):
        """Pre-encryption plaintext should be returned as-is (graceful migration)."""
        from src.utils.encryption import decrypt_value
        plaintext = "not-a-fernet-token"
        result = decrypt_value(plaintext)
        assert result == plaintext

    def test_roundtrip_unicode(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = "密码🔑"
        assert decrypt_value(encrypt_value(original)) == original

    def test_roundtrip_json_string(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = '{"key": "value", "nested": {"a": 1}}'
        assert decrypt_value(encrypt_value(original)) == original

    def test_roundtrip_url(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = "https://api.example.com/v1/data?key=abc&token=xyz"
        assert decrypt_value(encrypt_value(original)) == original

    def test_roundtrip_multiline(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = "line1\nline2\nline3"
        assert decrypt_value(encrypt_value(original)) == original

    def test_roundtrip_long_string(self):
        from src.utils.encryption import encrypt_value, decrypt_value
        original = "x" * 5000
        assert decrypt_value(encrypt_value(original)) == original


class TestMaskValue:
    def test_mask_none_returns_none(self):
        from src.utils.encryption import mask_value
        assert mask_value(None) is None

    def test_mask_empty_returns_empty(self):
        from src.utils.encryption import mask_value
        assert mask_value("") == ""

    def test_mask_short_string_fully_masked(self):
        from src.utils.encryption import mask_value
        result = mask_value("abcd", visible_chars=4)
        assert result == "••••"

    def test_mask_long_string(self):
        from src.utils.encryption import mask_value
        result = mask_value("abc123xyz789", visible_chars=4)
        assert result.startswith("abc1")
        assert result.endswith("z789")
        assert "••" in result

    def test_mask_custom_visible_chars(self):
        from src.utils.encryption import mask_value
        result = mask_value("0123456789", visible_chars=2)
        assert result.startswith("01")
        assert result.endswith("89")
        assert "••" in result

    def test_mask_exactly_double_visible(self):
        from src.utils.encryption import mask_value
        result = mask_value("abcdefgh", visible_chars=4)
        assert result == "••••••••"

    def test_mask_single_char(self):
        from src.utils.encryption import mask_value
        result = mask_value("a", visible_chars=4)
        assert result == "•"

    def test_mask_two_chars(self):
        from src.utils.encryption import mask_value
        result = mask_value("ab", visible_chars=4)
        assert result == "••"

    def test_mask_visible_chars_1(self):
        from src.utils.encryption import mask_value
        result = mask_value("abcdefgh", visible_chars=1)
        assert result.startswith("a")
        assert result.endswith("h")
        assert "••" in result
        assert len(result) == 8

    def test_mask_preserves_length(self):
        from src.utils.encryption import mask_value
        original = "0123456789abcdef"
        result = mask_value(original, visible_chars=4)
        assert len(result) == len(original)

    def test_mask_default_visible_chars(self):
        from src.utils.encryption import mask_value
        result = mask_value("0123456789abcdef")
        # Default visible_chars=4
        assert result.startswith("0123")
        assert result.endswith("cdef")
