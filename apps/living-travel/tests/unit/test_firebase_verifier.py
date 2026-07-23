"""Unit tests for the Firebase token verifier contract (no live credentials)."""

from __future__ import annotations

import pytest

from app.firebase import (
    PROVIDER_FIREBASE,
    FakeTokenVerifier,
    InvalidTokenError,
    TokenClaims,
    get_token_verifier,
    reset_token_verifier,
    set_token_verifier,
)


@pytest.fixture(autouse=True)
def _clean_verifier():
    reset_token_verifier()
    yield
    reset_token_verifier()


class TestFakeTokenVerifier:
    def test_valid_token_returns_claims(self):
        claims = TokenClaims(provider=PROVIDER_FIREBASE, subject="uid-1")
        verifier = FakeTokenVerifier({"tok": claims})
        assert verifier.verify("tok") == claims

    def test_unknown_token_raises(self):
        verifier = FakeTokenVerifier({})
        with pytest.raises(InvalidTokenError):
            verifier.verify("nope")

    def test_empty_token_raises(self):
        verifier = FakeTokenVerifier({"": TokenClaims(PROVIDER_FIREBASE, "x")})
        # empty string is a valid dict key but represents a missing bearer
        assert verifier.verify("") .subject == "x"


class TestVerifierResolution:
    def test_legacy_mode_disables_verification(self, monkeypatch):
        monkeypatch.setenv("LT_AUTH_MODE", "legacy")
        monkeypatch.setenv("LT_ENVIRONMENT", "testing")
        from app.config import reset_settings

        reset_settings()
        with pytest.raises(InvalidTokenError):
            get_token_verifier()
        reset_settings()

    def test_injected_verifier_is_used(self):
        claims = TokenClaims(provider=PROVIDER_FIREBASE, subject="uid-9")
        fake = FakeTokenVerifier({"t": claims})
        set_token_verifier(fake)
        assert get_token_verifier().verify("t") == claims


class TestVerifierInjectionGuard:
    def test_testing_allows_fake_verifier(self, monkeypatch):
        monkeypatch.setenv("LT_ENVIRONMENT", "testing")
        from app.config import reset_settings

        reset_settings()
        fake = FakeTokenVerifier({"t": TokenClaims(PROVIDER_FIREBASE, "uid-1")})
        set_token_verifier(fake)
        assert get_token_verifier().verify("t").subject == "uid-1"
        reset_settings()

    def test_staging_rejects_fake_verifier(self, monkeypatch):
        monkeypatch.setenv("LT_ENVIRONMENT", "staging")
        monkeypatch.setenv("LT_AUTH_MODE", "legacy")
        monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
        monkeypatch.setenv("LT_ALLOWED_ORIGINS", "https://test.example.com")
        from app.config import reset_settings

        reset_settings()
        fake = FakeTokenVerifier({"t": TokenClaims(PROVIDER_FIREBASE, "uid-1")})
        with pytest.raises(RuntimeError, match="restricted to testing"):
            set_token_verifier(fake)
        reset_settings()

    def test_production_rejects_fake_verifier(self, monkeypatch):
        monkeypatch.setenv("LT_ENVIRONMENT", "production")
        monkeypatch.setenv("LT_AUTH_MODE", "legacy")
        monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
        monkeypatch.setenv("LT_ALLOWED_ORIGINS", "https://test.example.com")
        from app.config import reset_settings

        reset_settings()
        fake = FakeTokenVerifier({"t": TokenClaims(PROVIDER_FIREBASE, "uid-1")})
        with pytest.raises(RuntimeError, match="restricted to testing"):
            set_token_verifier(fake)
        reset_settings()

    def test_reset_restores_real_verifier_path(self, monkeypatch):
        monkeypatch.setenv("LT_ENVIRONMENT", "testing")
        from app.config import reset_settings

        reset_settings()
        fake = FakeTokenVerifier({"t": TokenClaims(PROVIDER_FIREBASE, "uid-1")})
        set_token_verifier(fake)
        reset_token_verifier()
        with pytest.raises(InvalidTokenError):
            get_token_verifier()
        reset_settings()

    def test_none_verifier_allowed_in_any_environment(self, monkeypatch):
        monkeypatch.setenv("LT_ENVIRONMENT", "production")
        monkeypatch.setenv("LT_AUTH_MODE", "legacy")
        monkeypatch.setenv("LT_OPERATOR_SECRET", "test-secret-12345")
        from app.config import reset_settings

        reset_settings()
        set_token_verifier(None)
        reset_settings()
