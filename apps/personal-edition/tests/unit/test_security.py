import hmac

import pytest

from app import security


class TestTokenGeneration:
    def test_generates_minimum_32_bytes(self):
        token = security.generate_token()
        import base64

        decoded = base64.urlsafe_b64decode(token + "==")
        assert len(decoded) >= 32

    def test_token_not_empty_and_url_safe(self):
        token = security.generate_token()
        assert token
        assert all(c.isalnum() or c in ("-", "_") for c in token)

    def test_token_is_string(self):
        assert isinstance(security.generate_token(), str)


class TestHashToken:
    def test_deterministic_hash(self):
        token = security.generate_token()
        h1 = security.hash_token(token)
        h2 = security.hash_token(token)
        assert h1 == h2

    def test_different_tokens_different_hashes(self):
        t1 = security.generate_token()
        t2 = security.generate_token()
        assert security.hash_token(t1) != security.hash_token(t2)

    def test_hash_is_64_char_lowercase_hex(self):
        token = security.generate_token()
        h = security.hash_token(token)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_empty_token_rejected(self):
        with pytest.raises(ValueError):
            security.hash_token("")

    def test_non_string_token_rejected(self):
        with pytest.raises(TypeError):
            security.hash_token(None)
        with pytest.raises(TypeError):
            security.hash_token(123)

    def test_exception_does_not_contain_raw_token(self):
        raw = security.generate_token()
        with pytest.raises(ValueError) as excinfo:
            security.hash_token("")
        assert raw not in str(excinfo.value)


class TestVerifyToken:
    def test_correct_token_verifies(self):
        token = security.generate_token()
        token_hash = security.hash_token(token)
        assert security.verify_token(token, token_hash) is True

    def test_wrong_token_fails(self):
        token = security.generate_token()
        token_hash = security.hash_token(token)
        wrong = security.generate_token()
        assert security.verify_token(wrong, token_hash) is False

    def test_wrong_hash_fails(self):
        token = security.generate_token()
        security.hash_token(token)
        wrong_hash = "a" * 64
        assert security.verify_token(token, wrong_hash) is False

    def test_non_string_token_returns_false(self):
        token_hash = security.hash_token(security.generate_token())
        assert security.verify_token(123, token_hash) is False
        assert security.verify_token(None, token_hash) is False

    def test_non_string_hash_returns_false(self):
        token = security.generate_token()
        assert security.verify_token(token, 123) is False
        assert security.verify_token(token, None) is False

    def test_uses_hmac_compare_digest(self, monkeypatch):
        calls = []
        original = hmac.compare_digest
        monkeypatch.setattr(
            hmac,
            "compare_digest",
            lambda a, b: (calls.append((a, b)), original(a, b))[1],
        )

        token = security.generate_token()
        token_hash = security.hash_token(token)
        assert security.verify_token(token, token_hash) is True
        assert len(calls) >= 1
