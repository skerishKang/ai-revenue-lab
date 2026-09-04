from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any, Callable

from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    IdentityLinkState,
    ProductIdentityLink,
    SubjectType,
)


MAX_PROVIDER_SUBJECT_CHARS = 512
MAX_PRODUCT_USER_ID_CHARS = 256
_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_ALLOWED_PROVIDERS = frozenset({"google"})


def _utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError(
            "invalid_identity_authority",
            f"{field_name} must be timezone-aware",
        )
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ControlPlaneContractError(
            "invalid_identity_authority_state",
            f"{field_name} is invalid",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneContractError(
            "invalid_identity_authority_state",
            f"{field_name} is invalid",
        ) from exc
    return _utc(parsed, field_name)


def decode_identity_lookup_key(secret_b64url: str) -> bytes:
    if not isinstance(secret_b64url, str) or not _KEY_RE.fullmatch(secret_b64url):
        raise ControlPlaneContractError(
            "invalid_identity_authority_secret",
            "identity lookup key must encode exactly 32 random bytes",
        )
    padding = "=" * (-len(secret_b64url) % 4)
    try:
        decoded = base64.b64decode(secret_b64url + padding, altchars=b"-_", validate=True)
    except (TypeError, ValueError) as exc:
        raise ControlPlaneContractError(
            "invalid_identity_authority_secret",
            "identity lookup key is not valid base64url",
        ) from exc
    if len(decoded) != 32:
        raise ControlPlaneContractError(
            "invalid_identity_authority_secret",
            "identity lookup key must decode to 256 bits",
        )
    return decoded


def _safe_product_id(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise ControlPlaneContractError(
            "invalid_identity_authority",
            "product_id must be a bounded safe identifier",
        )
    return value


def _product_user_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_PRODUCT_USER_ID_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ControlPlaneContractError(
            "invalid_identity_authority",
            "product_user_id must be bounded opaque text",
        )
    return value.strip()


def _provider(value: Any) -> str:
    if not isinstance(value, str) or value not in _ALLOWED_PROVIDERS:
        raise ControlPlaneContractError(
            "unsupported_identity_provider",
            "identity provider is not reviewed",
        )
    return value


def _provider_subject(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_PROVIDER_SUBJECT_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ControlPlaneContractError(
            "invalid_identity_authority",
            "provider_subject must be bounded opaque text",
        )
    return value.strip()


def _rows(cursor: Any) -> list[dict[str, Any]]:
    to_array = getattr(cursor, "toArray", None)
    if not callable(to_array):
        raise ControlPlaneContractError(
            "identity_authority_storage_error",
            "identity authority storage returned an invalid cursor",
        )
    raw = to_array()
    result: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            result.append(dict(item))
            continue
        to_py = getattr(item, "to_py", None)
        converted = to_py() if callable(to_py) else None
        if isinstance(converted, dict):
            result.append(dict(converted))
            continue
        try:
            result.append(dict(item))
        except (TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "identity_authority_storage_error",
                "identity authority storage row is invalid",
            ) from exc
    return result


class CloudflareCanonicalIdentityAuthorityStore:
    """Canonical identity/session authority backed by one private SQLite Durable Object.

    Provider subjects are never persisted. A keyed HMAC fingerprint is the only
    provider lookup material stored at rest. Product D1 databases remain
    non-authoritative shadows of the canonical pointers issued here.
    """

    def __init__(
        self,
        storage: Any,
        *,
        lookup_key: bytes,
        allowed_product_id: str,
        random_hex: Callable[[int], str] | None = None,
    ) -> None:
        sql = getattr(storage, "sql", None)
        transaction = getattr(storage, "transactionSync", None)
        if sql is None or not callable(getattr(sql, "exec", None)) or not callable(transaction):
            raise ValueError("SQLite Durable Object storage is required")
        if not isinstance(lookup_key, bytes) or len(lookup_key) != 32:
            raise ValueError("lookup_key must be exactly 32 bytes")
        self._storage = storage
        self._sql = sql
        self._lookup_key = lookup_key
        self._allowed_product_id = _safe_product_id(allowed_product_id)
        self._random_hex = random_hex or secrets.token_hex
        self._initialize()

    def _initialize(self) -> None:
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS canonical_identity_subject ("
            "provider TEXT NOT NULL, provider_fingerprint TEXT NOT NULL, "
            "canonical_subject_id TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, "
            "PRIMARY KEY(provider, provider_fingerprint))"
        )
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS canonical_product_identity_link ("
            "product_id TEXT NOT NULL, product_user_id TEXT NOT NULL, "
            "canonical_subject_id TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, "
            "PRIMARY KEY(product_id, product_user_id))"
        )
        self._sql.exec(
            "CREATE INDEX IF NOT EXISTS idx_canonical_product_link_subject "
            "ON canonical_product_identity_link(product_id, canonical_subject_id)"
        )
        self._sql.exec(
            "CREATE TABLE IF NOT EXISTS canonical_auth_session ("
            "session_id TEXT PRIMARY KEY, product_id TEXT NOT NULL, "
            "subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, "
            "issued_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
            "state TEXT NOT NULL, revision INTEGER NOT NULL)"
        )
        self._sql.exec(
            "CREATE INDEX IF NOT EXISTS idx_canonical_auth_session_subject "
            "ON canonical_auth_session(product_id, subject_id)"
        )

    def _require_product(self, product_id: Any) -> str:
        product = _safe_product_id(product_id)
        if product != self._allowed_product_id:
            raise ControlPlaneContractError(
                "identity_authority_product_mismatch",
                "caller product is not authorized by this identity authority",
            )
        return product

    def _fingerprint(self, provider: str, provider_subject: str) -> str:
        material = ("identity-authority:v1\x00" + provider + "\x00" + provider_subject).encode("utf-8")
        return hmac.new(self._lookup_key, material, hashlib.sha256).hexdigest()

    def _new_ref(self, prefix: str, bytes_count: int) -> str:
        token = self._random_hex(bytes_count)
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]+", token) or len(token) != bytes_count * 2:
            raise ControlPlaneContractError(
                "identity_authority_random_source_invalid",
                "identity authority random source returned invalid material",
            )
        return prefix + token

    def resolve_or_create_product_link(
        self,
        *,
        product_id: str,
        product_user_id: str,
        auth_provider: str,
        provider_subject: str,
        now: datetime,
    ) -> ProductIdentityLink:
        product = self._require_product(product_id)
        user_id = _product_user_id(product_user_id)
        provider = _provider(auth_provider)
        provider_sub = _provider_subject(provider_subject)
        observed_at = _utc(now, "now")
        fingerprint = self._fingerprint(provider, provider_sub)

        def operation() -> tuple[str, str]:
            subject_rows = _rows(
                self._sql.exec(
                    "SELECT canonical_subject_id FROM canonical_identity_subject "
                    "WHERE provider=? AND provider_fingerprint=?",
                    provider,
                    fingerprint,
                )
            )
            if len(subject_rows) > 1:
                raise ControlPlaneContractError(
                    "identity_authority_storage_error",
                    "canonical provider identity is ambiguous",
                )
            if subject_rows:
                canonical_subject_id = str(subject_rows[0]["canonical_subject_id"])
            else:
                canonical_subject_id = self._new_ref("sub_", 16)
                self._sql.exec(
                    "INSERT INTO canonical_identity_subject "
                    "(provider, provider_fingerprint, canonical_subject_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    provider,
                    fingerprint,
                    canonical_subject_id,
                    _iso(observed_at),
                )

            link_rows = _rows(
                self._sql.exec(
                    "SELECT canonical_subject_id, state FROM canonical_product_identity_link "
                    "WHERE product_id=? AND product_user_id=?",
                    product,
                    user_id,
                )
            )
            if len(link_rows) > 1:
                raise ControlPlaneContractError(
                    "identity_authority_storage_error",
                    "canonical product identity link is ambiguous",
                )
            if link_rows:
                linked_subject = str(link_rows[0]["canonical_subject_id"])
                linked_state = str(link_rows[0]["state"])
                if linked_subject != canonical_subject_id:
                    raise ControlPlaneContractError(
                        "identity_rebind_forbidden",
                        "authenticated product user cannot be rebound to another canonical subject",
                    )
                return linked_subject, linked_state

            self._sql.exec(
                "INSERT INTO canonical_product_identity_link "
                "(product_id, product_user_id, canonical_subject_id, state, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                product,
                user_id,
                canonical_subject_id,
                IdentityLinkState.ACTIVE.value,
                _iso(observed_at),
            )
            return canonical_subject_id, IdentityLinkState.ACTIVE.value

        canonical_subject_id, state = self._storage.transactionSync(operation)
        try:
            link_state = IdentityLinkState(state)
        except ValueError as exc:
            raise ControlPlaneContractError(
                "identity_authority_storage_error",
                "canonical product identity state is invalid",
            ) from exc
        return ProductIdentityLink(
            product_id=product,
            product_user_id=user_id,
            canonical_subject_id=canonical_subject_id,
            state=link_state,
        )

    def establish_auth_session(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        authenticated_at: datetime,
        not_after: datetime,
        now: datetime,
    ) -> AuthSessionSnapshot:
        product = self._require_product(product_id)
        if not isinstance(subject, CanonicalSubjectRef) or subject.subject_type is not SubjectType.USER:
            raise ControlPlaneContractError(
                "identity_authority_subject_invalid",
                "canonical user subject is required",
            )
        authenticated = _utc(authenticated_at, "authenticated_at")
        expires = _utc(not_after, "not_after")
        issued = _utc(now, "now")
        if issued < authenticated:
            issued = authenticated
        if issued >= expires:
            raise ControlPlaneContractError(
                "identity_authority_session_expired",
                "product authentication evidence is already expired",
            )

        rows = _rows(
            self._sql.exec(
                "SELECT state FROM canonical_product_identity_link "
                "WHERE product_id=? AND canonical_subject_id=?",
                product,
                subject.subject_id,
            )
        )
        if not rows or not any(str(row.get("state")) == IdentityLinkState.ACTIVE.value for row in rows):
            raise ControlPlaneContractError(
                "identity_authority_link_missing",
                "canonical subject has no active link for the caller product",
            )

        session_id = self._new_ref("sess_", 16)
        snapshot = AuthSessionSnapshot(
            session_id=session_id,
            product_id=product,
            subject=subject,
            issued_at=issued,
            expires_at=expires,
            state=AuthSessionState.ACTIVE,
            revision=1,
        )
        self._sql.exec(
            "INSERT INTO canonical_auth_session "
            "(session_id, product_id, subject_type, subject_id, issued_at, expires_at, state, revision) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            snapshot.session_id,
            snapshot.product_id,
            snapshot.subject.subject_type.value,
            snapshot.subject.subject_id,
            _iso(snapshot.issued_at),
            _iso(snapshot.expires_at),
            snapshot.state.value,
            snapshot.revision,
        )
        return snapshot

    def resolve_auth_session(self, *, session_id: str) -> AuthSessionSnapshot:
        if not isinstance(session_id, str) or not _SAFE_ID_RE.fullmatch(session_id):
            raise ControlPlaneContractError(
                "invalid_identity_authority",
                "session_id must be a bounded safe identifier",
            )
        rows = _rows(
            self._sql.exec(
                "SELECT session_id, product_id, subject_type, subject_id, issued_at, expires_at, state, revision "
                "FROM canonical_auth_session WHERE session_id=?",
                session_id,
            )
        )
        if not rows:
            raise ControlPlaneContractError(
                "canonical_auth_session_not_found",
                "canonical auth session was not found",
            )
        if len(rows) != 1:
            raise ControlPlaneContractError(
                "identity_authority_storage_error",
                "canonical auth session is ambiguous",
            )
        row = rows[0]
        try:
            return AuthSessionSnapshot(
                session_id=str(row["session_id"]),
                product_id=str(row["product_id"]),
                subject=CanonicalSubjectRef(
                    subject_type=SubjectType(str(row["subject_type"])),
                    subject_id=str(row["subject_id"]),
                ),
                issued_at=_parse_iso(row["issued_at"], "issued_at"),
                expires_at=_parse_iso(row["expires_at"], "expires_at"),
                state=AuthSessionState(str(row["state"])),
                revision=int(row["revision"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ControlPlaneContractError(
                "identity_authority_storage_error",
                "canonical auth session row is invalid",
            ) from exc

    def safe_dict(self) -> dict[str, Any]:
        return {
            "canonical_identity_authority": True,
            "sqlite_durable_object": True,
            "provider_subject_persisted": False,
            "provider_subject_hmac_fingerprint_only": True,
            "product_shadow_authoritative": False,
            "allowed_product_id": self._allowed_product_id,
            "public_http": False,
        }
