"""Firebase IdentityVerifier contracts (firebase_admin mocked, network-free).

All verification failures must collapse to a generic ``InvalidTokenError`` that
carries no token, claims, UID, email, or exception detail.
"""

from __future__ import annotations

import sys
import types

import pytest

from app.identity import (
    FIREBASE_ISSUER,
    FirebaseIdentityVerifier,
    IdentityPrincipal,
    InvalidTokenError,
)


def _install_fake_firebase_admin(decoded_by_token: dict, raise_for: set | None = None):
    """Install a fake firebase_admin into sys.modules for the verifier to import."""
    raise_for = raise_for or set()

    firebase_admin = types.ModuleType("firebase_admin")
    credentials = types.ModuleType("firebase_admin.credentials")
    auth = types.ModuleType("firebase_admin.auth")

    class _Cert:
        pass

    credentials.Certificate = lambda *_a, **_k: _Cert()
    credentials.ApplicationDefault = lambda *_a, **_k: _Cert()

    def _initialize_app(cred, options=None):
        return object()

    def _get_app():
        return object()

    firebase_admin.initialize_app = _initialize_app
    firebase_admin.get_app = _get_app
    firebase_admin.credentials = credentials

    def verify_id_token(token, app=None, check_revoked=False):
        if token in raise_for:
            raise ValueError("simulated verification failure")
        if token not in decoded_by_token:
            raise ValueError("unknown token")
        return decoded_by_token[token]

    auth.verify_id_token = verify_id_token
    firebase_admin.auth = auth

    saved = {k: sys.modules.get(k) for k in ("firebase_admin", "firebase_admin.credentials", "firebase_admin.auth")}
    sys.modules["firebase_admin"] = firebase_admin
    sys.modules["firebase_admin.credentials"] = credentials
    sys.modules["firebase_admin.auth"] = auth
    return saved


def _restore(saved):
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def test_valid_token_returns_principal(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    decoded = {
        "good-token": {"uid": "uid-123", "sub": "uid-123", "email": "a@b.example", "email_verified": True}
    }
    saved = _install_fake_firebase_admin(decoded)
    try:
        verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity")
        principal = verifier.verify_bearer_token("good-token")
        assert isinstance(principal, IdentityPrincipal)
        assert principal.issuer == FIREBASE_ISSUER
        assert principal.subject == "uid-123"
        assert principal.email == "a@b.example"
        assert principal.email_verified is True
    finally:
        _restore(saved)


def test_empty_token_rejected():
    verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity")
    with pytest.raises(InvalidTokenError):
        verifier.verify_bearer_token("")


def test_malformed_token_generic_error(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    saved = _install_fake_firebase_admin({}, raise_for={"bad-token"})
    try:
        verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity")
        with pytest.raises(InvalidTokenError) as exc:
            verifier.verify_bearer_token("bad-token")
        # Generic message — no detail leaked.
        assert "simulated" not in str(exc.value)
        assert "bad-token" not in str(exc.value)
    finally:
        _restore(saved)


def test_missing_subject_rejected(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    saved = _install_fake_firebase_admin({"no-sub": {"email": "a@b.example", "email_verified": True}})
    try:
        verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity")
        with pytest.raises(InvalidTokenError):
            verifier.verify_bearer_token("no-sub")
    finally:
        _restore(saved)


def test_unverified_email_rejected(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    decoded = {"unverified": {"uid": "u", "email": "a@b.example", "email_verified": False}}
    saved = _install_fake_firebase_admin(decoded)
    try:
        verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity")
        with pytest.raises(InvalidTokenError):
            verifier.verify_bearer_token("unverified")
    finally:
        _restore(saved)


def test_revoked_token_check_enabled(monkeypatch):
    # check_revoked=True is passed to the SDK; a revoked token raises in the SDK
    # and collapses to a generic InvalidTokenError.
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT_JSON", '{"type":"service_account"}')
    saved = _install_fake_firebase_admin({}, raise_for={"revoked-token"})
    try:
        verifier = FirebaseIdentityVerifier("ai-revenue-lab-identity", check_revoked=True)
        with pytest.raises(InvalidTokenError):
            verifier.verify_bearer_token("revoked-token")
    finally:
        _restore(saved)
