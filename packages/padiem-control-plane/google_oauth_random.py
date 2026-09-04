from __future__ import annotations

import re
import secrets

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~\-]{43,128}$")
_ALLOWED_TOKEN_SIZES = frozenset({24, 32, 64})


def production_google_oauth_token(size: int) -> str:
    """Generate a Worker-side OAuth token with a deterministic safe leading char.

    ``secrets.token_urlsafe`` may legally begin with ``-`` or ``_``. B54 safe
    references require an alphanumeric first character, while PKCE accepts the
    prefixed result. Production therefore prefixes every reviewed token size
    with ``r`` instead of retrying or weakening the safe-ref contract.
    """

    if type(size) is not int or size not in _ALLOWED_TOKEN_SIZES:
        raise ValueError("Google OAuth token size is not reviewed")
    value = "r" + secrets.token_urlsafe(size)
    if size in (24, 32):
        if _SAFE_REF_RE.fullmatch(value) is None:
            raise RuntimeError("generated Google OAuth safe reference is invalid")
    elif _PKCE_VERIFIER_RE.fullmatch(value) is None:
        raise RuntimeError("generated Google OAuth PKCE verifier is invalid")
    return value


def safe_dict() -> dict[str, object]:
    return {
        "cryptographic_random_source": "secrets.token_urlsafe",
        "safe_leading_alnum_prefix": True,
        "reviewed_sizes": sorted(_ALLOWED_TOKEN_SIZES),
        "retry_loop": False,
        "raw_token_public": False,
    }


PRODUCTION_GOOGLE_OAUTH_RANDOM_SOURCE_READY = True
