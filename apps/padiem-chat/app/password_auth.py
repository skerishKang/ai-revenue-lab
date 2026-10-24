from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

from app.password_kdf import apbkdf2_sha512 as _pbkdf2_dispatch

USERNAME_MIN_CHARS = 4
USERNAME_MAX_CHARS = 32
PASSWORD_MIN_CHARS = 8
PASSWORD_MAX_CHARS = 128
DISPLAY_NAME_MAX_CHARS = 160
EMAIL_MAX_CHARS = 320
# The Control Plane identity bridge bounds a provider subject to 255
# characters. The account login identifier is stored as that subject, so a
# registration identifier may never be longer than the bridge accepts.
LOGIN_IDENTIFIER_MAX_CHARS = 255

PBKDF2_ALGORITHM = "sha512"
PBKDF2_ITERATIONS = 220_000
PBKDF2_SALT_BYTES = 16
PBKDF2_DKLEN = 32
PASSWORD_HASH_PREFIX = "pbkdf2_sha512"

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{3,31}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Fixed, non-secret dummy verifier used only to equalize missing-account work.
_DUMMY_HASH = (
    "pbkdf2_sha512$220000$"
    "cGFkaWVtLWR1bW15LXNhbHQtMDE="
    "$RsPCZ1wcH0+GxN9zW+zqsNlwPiylbJdzVeHjLxWd7Yw="
)


class PasswordAuthError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_username(value: object) -> str:
    """Normalize a legacy standalone ID.

    #5424 unified the account identifier on the email address, so a new
    registration never asks for a separate ID. This grammar is kept only so
    an account that was registered before the unification can still sign in
    with the ID it was created with.
    """
    if not isinstance(value, str):
        raise PasswordAuthError("invalid_username", "아이디 형식이 올바르지 않습니다.")
    username = value.strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise PasswordAuthError(
            "invalid_username",
            "아이디는 영문 소문자, 숫자, 점, 밑줄, 하이픈을 사용해 4~32자로 입력해 주세요.",
        )
    return username


def normalize_email(value: object) -> str:
    if not isinstance(value, str):
        raise PasswordAuthError("invalid_email", "이메일 형식이 올바르지 않습니다.")
    email = value.strip().lower()
    if not email or len(email) > EMAIL_MAX_CHARS or not _EMAIL_RE.fullmatch(email):
        raise PasswordAuthError("invalid_email", "이메일 형식이 올바르지 않습니다.")
    return email


def normalize_login_identifier(value: object) -> str:
    """Normalize the single PADIEM login identifier: the account email address.

    #5424 removed the separate ID field. The credential still stores its
    subject in the ``password_credentials.username`` column, but that value is
    now the normalized email, so the canonical id derivation and the
    ``password:`` compatibility subject stay exactly as they were.
    """
    email = normalize_email(value)
    if len(email) > LOGIN_IDENTIFIER_MAX_CHARS:
        raise PasswordAuthError(
            "invalid_email",
            f"이메일은 {LOGIN_IDENTIFIER_MAX_CHARS}자 이하로 입력해 주세요.",
        )
    return email


def normalize_display_name(value: object, *, fallback: str) -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise PasswordAuthError("invalid_display_name", "이름 형식이 올바르지 않습니다.")
    name = " ".join(value.split())
    if not name:
        return fallback
    if len(name) > DISPLAY_NAME_MAX_CHARS:
        raise PasswordAuthError("invalid_display_name", "이름은 160자 이하로 입력해 주세요.")
    return name


def _identifier_fragments(identifier: str | None) -> tuple[str, ...]:
    """The identifier substrings a password may not contain.

    The email address is the account identifier, so neither the whole address
    nor its local part may appear inside a password. A local part shorter than
    the legacy ID minimum is skipped: it is not an identifier a password could
    meaningfully be built from, and rejecting it would reject unrelated
    passwords.
    """
    if not isinstance(identifier, str):
        return ()
    normalized = identifier.strip().lower()
    if not normalized:
        return ()
    fragments = [normalized]
    local = normalized.partition("@")[0]
    if len(local) >= USERNAME_MIN_CHARS and local not in fragments:
        fragments.append(local)
    return tuple(fragments)


def validate_password(value: object, *, identifier: str | None = None) -> str:
    if not isinstance(value, str):
        raise PasswordAuthError("invalid_password", "비밀번호 형식이 올바르지 않습니다.")
    if not PASSWORD_MIN_CHARS <= len(value) <= PASSWORD_MAX_CHARS:
        raise PasswordAuthError(
            "invalid_password",
            f"비밀번호는 {PASSWORD_MIN_CHARS}~{PASSWORD_MAX_CHARS}자로 입력해 주세요.",
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise PasswordAuthError("invalid_password", "비밀번호에 제어 문자를 사용할 수 없습니다.")
    for fragment in _identifier_fragments(identifier):
        if fragment in value.lower():
            raise PasswordAuthError(
                "invalid_password",
                "비밀번호에 이메일(로그인 아이디)을 포함할 수 없습니다.",
            )
    return value


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=PBKDF2_DKLEN,
    )
    return f"{PASSWORD_HASH_PREFIX}${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(derived)}"


async def hash_password_async(password: str) -> str:
    """Runtime-dispatching hash: the C path on 3.13, WebCrypto on 3.14.

    #5479/#5664: the sync :func:`hash_password` stays exactly as Production
    runs it today (Pyodide 3.13 provides ``hashlib.pbkdf2_hmac``). The async
    form dispatches through app.password_kdf so a runtime move that removes
    ``_hashlib`` keeps deriving the same PBKDF2-HMAC-SHA512 bytes — the
    stored credential format does not change.
    """
    validate_password(password)
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    derived = await _pbkdf2_dispatch(
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        PBKDF2_DKLEN,
    )
    return f"{PASSWORD_HASH_PREFIX}${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(derived)}"


def _verify_parameters(encoded: str | None) -> tuple[bytes, int, int, bytes]:
    """salt, iterations, dklen, expected — with the bounded dummy fallback.

    Still performs one bounded dummy KDF for malformed/missing rows so they do
    not become an obvious cheap username oracle (unchanged #5424 semantics).
    """
    candidate = encoded if isinstance(encoded, str) and encoded else _DUMMY_HASH
    try:
        prefix, iterations_raw, salt_raw, digest_raw = candidate.split("$", 3)
        if prefix != PASSWORD_HASH_PREFIX:
            raise ValueError("unsupported password hash")
        iterations = int(iterations_raw)
        if iterations != PBKDF2_ITERATIONS:
            raise ValueError("unsupported password cost")
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
        if len(salt) < 16 or len(expected) != PBKDF2_DKLEN:
            raise ValueError("invalid password hash")
    except (ValueError, TypeError):
        _, iterations_raw, salt_raw, digest_raw = _DUMMY_HASH.split("$", 3)
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
    return salt, iterations, len(expected), expected


def verify_password(password: object, encoded: str | None) -> bool:
    candidate = password if isinstance(password, str) else ""
    salt, iterations, dklen, expected = _verify_parameters(encoded)
    actual = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        candidate.encode("utf-8"),
        salt,
        iterations,
        dklen=dklen,
    )
    return hmac.compare_digest(actual, expected)


async def verify_password_async(password: object, encoded: str | None) -> bool:
    """Runtime-dispatching verify: the async twin of :func:`verify_password`."""
    candidate = password if isinstance(password, str) else ""
    salt, iterations, dklen, expected = _verify_parameters(encoded)
    actual = await _pbkdf2_dispatch(
        candidate.encode("utf-8"),
        salt,
        iterations,
        dklen,
    )
    return hmac.compare_digest(actual, expected)
