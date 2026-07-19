import hashlib
import hmac
import secrets

_TOKEN_HASH_DOMAIN = b"personal-edition.participant-token.v1\x00"
TOKEN_BYTES = 32


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _compute_hash(token: str) -> str:
    return hashlib.sha256(
        _TOKEN_HASH_DOMAIN + token.encode("utf-8")
    ).hexdigest()


def hash_token(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    if not token:
        raise ValueError("token must not be empty")
    return _compute_hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    if not token:
        raise ValueError("token must not be empty")
    if not isinstance(token_hash, str):
        raise TypeError("token_hash must be a string")
    if not token_hash:
        raise ValueError("token_hash must not be empty")
    computed = _compute_hash(token)
    return hmac.compare_digest(computed, token_hash)
