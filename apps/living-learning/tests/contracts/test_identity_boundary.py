"""Portal-ready identity boundary (network-free).

The verifier protocol, the fake/rejecting implementations, and fail-closed
behavior. No Firebase SDK is involved; the subject is never used as a learner id.
"""

from __future__ import annotations

import pytest

from app.identity import (
    FakeIdentityVerifier,
    IdentityPrincipal,
    IdentityVerifier,
    InvalidTokenError,
    RejectingIdentityVerifier,
    get_identity_verifier,
    reset_identity_verifier,
    set_identity_verifier,
)


def _principal(subject: str = "uid-1") -> IdentityPrincipal:
    return IdentityPrincipal(
        issuer="ai-revenue-lab-identity",
        subject=subject,
        email="learner@example.com",
        email_verified=True,
        claims={},
    )


def test_fake_verifier_returns_registered_principal():
    verifier = FakeIdentityVerifier({"token-a": _principal("uid-1")})
    principal = verifier.verify_bearer_token("token-a")
    assert principal.subject == "uid-1"
    assert principal.issuer == "ai-revenue-lab-identity"


def test_fake_verifier_rejects_unknown_token():
    verifier = FakeIdentityVerifier({"token-a": _principal()})
    with pytest.raises(InvalidTokenError):
        verifier.verify_bearer_token("token-unknown")


def test_empty_fake_verifier_rejects_everything():
    verifier = FakeIdentityVerifier()
    with pytest.raises(InvalidTokenError):
        verifier.verify_bearer_token("any-token")


def test_rejecting_verifier_rejects_all():
    verifier = RejectingIdentityVerifier()
    with pytest.raises(InvalidTokenError):
        verifier.verify_bearer_token("any-token")


def test_verifiers_satisfy_protocol():
    assert isinstance(FakeIdentityVerifier(), IdentityVerifier)
    assert isinstance(RejectingIdentityVerifier(), IdentityVerifier)


def test_default_verifier_is_fail_closed():
    reset_identity_verifier()
    try:
        verifier = get_identity_verifier()
        with pytest.raises(InvalidTokenError):
            verifier.verify_bearer_token("any-token")
    finally:
        reset_identity_verifier()


def test_set_and_reset_verifier():
    reset_identity_verifier()
    try:
        fake = FakeIdentityVerifier({"t": _principal("uid-9")})
        set_identity_verifier(fake)
        assert get_identity_verifier().verify_bearer_token("t").subject == "uid-9"
    finally:
        reset_identity_verifier()
    # After reset, fail-closed again.
    with pytest.raises(InvalidTokenError):
        get_identity_verifier().verify_bearer_token("t")
