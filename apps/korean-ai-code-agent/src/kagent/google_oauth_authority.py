from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any, Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .connector_trust import ConnectorBindingProjection
from .contracts import ContractError
from .gmail_contracts import GMAIL_READONLY_SCOPE

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_DRIVE_API_BASE_URL = "https://www.googleapis.com/drive/v3"

DEFAULT_REQUEST_TIMEOUT_SECONDS = 30
DEFAULT_MAX_RESPONSE_BYTES = 2_000_000
MAX_GOOGLE_API_RESPONSE_BYTES = 4_000_000
MAX_TOKEN_RESPONSE_BYTES = 64_000
TOKEN_REFRESH_SKEW_SECONDS = 60

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
_FORBIDDEN_QUERY_KEYS = frozenset(
    {"access_token", "oauth_token", "authorization", "api_key", "apikey", "key"}
)
_ALLOWED_NETWORK_HOSTS = frozenset(
    {"oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com"}
)


def _safe_ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return normalized


def _secret_text(value: str, field_name: str, *, limit: int = 8_192) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        raise ContractError(f"{field_name} must be non-empty and bounded")
    if any(ord(char) < 32 for char in normalized):
        raise ContractError(f"{field_name} contains control characters")
    return normalized


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class GoogleOAuthCredentialRecord:
    """Trusted secret-bearing record.

    This value must stay behind the credential-store/OAuth authority boundary.
    Secret fields are excluded from repr and there is deliberately no serializer
    that returns them.
    """

    binding: ConnectorBindingProjection
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    refresh_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.binding, ConnectorBindingProjection):
            raise ContractError("binding must be ConnectorBindingProjection")
        object.__setattr__(self, "client_id", _secret_text(self.client_id, "client_id"))
        object.__setattr__(
            self,
            "client_secret",
            _secret_text(self.client_secret, "client_secret"),
        )
        object.__setattr__(
            self,
            "refresh_token",
            _secret_text(self.refresh_token, "refresh_token"),
        )

    def safe_dict(self) -> dict[str, Any]:
        projection = dict(self.binding.safe_dict())
        projection.update(
            {
                "google_oauth_credential_present": True,
                "client_id_present": True,
                "client_secret_present": True,
                "refresh_token_present": True,
                "raw_client_id": False,
                "raw_client_secret": False,
                "raw_refresh_token": False,
                "raw_access_token": False,
            }
        )
        return projection


class GoogleOAuthCredentialStore(Protocol):
    """Trusted persistent credential store.

    Production implementations may use an encrypted database/KMS-backed store,
    but must never return these records into task/model state.
    """

    def load(self, *, binding_ref: str) -> GoogleOAuthCredentialRecord | None:
        ...


@dataclass(frozen=True, slots=True)
class GoogleProviderHttpResponse:
    status: int
    body: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise ContractError("HTTP status must be an integer")
        if not isinstance(self.body, bytes):
            raise ContractError("HTTP response body must be bytes")


class GoogleProviderNetworkPort(Protocol):
    """Secret-bearing network port used only inside the trusted OAuth authority."""

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> GoogleProviderHttpResponse:
        ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _validate_https_google_url(url: str) -> None:
    if not isinstance(url, str):
        raise ContractError("Google provider URL must be a string")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ContractError("Google provider URL must use pinned HTTPS")
    if parsed.hostname not in _ALLOWED_NETWORK_HOSTS:
        raise ContractError("Google provider host is not allowlisted")
    if parsed.port not in (None, 443):
        raise ContractError("Google provider URL must use the default TLS port")
    if parsed.fragment:
        raise ContractError("Google provider URL must not contain a fragment")


class StdlibGoogleProviderNetwork:
    """Bounded, no-redirect HTTPS transport for Google OAuth/provider calls."""

    def __init__(self) -> None:
        self._opener = build_opener(_NoRedirect())

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> GoogleProviderHttpResponse:
        _validate_https_google_url(url)
        normalized_method = method.upper().strip()
        if normalized_method not in {"GET", "POST"}:
            raise ContractError("Google provider HTTP method is not allowed")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 120
        ):
            raise ContractError("timeout_seconds must be between 1 and 120")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_GOOGLE_API_RESPONSE_BYTES
        ):
            raise ContractError("max_response_bytes exceeds trusted Google HTTP bound")
        if not isinstance(headers, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in headers.items()
        ):
            raise ContractError("Google provider headers must be a string map")
        if body is not None and not isinstance(body, bytes):
            raise ContractError("Google provider request body must be bytes")

        request = Request(
            url,
            data=body,
            headers=dict(headers),
            method=normalized_method,
        )
        try:
            response = self._opener.open(request, timeout=timeout_seconds)
        except HTTPError as exc:
            response = exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ContractError("Google provider network request failed") from exc

        try:
            status = int(response.getcode())
            raw = response.read(max_response_bytes + 1)
        except (OSError, ValueError) as exc:
            raise ContractError("Google provider response could not be read") from exc
        finally:
            try:
                response.close()
            except Exception:
                pass

        if len(raw) > max_response_bytes:
            raise ContractError("Google provider response exceeds trusted byte bound")
        return GoogleProviderHttpResponse(status=status, body=raw)


@dataclass(frozen=True, slots=True)
class _ProviderPolicy:
    connector_id: str
    base_url: str
    required_scopes: tuple[str, ...]


_PROVIDER_POLICIES: dict[str, _ProviderPolicy] = {
    GMAIL_API_BASE_URL: _ProviderPolicy(
        connector_id="gmail",
        base_url=GMAIL_API_BASE_URL,
        required_scopes=(GMAIL_READONLY_SCOPE,),
    ),
    GOOGLE_DRIVE_API_BASE_URL: _ProviderPolicy(
        connector_id="google-drive",
        base_url=GOOGLE_DRIVE_API_BASE_URL,
        required_scopes=(GOOGLE_DRIVE_READONLY_SCOPE,),
    ),
}


@dataclass(frozen=True, slots=True)
class _CachedAccessToken:
    access_token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "access_token",
            _secret_text(self.access_token, "access_token"),
        )
        object.__setattr__(self, "expires_at", _aware_utc(self.expires_at, "expires_at"))

    def usable_at(self, now: datetime) -> bool:
        current = _aware_utc(now, "now")
        return current + timedelta(seconds=TOKEN_REFRESH_SKEW_SECONDS) < self.expires_at


class GoogleReadonlyOAuthAuthority:
    """Physical Google OAuth authority for bounded Gmail/Drive reads.

    Connector code supplies only binding/actor refs and provider read arguments.
    This authority resolves trusted credentials, checks binding/scope truth,
    refreshes short-lived access tokens, injects Authorization only inside this
    boundary, and performs bounded HTTPS requests.

    It intentionally does not implement OAuth onboarding/callback persistence.
    A Production credential-store implementation must provision the refresh-token
    record before a binding can become live-provider-ready.
    """

    def __init__(
        self,
        *,
        credentials: GoogleOAuthCredentialStore,
        network: GoogleProviderNetworkPort,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._credentials = credentials
        self._network = network
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._access_tokens: dict[str, _CachedAccessToken] = {}

    def _now(self) -> datetime:
        return _aware_utc(self._clock(), "clock")

    def _policy(
        self,
        *,
        base_url: str,
        required_scopes: tuple[str, ...] | None,
    ) -> _ProviderPolicy:
        try:
            policy = _PROVIDER_POLICIES[base_url]
        except KeyError as exc:
            raise ContractError("Google provider base URL is not reviewed") from exc

        requested = policy.required_scopes if required_scopes is None else tuple(required_scopes)
        if any(not isinstance(scope, str) or not scope.strip() for scope in requested):
            raise ContractError("required_scopes must contain non-empty scope strings")
        normalized = tuple(scope.strip() for scope in requested)
        if set(normalized) != set(policy.required_scopes):
            raise ContractError("Google readonly authority requires the reviewed exact scope set")
        return policy

    def _record(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        policy: _ProviderPolicy,
    ) -> GoogleOAuthCredentialRecord:
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        actor_ref = _safe_ref(actor_ref, "actor_ref")
        record = self._credentials.load(binding_ref=binding_ref)
        if not isinstance(record, GoogleOAuthCredentialRecord):
            raise ContractError("Google OAuth credential binding is not provisioned")

        binding = record.binding
        now = self._now()
        if binding.binding_ref != binding_ref:
            raise ContractError("Google OAuth credential store returned the wrong binding")
        if binding.actor_ref != actor_ref:
            raise ContractError("Google OAuth actor binding mismatch")
        if binding.connector_id != policy.connector_id:
            raise ContractError("Google OAuth connector binding mismatch")
        if not binding.usable_at(now):
            raise ContractError("Google OAuth connector binding is not active")
        if not set(policy.required_scopes).issubset(set(binding.granted_scopes)):
            raise ContractError("Google OAuth binding is missing the required readonly scope")
        return record

    def _refresh(
        self,
        *,
        record: GoogleOAuthCredentialRecord,
        policy: _ProviderPolicy,
    ) -> _CachedAccessToken:
        form = urlencode(
            {
                "client_id": record.client_id,
                "client_secret": record.client_secret,
                "refresh_token": record.refresh_token,
                "grant_type": "refresh_token",
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
            timeout_seconds=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=MAX_TOKEN_RESPONSE_BYTES,
        )
        if response.status != 200:
            raise ContractError("Google OAuth token refresh failed")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("Google OAuth token response is invalid") from exc
        if not isinstance(payload, dict):
            raise ContractError("Google OAuth token response must be an object")

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")
        if not isinstance(access_token, str) or not access_token.strip():
            raise ContractError("Google OAuth token response is missing access_token")
        if not isinstance(token_type, str) or token_type.casefold() != "bearer":
            raise ContractError("Google OAuth token response has unsupported token_type")
        if (
            isinstance(expires_in, bool)
            or not isinstance(expires_in, int)
            or not 1 <= expires_in <= 86_400
        ):
            raise ContractError("Google OAuth token response has invalid expires_in")

        returned_scope = payload.get("scope")
        if returned_scope is not None:
            if not isinstance(returned_scope, str):
                raise ContractError("Google OAuth token response has invalid scope")
            returned_scopes = set(returned_scope.split())
            if not set(policy.required_scopes).issubset(returned_scopes):
                raise ContractError("Google OAuth refreshed token lacks required readonly scope")

        cached = _CachedAccessToken(
            access_token=access_token.strip(),
            expires_at=self._now() + timedelta(seconds=expires_in),
        )
        self._access_tokens[record.binding.binding_ref] = cached
        return cached

    def _token(
        self,
        *,
        record: GoogleOAuthCredentialRecord,
        policy: _ProviderPolicy,
        force_refresh: bool = False,
    ) -> _CachedAccessToken:
        binding_ref = record.binding.binding_ref
        if not force_refresh:
            cached = self._access_tokens.get(binding_ref)
            if cached is not None and cached.usable_at(self._now()):
                return cached
        return self._refresh(record=record, policy=policy)

    def _api_url(
        self,
        *,
        policy: _ProviderPolicy,
        path: str,
        query: dict[str, str],
    ) -> str:
        if not isinstance(path, str) or not path.startswith("/"):
            raise ContractError("Google provider path must be absolute")
        parsed_path = urlsplit(path)
        if parsed_path.scheme or parsed_path.netloc or parsed_path.query or parsed_path.fragment:
            raise ContractError("Google provider path must not override origin/query")
        if any(segment == ".." for segment in parsed_path.path.split("/")):
            raise ContractError("Google provider path traversal is not allowed")
        if not isinstance(query, dict):
            raise ContractError("Google provider query must be an object")

        normalized_query: dict[str, str] = {}
        for key, value in query.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ContractError("Google provider query keys and values must be strings")
            normalized_key = key.strip()
            if not normalized_key or normalized_key.casefold() in _FORBIDDEN_QUERY_KEYS:
                raise ContractError("credential-bearing Google provider query parameter is forbidden")
            if len(normalized_key) > 256 or len(value) > 8_192:
                raise ContractError("Google provider query parameter exceeds trusted bound")
            normalized_query[normalized_key] = value

        suffix = f"?{urlencode(normalized_query)}" if normalized_query else ""
        url = f"{policy.base_url}{parsed_path.path}{suffix}"
        _validate_https_google_url(url)
        return url

    def _request(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        max_response_bytes: int,
        required_scopes: tuple[str, ...] | None,
    ) -> bytes:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 1 <= timeout_seconds <= 120
        ):
            raise ContractError("timeout_seconds must be between 1 and 120")
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or not 1 <= max_response_bytes <= MAX_GOOGLE_API_RESPONSE_BYTES
        ):
            raise ContractError("max_response_bytes exceeds trusted Google HTTP bound")

        policy = self._policy(base_url=base_url, required_scopes=required_scopes)
        record = self._record(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            policy=policy,
        )
        url = self._api_url(policy=policy, path=path, query=query)

        token = self._token(record=record, policy=policy)
        response = self._network.request(
            method="GET",
            url=url,
            headers={
                "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
                "Authorization": f"Bearer {token.access_token}",
            },
            body=None,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        if response.status == 401:
            self._access_tokens.pop(record.binding.binding_ref, None)
            token = self._token(record=record, policy=policy, force_refresh=True)
            response = self._network.request(
                method="GET",
                url=url,
                headers={
                    "Accept": "application/json, text/plain;q=0.9, */*;q=0.1",
                    "Authorization": f"Bearer {token.access_token}",
                },
                body=None,
                timeout_seconds=timeout_seconds,
                max_response_bytes=max_response_bytes,
            )
        if not 200 <= response.status < 300:
            raise ContractError(f"Google provider request failed with HTTP {response.status}")
        if len(response.body) > max_response_bytes:
            raise ContractError("Google provider response exceeds trusted byte bound")
        return response.body

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        required_scopes: tuple[str, ...] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
        raw = self._request(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            base_url=base_url,
            path=path,
            query=query,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            required_scopes=required_scopes,
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ContractError("Google provider JSON response is invalid") from exc
        if not isinstance(payload, dict):
            raise ContractError("Google provider JSON response must be an object")
        return payload

    def get_text(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
        required_scopes: tuple[str, ...] | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> str:
        raw = self._request(
            binding_ref=binding_ref,
            actor_ref=actor_ref,
            base_url=base_url,
            path=path,
            query=query,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            required_scopes=required_scopes,
        )
        return raw.decode("utf-8", errors="replace")


GOOGLE_READONLY_OAUTH_AUTHORITY_IMPLEMENTED = True
GOOGLE_OAUTH_LIVE_CREDENTIAL_STORE_CONFIGURED = False
GOOGLE_OAUTH_RAW_TOKEN_IN_TASK = False
