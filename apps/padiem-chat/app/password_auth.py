from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets

USERNAME_MIN_CHARS = 4
USERNAME_MAX_CHARS = 32
PASSWORD_MIN_CHARS = 12
PASSWORD_MAX_CHARS = 128
DISPLAY_NAME_MAX_CHARS = 160
EMAIL_MAX_CHARS = 320

PBKDF2_ALGORITHM = "sha512"
PBKDF2_ITERATIONS = 210_000
PBKDF2_SALT_BYTES = 16
PBKDF2_DKLEN = 32
PASSWORD_HASH_PREFIX = "pbkdf2_sha512"

_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{3,31}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Fixed, non-secret dummy verifier used only to equalize missing-account work.
_DUMMY_HASH = (
    "pbkdf2_sha512$210000$"
    "cGFkaWVtLWR1bW15LXNhbHQtMDE="
    "$RsPCZ1wcH0+GxN9zW+zqsNlwPiylbJdzVeHjLxWd7Yw="
)


class PasswordAuthError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_username(value: object) -> str:
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


def validate_password(value: object, *, username: str | None = None) -> str:
    if not isinstance(value, str):
        raise PasswordAuthError("invalid_password", "비밀번호 형식이 올바르지 않습니다.")
    if not PASSWORD_MIN_CHARS <= len(value) <= PASSWORD_MAX_CHARS:
        raise PasswordAuthError(
            "invalid_password",
            f"비밀번호는 {PASSWORD_MIN_CHARS}~{PASSWORD_MAX_CHARS}자로 입력해 주세요.",
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise PasswordAuthError("invalid_password", "비밀번호에 제어 문자를 사용할 수 없습니다.")
    if username and username.lower() in value.lower():
        raise PasswordAuthError("invalid_password", "비밀번호에 아이디 전체를 포함할 수 없습니다.")
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


def verify_password(password: object, encoded: str | None) -> bool:
    candidate = password if isinstance(password, str) else ""
    stored = encoded if isinstance(encoded, str) and encoded else _DUMMY_HASH
    try:
        prefix, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
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
        # Still perform one bounded dummy KDF so malformed/missing rows do not
        # become an obvious cheap username oracle.
        stored = _DUMMY_HASH
        _, iterations_raw, salt_raw, digest_raw = stored.split("$", 3)
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)

    actual = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        candidate.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)
