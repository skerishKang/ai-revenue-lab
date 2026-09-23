"""Repo-owned, provider-free contract for a readonly OAuth browser canary.

This module owns one in-process canary attempt only. It is not cross-tab or
cross-submission replay protection: durable replay authority remains the
server-side persisted ticket-use row in the Control Plane.

The helper deliberately accepts action callbacks rather than making network
requests. A real runner may adapt the callbacks to its browser, while this
contract keeps budgets, ordering, redirect/retry policy, polling, safe
diagnostics, and the reviewed read-only connector scope set testable without
OAuth execution.

Scope parameterization is deliberately closed. A canary attempt cannot start
without a `CanaryConnectorScope` drawn from `CANARY_REVIEWED_READONLY_SCOPES`,
so a reusable adapter has no way to request a write scope. Server-side
enforcement of the same reviewed scope set already exists in the Control Plane
ticket/durable-store contracts and in the readonly Google OAuth authority; this
is harness-side defense in depth, not a replacement for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic, sleep
from typing import Callable, Mapping
from urllib.parse import urlsplit


EXTERNAL_RUNTIME_METADATA_REDACTION = "UNRESOLVED"
DURABLE_REPLAY_AUTHORITY = "SERVER_SIDE_EXISTING"

GOOGLE_DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"

READONLY_SCOPE_SUFFIX = ".readonly"

# The only connector scopes a reusable canary may be parameterized with. A
# connector is added here only after its read-only scope set has been reviewed;
# the table is asserted read-only at import time so a later edit cannot
# introduce a write scope silently.
CANARY_REVIEWED_READONLY_SCOPES: Mapping[str, tuple[str, ...]] = {
    "google-drive": (GOOGLE_DRIVE_READONLY_SCOPE,),
    "gmail": (GMAIL_READONLY_SCOPE,),
}


class CanaryContractError(ValueError):
    """A canary action would violate the bounded contract."""


class ConsentPollStatus(str, Enum):
    READY = "ready"
    TIMEOUT = "timeout"


class AttemptStatus(str, Enum):
    ACTIVE = "active"
    FAILED = "failed"


_SAFE_STATUSES = frozenset(
    {"started", "ticketed", "connected", "consent_ready", "completed", "failed", "timeout", "blocked"}
)
_SAFE_ERROR_CODES = frozenset(
    {
        "action_failed",
        "callback_failed",
        "connect_failed",
        "consent_failed",
        "consent_timeout",
        "invalid_request",
        "non_readonly_scope",
        "scope_required",
        "transition_invalid",
        "ticket_failed",
        "unreviewed_connector_scope",
    }
)
_SAFE_PRESENCE_KEYS = frozenset(
    {
        "account_ref",
        "actor_ref",
        "authorization_code",
        "authorization_url",
        "binding_ref",
        "callback",
        "consent_target",
        "cookie_session",
        "provider_token",
        "ticket",
    }
)


def _assert_reviewed_scopes_are_readonly() -> None:
    """Fail closed at import time if the reviewed table ever gains a write scope."""

    if not CANARY_REVIEWED_READONLY_SCOPES:
        raise CanaryContractError("reviewed canary connector scope table must not be empty")
    for connector_id, scopes in CANARY_REVIEWED_READONLY_SCOPES.items():
        if not isinstance(connector_id, str) or not connector_id:
            raise CanaryContractError("reviewed canary connector id is invalid")
        if not isinstance(scopes, tuple) or not scopes:
            raise CanaryContractError("reviewed canary connector scopes must be a non-empty tuple")
        for scope in scopes:
            if not isinstance(scope, str) or not scope.endswith(READONLY_SCOPE_SUFFIX):
                raise CanaryContractError("reviewed canary connector scopes must be read-only")


_assert_reviewed_scopes_are_readonly()


@dataclass(frozen=True, slots=True)
class CanaryConnectorScope:
    """The only scope parameterization a reusable canary attempt may carry."""

    connector_id: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or self.connector_id not in CANARY_REVIEWED_READONLY_SCOPES:
            raise CanaryContractError(
                "unreviewed_connector_scope: connector is not reviewed for canary use"
            )
        if not isinstance(self.scopes, tuple) or not self.scopes:
            raise CanaryContractError("canary connector scopes must be a non-empty tuple")
        if any(not isinstance(scope, str) for scope in self.scopes):
            raise CanaryContractError("canary connector scopes must be strings")
        if len(set(self.scopes)) != len(self.scopes):
            raise CanaryContractError("canary connector scopes must be unique")
        for scope in self.scopes:
            if not scope.endswith(READONLY_SCOPE_SUFFIX):
                raise CanaryContractError(
                    "non_readonly_scope: canary connector scopes must be read-only"
                )
        expected = CANARY_REVIEWED_READONLY_SCOPES[self.connector_id]
        if set(self.scopes) != set(expected):
            raise CanaryContractError(
                "unreviewed_connector_scope: scopes must exactly match the reviewed read-only set"
            )


def reviewed_canary_scope(connector_id: str) -> CanaryConnectorScope:
    """Return the reviewed read-only scope for one canary connector."""

    if not isinstance(connector_id, str):
        raise CanaryContractError("unreviewed_connector_scope: connector id must be a string")
    scopes = CANARY_REVIEWED_READONLY_SCOPES.get(connector_id)
    if scopes is None:
        raise CanaryContractError("unreviewed_connector_scope: connector is not reviewed for canary use")
    return CanaryConnectorScope(connector_id=connector_id, scopes=scopes)


@dataclass(frozen=True, slots=True)
class ConsentPollResult:
    status: ConsentPollStatus
    polls: int


@dataclass(frozen=True, slots=True)
class ConnectRequestPolicy:
    """The only redirect/retry policy allowed for a budgeted connect POST."""

    max_redirects: int = 0
    max_retries: int = 0

    def __post_init__(self) -> None:
        if self.max_redirects != 0:
            raise CanaryContractError("budgeted connect POST requires max_redirects=0")
        if self.max_retries != 0:
            raise CanaryContractError("budgeted connect POST requires max_retries=0")


@dataclass(frozen=True, slots=True)
class SafeDiagnosticProjection:
    status: str
    error_code: str | None = None
    transition_location: str | None = None
    presence: Mapping[str, bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.status, str) or self.status not in _SAFE_STATUSES:
            raise CanaryContractError("status is not a safe diagnostic status")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or self.error_code not in _SAFE_ERROR_CODES
        ):
            raise CanaryContractError("error_code is not a safe diagnostic code")
        if set(self.presence) - _SAFE_PRESENCE_KEYS:
            raise CanaryContractError("presence contains an unapproved key")
        if any(not isinstance(value, bool) for value in self.presence.values()):
            raise CanaryContractError("presence values must be boolean")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "error_code": self.error_code,
            "transition_location": self.transition_location,
            "presence": dict(self.presence),
            "raw_ticket": False,
            "raw_authorization_code": False,
            "raw_provider_token": False,
            "raw_cookie_session": False,
            "raw_binding_ref": False,
            "raw_actor_ref": False,
            "raw_oauth_query": False,
        }


def project_transition_location(url: str) -> str:
    """Return only URL location; query and fragment are never projected."""

    if not isinstance(url, str):
        raise CanaryContractError("transition URL must be a string")
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CanaryContractError("transition URL has an invalid port") from exc
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username is not None or parsed.password is not None:
        raise CanaryContractError("transition URL must contain scheme, host, and path")
    if not parsed.path or len(parsed.path) > 512 or any(ord(char) < 32 for char in parsed.path):
        raise CanaryContractError("transition URL path is invalid")
    host = hostname.lower()
    location_port = f":{port}" if port is not None else ""
    return f"{parsed.scheme}://{host}{location_port}{parsed.path}"


def poll_consent_target(
    target_available: Callable[[], bool],
    *,
    timeout_seconds: float = 5.0,
    interval_seconds: float = 0.25,
    clock: Callable[[], float] = monotonic,
    wait: Callable[[float], None] = sleep,
) -> ConsentPollResult:
    """Poll for consent UI after commit without treating commit as readiness."""

    if timeout_seconds <= 0 or interval_seconds <= 0:
        raise CanaryContractError("consent poll timeout and interval must be positive")
    deadline = clock() + timeout_seconds
    polls = 0
    while True:
        polls += 1
        if target_available():
            return ConsentPollResult(ConsentPollStatus.READY, polls)
        remaining = deadline - clock()
        if remaining <= 0:
            return ConsentPollResult(ConsentPollStatus.TIMEOUT, polls)
        wait(min(interval_seconds, remaining))


@dataclass(slots=True)
class OAuthCanaryAttempt:
    """Single-owner, one-shot budget for ticket/connect/consent/callback."""

    _started: bool = False
    _counts: dict[str, int] = field(
        default_factory=lambda: {
            "ticket_post": 0,
            "connect_post": 0,
            "consent": 0,
            "callback": 0,
        }
    )
    _next_action: int = 0
    _policy: ConnectRequestPolicy | None = None
    _status: AttemptStatus = AttemptStatus.ACTIVE
    _scope: CanaryConnectorScope | None = None

    _ORDER = ("ticket_post", "connect_post", "consent", "callback")

    def start(self, scope: CanaryConnectorScope) -> None:
        if self._started or self._status is AttemptStatus.FAILED:
            raise CanaryContractError("canary attempt already started")
        if not isinstance(scope, CanaryConnectorScope):
            raise CanaryContractError(
                "scope_required: canary attempt requires a reviewed read-only connector scope"
            )
        self._scope = scope
        self._started = True

    @property
    def scope(self) -> CanaryConnectorScope:
        if self._scope is None:
            raise CanaryContractError("canary scope is unavailable before start")
        return self._scope

    @property
    def status(self) -> AttemptStatus:
        return self._status

    @property
    def counts(self) -> Mapping[str, int]:
        return dict(self._counts)

    @property
    def connect_policy(self) -> ConnectRequestPolicy:
        if self._policy is None:
            raise CanaryContractError("connect policy is unavailable before start")
        return self._policy

    def _consume(self, action: str, callback: Callable[[], None], *, policy: ConnectRequestPolicy | None = None) -> None:
        if not self._started or self._status is AttemptStatus.FAILED:
            if self._status is AttemptStatus.FAILED:
                raise CanaryContractError("canary attempt is terminally failed")
            raise CanaryContractError("canary attempt must start before actions")
        if self._next_action >= len(self._ORDER):
            raise CanaryContractError(f"{action} budget exhausted")
        expected = self._ORDER[self._next_action]
        if action != expected:
            raise CanaryContractError(f"invalid canary action order: expected {expected}")
        if self._counts[action] >= 1:
            raise CanaryContractError(f"{action} budget exhausted")
        if action == "connect_post":
            self._policy = policy or ConnectRequestPolicy()
        # Consume before invoking the external action so an exception cannot
        # create an implicit retry path for a budgeted operation.
        self._counts[action] += 1
        self._next_action += 1
        try:
            callback()
        except Exception:
            self._status = AttemptStatus.FAILED
            raise

    def ticket_post(self, action: Callable[[], None]) -> None:
        self._consume("ticket_post", action)

    def connect_post(self, action: Callable[[ConnectRequestPolicy], None], *, policy: ConnectRequestPolicy | None = None) -> None:
        if policy is not None and not isinstance(policy, ConnectRequestPolicy):
            raise CanaryContractError("connect policy must be ConnectRequestPolicy")
        selected_policy = policy or ConnectRequestPolicy()
        self._consume("connect_post", lambda: action(selected_policy), policy=selected_policy)

    def consent(self, action: Callable[[], None]) -> None:
        self._consume("consent", action)

    def callback(self, action: Callable[[], None]) -> None:
        self._consume("callback", action)

    def safe_report(
        self,
        *,
        status: str,
        error_code: str | None = None,
        transition_url: str | None = None,
        presence: Mapping[str, bool] | None = None,
    ) -> SafeDiagnosticProjection:
        return SafeDiagnosticProjection(
            status=status,
            error_code=error_code,
            transition_location=project_transition_location(transition_url) if transition_url else None,
            presence=dict(presence or {}),
        )
