from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Callable, Protocol
from urllib.parse import urlencode, urlsplit

from .connector_trust import ConnectorBindingProjection
from .contracts import ContractError
from .gmail_contracts import GMAIL_READONLY_SCOPE
from .google_oauth_authority import (
    GOOGLE_DRIVE_READONLY_SCOPE,
    GOOGLE_TOKEN_URL,
    MAX_TOKEN_RESPONSE_BYTES,
    GoogleOAuthCredentialRecord,
    GoogleProviderNetworkPort,
)

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
AUTHORIZATION_SESSION_TTL_SECONDS = 600
MAX_AUTHORIZATION_CODE_CHARS = 4_096
MAX_SEALED_RECORD_BYTES = 256_000
MAX_REFRESH_TOKEN_LIFETIME_SECONDS = 366 * 24 * 60 * 60

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~\-]{43,128}$")

_CONNECTOR_SCOPES: dict[str, tuple[str, ...]] = {
    "gmail": (GMAIL_READONLY_SCOPE,),
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
}


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _bounded_secret(value: str, field_name: str, *, limit: int = 16_384) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit or any(ord(char) < 32 for char in normalized):
        raise ContractError(f"{field_name} must be non-empty and bounded")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value, "datetime").isoformat().replace("+00:00", "Z")


def _parse_iso(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{field_name} must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{field_name} must be an ISO datetime") from exc
    return _aware(parsed, field_name)


def _https_redirect_uri(value: str) -> str:
    if not isinstance(value, str):
        raise ContractError("redirect_uri must be a string")
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or len(normalized) > 2_048
    ):
        raise ContractError("redirect_uri must be a bounded HTTPS URI")
    return normalized


def _scope_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError("scopes must be a sequence")
    scopes = tuple(str(scope).strip() for scope in value)
    if not scopes or any(not scope for scope in scopes) or len(scopes) != len(set(scopes)):
        raise ContractError("scopes must be non-empty and unique")
    return scopes


def _pkce_challenge(verifier: str) -> str:
    if not isinstance(verifier, str) or not _PKCE_VERIFIER_RE.fullmatch(verifier):
        raise ContractError("PKCE verifier must be 43-128 unreserved characters")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class GoogleOAuthClientConfig:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "client_id", _bounded_secret(self.client_id, "client_id"))
        object.__setattr__(
            self,
            "client_secret",
            _bounded_secret(self.client_secret, "client_secret"),
        )
        object.__setattr__(self, "redirect_uri", _https_redirect_uri(self.redirect_uri))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "client_secret_present": True,
            "raw_client_secret": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthAuthorizationSession:
    state_ref: str
    connector_id: str
    actor_ref: str
    account_ref: str
    workspace_ref: str
    requested_scopes: tuple[str, ...]
    code_verifier: str = field(repr=False)
    redirect_uri: str
    created_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "state_ref",
            "connector_id",
            "actor_ref",
            "account_ref",
            "workspace_ref",
        ):
            object.__setattr__(self, field_name, _safe_ref(getattr(self, field_name), field_name))
        object.__setattr__(self, "requested_scopes", _scope_tuple(self.requested_scopes))
        expected = _CONNECTOR_SCOPES.get(self.connector_id)
        if expected is None or set(self.requested_scopes) != set(expected):
            raise ContractError("OAuth session scopes do not match reviewed connector scopes")
        verifier = _bounded_secret(self.code_verifier, "code_verifier", limit=128)
        if not _PKCE_VERIFIER_RE.fullmatch(verifier):
            raise ContractError("code_verifier must satisfy PKCE bounds")
        object.__setattr__(self, "code_verifier", verifier)
        object.__setattr__(self, "redirect_uri", _https_redirect_uri(self.redirect_uri))
        created = _aware(self.created_at, "created_at")
        expires = _aware(self.expires_at, "expires_at")
        if not created < expires <= created + timedelta(seconds=AUTHORIZATION_SESSION_TTL_SECONDS):
            raise ContractError("OAuth authorization session expiry exceeds trusted bound")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "state_ref": self.state_ref,
            "connector_id": self.connector_id,
            "actor_ref": self.actor_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "requested_scopes": list(self.requested_scopes),
            "redirect_uri": self.redirect_uri,
            "created_at": _iso(self.created_at),
            "expires_at": _iso(self.expires_at),
            "pkce_verifier_present": True,
            "raw_pkce_verifier": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthAuthorizationStart:
    authorization_url: str
    state_ref: str
    connector_id: str
    requested_scopes: tuple[str, ...]
    expires_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.authorization_url, str) or not self.authorization_url.startswith(
            GOOGLE_AUTHORIZATION_URL + "?"
        ):
            raise ContractError("authorization_url must use the pinned Google endpoint")
        object.__setattr__(self, "state_ref", _safe_ref(self.state_ref, "state_ref"))
        object.__setattr__(self, "connector_id", _safe_ref(self.connector_id, "connector_id"))
        object.__setattr__(self, "requested_scopes", _scope_tuple(self.requested_scopes))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "authorization_url": self.authorization_url,
            "state_ref": self.state_ref,
            "connector_id": self.connector_id,
            "requested_scopes": list(self.requested_scopes),
            "expires_at": _iso(self.expires_at),
            "raw_client_secret": False,
            "raw_code_verifier": False,
            "raw_refresh_token": False,
        }


@dataclass(frozen=True, slots=True)
class GoogleOAuthProvisioningReceipt:
    binding: ConnectorBindingProjection
    connected_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ConnectorBindingProjection):
            raise ContractError("binding must be ConnectorBindingProjection")
        object.__setattr__(self, "connected_at", _aware(self.connected_at, "connected_at"))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding": self.binding.safe_dict(),
            "connected_at": _iso(self.connected_at),
            "oauth_authorization_code_consumed": True,
            "refresh_token_persisted": True,
            "raw_authorization_code": False,
            "raw_access_token": False,
            "raw_refresh_token": False,
            "raw_client_secret": False,
        }


class GoogleOAuthAuthorizationSessionStore(Protocol):
    def put(self, session: GoogleOAuthAuthorizationSession) -> None:
        ...

    def consume(self, *, state_ref: str) -> GoogleOAuthAuthorizationSession | None:
        ...


class GoogleOAuthCredentialWriter(Protocol):
    def save(self, record: GoogleOAuthCredentialRecord) -> None:
        ...


class GoogleCredentialSealerPort(Protocol):
    """Trusted KMS/envelope-encryption boundary.

    The persistence adapter receives only ciphertext from this port. Production
    must supply a cryptographically authenticated sealer backed by trusted key
    authority; deterministic test sealers must never be wired in Production.
    """

    def seal(self, *, plaintext: bytes, aad: bytes) -> bytes:
        ...

    def open(self, *, ciphertext: bytes, aad: bytes) -> bytes:
        ...


def _session_payload(session: GoogleOAuthAuthorizationSession) -> bytes:
    return json.dumps(
        {
            "state_ref": session.state_ref,
            "connector_id": session.connector_id,
            "actor_ref": session.actor_ref,
            "account_ref": session.account_ref,
            "workspace_ref": session.workspace_ref,
            "requested_scopes": list(session.requested_scopes),
            "code_verifier": session.code_verifier,
            "redirect_uri": session.redirect_uri,
            "created_at": _iso(session.created_at),
            "expires_at": _iso(session.expires_at),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _session_from_payload(raw: bytes) -> GoogleOAuthAuthorizationSession:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("sealed OAuth session payload is invalid") from exc
    if not isinstance(payload, dict):
        raise ContractError("sealed OAuth session payload must be an object")
    try:
        return GoogleOAuthAuthorizationSession(
            state_ref=payload["state_ref"],
            connector_id=payload["connector_id"],
            actor_ref=payload["actor_ref"],
            account_ref=payload["account_ref"],
            workspace_ref=payload["workspace_ref"],
            requested_scopes=tuple(payload["requested_scopes"]),
            code_verifier=payload["code_verifier"],
            redirect_uri=payload["redirect_uri"],
            created_at=_parse_iso(payload["created_at"], "created_at"),
            expires_at=_parse_iso(payload["expires_at"], "expires_at"),
        )
    except (KeyError, TypeError) as exc:
        raise ContractError("sealed OAuth session payload is incomplete") from exc


def _credential_payload(record: GoogleOAuthCredentialRecord) -> bytes:
    binding = record.binding
    return json.dumps(
        {
            "binding": {
                "binding_ref": binding.binding_ref,
                "connector_id": binding.connector_id,
                "actor_ref": binding.actor_ref,
                "account_ref": binding.account_ref,
                "workspace_ref": binding.workspace_ref,
                "granted_scopes": list(binding.granted_scopes),
                "granted_capabilities": list(binding.granted_capabilities),
                "issued_at": _iso(binding.issued_at),
                "updated_at": _iso(binding.updated_at),
                "expires_at": _iso(binding.expires_at) if binding.expires_at else None,
                "state": binding.state.value,
                "revoked_at": _iso(binding.revoked_at) if binding.revoked_at else None,
            },
            "client_id": record.client_id,
            "client_secret": record.client_secret,
            "refresh_token": record.refresh_token,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _credential_from_payload(raw: bytes) -> GoogleOAuthCredentialRecord:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("sealed Google credential payload is invalid") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("binding"), dict):
        raise ContractError("sealed Google credential payload must contain binding")
    binding = payload["binding"]
    try:
        projection = ConnectorBindingProjection(
            binding_ref=binding["binding_ref"],
            connector_id=binding["connector_id"],
            actor_ref=binding["actor_ref"],
            account_ref=binding["account_ref"],
            workspace_ref=binding["workspace_ref"],
            granted_scopes=tuple(binding["granted_scopes"]),
            granted_capabilities=tuple(binding["granted_capabilities"]),
            issued_at=_parse_iso(binding["issued_at"], "issued_at"),
            updated_at=_parse_iso(binding["updated_at"], "updated_at"),
            expires_at=(
                _parse_iso(binding["expires_at"], "expires_at")
                if binding.get("expires_at")
                else None
            ),
            revoked_at=(
                _parse_iso(binding["revoked_at"], "revoked_at")
                if binding.get("revoked_at")
                else None
            ),
            state=binding["state"],
        )
        return GoogleOAuthCredentialRecord(
            binding=projection,
            client_id=payload["client_id"],
            client_secret=payload["client_secret"],
            refresh_token=payload["refresh_token"],
        )
    except (KeyError, TypeError) as exc:
        raise ContractError("sealed Google credential payload is incomplete") from exc


class SqliteSealedGoogleOAuthStore:
    """Persistent OAuth store whose SQLite rows contain ciphertext only.

    The cryptographic primitive/key lifecycle remains behind
    `GoogleCredentialSealerPort`, allowing a Production KMS/envelope-encryption
    implementation without putting raw master keys in B54 task/model state.
    """

    def __init__(self, database_path: str | Path, sealer: GoogleCredentialSealerPort) -> None:
        if not hasattr(sealer, "seal") or not hasattr(sealer, "open"):
            raise ContractError("sealer must implement the trusted sealing boundary")
        self._sealer = sealer
        if isinstance(database_path, Path):
            database_path = str(database_path)
        if not isinstance(database_path, str) or not database_path.strip():
            raise ContractError("database_path must be non-empty")
        self._database_path = database_path.strip()
        if self._database_path != ":memory:":
            path = Path(self._database_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._database_path, isolation_level=None, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS google_oauth_sessions ("
            "state_ref TEXT PRIMARY KEY, sealed BLOB NOT NULL, expires_at TEXT NOT NULL)"
        )
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS google_oauth_credentials ("
            "binding_ref TEXT PRIMARY KEY, sealed BLOB NOT NULL, updated_at TEXT NOT NULL)"
        )

    @staticmethod
    def _sealed(value: Any, *, field_name: str) -> bytes:
        if not isinstance(value, (bytes, bytearray)):
            raise ContractError(f"{field_name} must be sealed bytes")
        raw = bytes(value)
        if not raw or len(raw) > MAX_SEALED_RECORD_BYTES:
            raise ContractError(f"{field_name} exceeds sealed-record bound")
        return raw

    @staticmethod
    def _session_aad(state_ref: str) -> bytes:
        return f"padiem-b54-google-oauth-session:v1:{state_ref}".encode("utf-8")

    @staticmethod
    def _credential_aad(binding_ref: str) -> bytes:
        return f"padiem-b54-google-oauth-credential:v1:{binding_ref}".encode("utf-8")

    def put(self, session: GoogleOAuthAuthorizationSession) -> None:
        if not isinstance(session, GoogleOAuthAuthorizationSession):
            raise ContractError("session must be GoogleOAuthAuthorizationSession")
        sealed = self._sealed(
            self._sealer.seal(
                plaintext=_session_payload(session),
                aad=self._session_aad(session.state_ref),
            ),
            field_name="sealed session",
        )
        try:
            self._db.execute(
                "INSERT INTO google_oauth_sessions(state_ref, sealed, expires_at) VALUES (?, ?, ?)",
                (session.state_ref, sealed, _iso(session.expires_at)),
            )
        except sqlite3.IntegrityError as exc:
            raise ContractError("OAuth state collision detected") from exc

    def consume(self, *, state_ref: str) -> GoogleOAuthAuthorizationSession | None:
        state_ref = _safe_ref(state_ref, "state_ref")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            row = self._db.execute(
                "SELECT sealed FROM google_oauth_sessions WHERE state_ref = ?",
                (state_ref,),
            ).fetchone()
            if row is None:
                self._db.execute("COMMIT")
                return None
            self._db.execute(
                "DELETE FROM google_oauth_sessions WHERE state_ref = ?",
                (state_ref,),
            )
            self._db.execute("COMMIT")
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        sealed = self._sealed(row[0], field_name="sealed session")
        plaintext = self._sealer.open(ciphertext=sealed, aad=self._session_aad(state_ref))
        if not isinstance(plaintext, bytes) or len(plaintext) > MAX_SEALED_RECORD_BYTES:
            raise ContractError("unsealed OAuth session payload is invalid")
        session = _session_from_payload(plaintext)
        if session.state_ref != state_ref:
            raise ContractError("sealed OAuth session state binding mismatch")
        return session

    def save(self, record: GoogleOAuthCredentialRecord) -> None:
        if not isinstance(record, GoogleOAuthCredentialRecord):
            raise ContractError("record must be GoogleOAuthCredentialRecord")
        binding_ref = record.binding.binding_ref
        sealed = self._sealed(
            self._sealer.seal(
                plaintext=_credential_payload(record),
                aad=self._credential_aad(binding_ref),
            ),
            field_name="sealed credential",
        )
        self._db.execute(
            "INSERT INTO google_oauth_credentials(binding_ref, sealed, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(binding_ref) DO UPDATE SET sealed=excluded.sealed, updated_at=excluded.updated_at",
            (binding_ref, sealed, _iso(record.binding.updated_at)),
        )

    def load(self, *, binding_ref: str) -> GoogleOAuthCredentialRecord | None:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        row = self._db.execute(
            "SELECT sealed FROM google_oauth_credentials WHERE binding_ref = ?",
            (binding_ref,),
        ).fetchone()
        if row is None:
            return None
        sealed = self._sealed(row[0], field_name="sealed credential")
        plaintext = self._sealer.open(
            ciphertext=sealed,
            aad=self._credential_aad(binding_ref),
        )
        if not isinstance(plaintext, bytes) or len(plaintext) > MAX_SEALED_RECORD_BYTES:
            raise ContractError("unsealed Google credential payload is invalid")
        record = _credential_from_payload(plaintext)
        if record.binding.binding_ref != binding_ref:
            raise ContractError("sealed Google credential binding mismatch")
        return record

    def delete_binding(self, *, binding_ref: str) -> bool:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        cursor = self._db.execute(
            "DELETE FROM google_oauth_credentials WHERE binding_ref = ?",
            (binding_ref,),
        )
        return cursor.rowcount == 1

    def raw_persistent_rows_for_audit(self) -> tuple[bytes, ...]:
        """Test/audit helper: returns ciphertext only, never decrypted secret material."""
        rows = []
        for table in ("google_oauth_sessions", "google_oauth_credentials"):
            rows.extend(
                bytes(row[0])
                for row in self._db.execute(f"SELECT sealed FROM {table}").fetchall()
            )
        return tuple(rows)


class GoogleOAuthProvisioner:
    """Authorization-code onboarding boundary for Gmail/Drive read bindings."""

    def __init__(
        self,
        *,
        client: GoogleOAuthClientConfig,
        sessions: GoogleOAuthAuthorizationSessionStore,
        credentials: GoogleOAuthCredentialWriter,
        network: GoogleProviderNetworkPort,
        clock: Callable[[], datetime] | None = None,
        random_token: Callable[[int], str] | None = None,
    ) -> None:
        if not isinstance(client, GoogleOAuthClientConfig):
            raise ContractError("client must be GoogleOAuthClientConfig")
        self._client = client
        self._sessions = sessions
        self._credentials = credentials
        self._network = network
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._random_token = random_token or secrets.token_urlsafe

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock")

    def _token(self, bytes_count: int, field_name: str) -> str:
        value = self._random_token(bytes_count)
        if not isinstance(value, str) or not value:
            raise ContractError(f"random source returned invalid {field_name}")
        return value

    def begin(
        self,
        *,
        connector_id: str,
        actor_ref: str,
        account_ref: str,
        workspace_ref: str,
    ) -> GoogleOAuthAuthorizationStart:
        connector_id = _safe_ref(connector_id, "connector_id")
        scopes = _CONNECTOR_SCOPES.get(connector_id)
        if scopes is None:
            raise ContractError("connector is not approved for Google readonly OAuth provisioning")
        actor_ref = _safe_ref(actor_ref, "actor_ref")
        account_ref = _safe_ref(account_ref, "account_ref")
        workspace_ref = _safe_ref(workspace_ref, "workspace_ref")
        state_ref = _safe_ref(self._token(32, "state_ref"), "state_ref")
        code_verifier = self._token(64, "code_verifier")
        if not _PKCE_VERIFIER_RE.fullmatch(code_verifier):
            raise ContractError("random source returned invalid PKCE verifier")
        now = self._now()
        session = GoogleOAuthAuthorizationSession(
            state_ref=state_ref,
            connector_id=connector_id,
            actor_ref=actor_ref,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            requested_scopes=scopes,
            code_verifier=code_verifier,
            redirect_uri=self._client.redirect_uri,
            created_at=now,
            expires_at=now + timedelta(seconds=AUTHORIZATION_SESSION_TTL_SECONDS),
        )
        self._sessions.put(session)
        authorization_url = GOOGLE_AUTHORIZATION_URL + "?" + urlencode(
            {
                "client_id": self._client.client_id,
                "redirect_uri": self._client.redirect_uri,
                "response_type": "code",
                "scope": " ".join(scopes),
                "access_type": "offline",
                "prompt": "consent",
                "state": state_ref,
                "code_challenge": _pkce_challenge(code_verifier),
                "code_challenge_method": "S256",
            }
        )
        return GoogleOAuthAuthorizationStart(
            authorization_url=authorization_url,
            state_ref=state_ref,
            connector_id=connector_id,
            requested_scopes=scopes,
            expires_at=session.expires_at,
        )

    def complete_callback(
        self,
        *,
        state_ref: str,
        authorization_code: str | None = None,
        provider_error: str | None = None,
    ) -> GoogleOAuthProvisioningReceipt:
        state_ref = _safe_ref(state_ref, "state_ref")
        session = self._sessions.consume(state_ref=state_ref)
        if not isinstance(session, GoogleOAuthAuthorizationSession):
            raise ContractError("OAuth callback state is unknown or already consumed")
        now = self._now()
        if now > session.expires_at:
            raise ContractError("OAuth callback state has expired")
        if provider_error is not None:
            if not isinstance(provider_error, str) or len(provider_error) > 1_024:
                raise ContractError("OAuth provider error is invalid")
            raise ContractError("Google OAuth authorization was not granted")
        code = _bounded_secret(
            authorization_code if authorization_code is not None else "",
            "authorization_code",
            limit=MAX_AUTHORIZATION_CODE_CHARS,
        )
        form = urlencode(
            {
                "client_id": self._client.client_id,
                "client_secret": self._client.client_secret,
                "code": code,
                "code_verifier": session.code_verifier,
                "grant_type": "authorization_code",
                "redirect_uri": session.redirect_uri,
            }
        ).encode("utf-8")
        response = self._network.request(
            method="POST",
            url=GOOGLE_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body=form,
            timeout_seconds=30,
            max_response_bytes=MAX_TOKEN_RESPONSE_BYTES,
        )
        if response.status != 200:
            raise ContractError("Google OAuth authorization-code exchange failed")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("Google OAuth authorization-code response is invalid") from exc
        if not isinstance(payload, dict):
            raise ContractError("Google OAuth authorization-code response must be an object")

        access_token = payload.get("access_token")
        refresh_token = payload.get("refresh_token")
        token_type = payload.get("token_type")
        scopes_raw = payload.get("scope")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ContractError("Google OAuth authorization-code response lacks access_token")
        if not isinstance(refresh_token, str) or not refresh_token.strip():
            raise ContractError("Google OAuth authorization-code response lacks refresh_token")
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise ContractError("Google OAuth authorization-code response has unsupported token_type")
        if not isinstance(scopes_raw, str) or not scopes_raw.strip():
            raise ContractError("Google OAuth authorization-code response lacks granted scope proof")
        granted_scopes = tuple(scopes_raw.split())
        if set(granted_scopes) != set(session.requested_scopes):
            raise ContractError("Google OAuth granted scopes differ from reviewed request")

        refresh_expires_in = payload.get("refresh_token_expires_in")
        binding_expires_at = None
        if refresh_expires_in is not None:
            if (
                isinstance(refresh_expires_in, bool)
                or not isinstance(refresh_expires_in, int)
                or not 1 <= refresh_expires_in <= MAX_REFRESH_TOKEN_LIFETIME_SECONDS
            ):
                raise ContractError("Google OAuth refresh token expiry is invalid")
            binding_expires_at = now + timedelta(seconds=refresh_expires_in)

        binding_ref = _safe_ref(
            f"google-{session.connector_id}-{self._token(24, 'binding_ref')}",
            "binding_ref",
        )
        binding = ConnectorBindingProjection(
            binding_ref=binding_ref,
            connector_id=session.connector_id,
            actor_ref=session.actor_ref,
            account_ref=session.account_ref,
            workspace_ref=session.workspace_ref,
            granted_scopes=session.requested_scopes,
            granted_capabilities=("read",),
            issued_at=now,
            updated_at=now,
            expires_at=binding_expires_at,
        )
        record = GoogleOAuthCredentialRecord(
            binding=binding,
            client_id=self._client.client_id,
            client_secret=self._client.client_secret,
            refresh_token=refresh_token.strip(),
        )
        self._credentials.save(record)
        return GoogleOAuthProvisioningReceipt(binding=binding, connected_at=now)


GOOGLE_OAUTH_PROVISIONING_SOURCE_IMPLEMENTED = True
GOOGLE_OAUTH_PKCE_STATE_SOURCE_IMPLEMENTED = True
GOOGLE_OAUTH_SEALED_SQLITE_STORE_IMPLEMENTED = True
GOOGLE_OAUTH_PRODUCTION_SEALER_CONFIGURED = False
GOOGLE_OAUTH_CALLBACK_HTTP_ROUTE_CONFIGURED = False
GOOGLE_OAUTH_LIVE_CLIENT_CONFIGURED = False
