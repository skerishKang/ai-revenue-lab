from __future__ import annotations

import re

import pytest

from google_oauth_random import production_google_oauth_token, safe_dict

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~\-]{43,128}$")


def test_production_random_source_always_meets_safe_reference_contract():
    for size in (24, 32):
        for _ in range(256):
            token = production_google_oauth_token(size)
            assert token.startswith("r")
            assert _SAFE_REF_RE.fullmatch(token)


def test_production_random_source_always_meets_pkce_contract():
    for _ in range(256):
        token = production_google_oauth_token(64)
        assert token.startswith("r")
        assert _PKCE_VERIFIER_RE.fullmatch(token)


def test_unreviewed_token_size_fails_closed():
    for size in (0, 1, 16, 48, 96, True):
        with pytest.raises(ValueError):
            production_google_oauth_token(size)


def test_public_projection_contains_no_generated_token():
    projection = safe_dict()
    assert projection == {
        "cryptographic_random_source": "secrets.token_urlsafe",
        "safe_leading_alnum_prefix": True,
        "reviewed_sizes": [24, 32, 64],
        "retry_loop": False,
        "raw_token_public": False,
    }
