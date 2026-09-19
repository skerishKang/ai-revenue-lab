"""Repo-owned, provider-free contract for a readonly OAuth browser canary.

This module owns one in-process canary attempt only. It is not cross-tab or
cross-submission replay protection: durable replay authority remains the
server-side persisted ticket-use row in the Control Plane.

The helper deliberately accepts action callbacks rather than making network
requests. A real runner may adapt the callbacks to its browser, while this
contract keeps budgets, ordering, redirect/retry policy, polling, and safe
diagnostics testable without OAuth execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import monotonic, sleep
from typing import Callable, Mapping
from urllib.parse import urlsplit


EXTERNAL_RUNTIME_METADATA_REDACTION = "UNRESOLVED"
DURABLE_REPLAY_AUTHORITY = "SERVER_SIDE_EXISTING"


class CanaryContractError(ValueError):
    """A canary action would violate the bounded contract."""


class ConsentPollStatus(str, Enum):
    READY = "ready"
    TIMEOUT = "timeout"


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

    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc or not parsed.path:
        raise CanaryContractError("transition URL must contain scheme, host, and path")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


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

    _ORDER = ("ticket_post", "connect_post", "consent", "callback")

    def start(self) -> None:
        if self._started:
            raise CanaryContractError("canary attempt already started")
        self._started = True

    @property
    def counts(self) -> Mapping[str, int]:
        return dict(self._counts)

    @property
    def connect_policy(self) -> ConnectRequestPolicy:
        if self._policy is None:
            raise CanaryContractError("connect policy is unavailable before start")
        return self._policy

    def _consume(self, action: str, callback: Callable[[], None], *, policy: ConnectRequestPolicy | None = None) -> None:
        if not self._started:
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
        callback()

    def ticket_post(self, action: Callable[[], None]) -> None:
        self._consume("ticket_post", action)

    def connect_post(self, action: Callable[[], None], *, policy: ConnectRequestPolicy | None = None) -> None:
        self._consume("connect_post", action, policy=policy)

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
