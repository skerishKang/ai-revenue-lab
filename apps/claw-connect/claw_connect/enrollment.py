"""PADIEM Connector enrollment — one reviewed login, then one canonical binding.

Authority boundaries (see ``docs/architecture/PADIEM_CONNECTOR_PLATFORM_DECISION_20261012.md``
and ``docs/architecture/PADIEM_CONNECTOR_S2_ENROLLMENT_CLIENT_CONTRACT_20261012.md``):

* The **browser is never authoritative** for account or workspace identity. This
  module only carries the proofs the reviewed user supplies from the official
  PADIEM authentication surface; it never collects a password, a browser cookie
  or a private browser profile.
* Enrollment challenges are redeemed **only** through the authenticated S1
  enrollment server route (``redeem_connector_enrollment`` semantics: canonical
  session check → server-derived scope → explicit consent → durable liveness
  re-read → binding probe → scoped redemption → server receipt). The generic
  pairing ``redeem()`` path is **closed** for enrollment — S1 refuses
  enrollment-bound challenges on it with
  ``enrollment_bound_challenge_requires_scoped_redemption`` — so this module
  never calls it for enrollment.
* Device pairing, credential custody and the ONLINE transition are **delegated**
  to the canonical Local Agent Broker surfaces in ``kagent``
  (``local_agent_broker_pairing_client``, ``local_agent_secure_transport``,
  ``local_agent_server_projection``). This file adds **no** second pairing,
  device-lifecycle, session or credential authority.
* The raw device credential is never read, logged, projected or written here. It
  is persisted only by the canonical protected credential store. The one-time
  pairing code is used once to compute the HMAC possession proof and is never
  persisted, logged or sent beyond that single redemption call.
* Enrollment is **outbound-only**. No inbound socket is opened, no public inbound
  port is required and no UPnP/port mapping is attempted.
* Registration is **not** a P01 READ/WRITE approval. Nothing here grants one.

Because the LOCAL1 server side is not deployed yet
(``PRODUCTION_ACTIVATION=NO`` / ``LIVE_PRODUCTION_PAIRING_CALL=0`` in
``local_agent_pairing_activation_3102``, no authenticated enrollment HTTP
endpoint, durable consent authority unwired), every live call fails closed
until a pinned enrollment server route is explicitly wired. A missing or
partial configuration is reported as blocked, never as a success.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from . import CONNECT_PRODUCT, WEB_URL


class EnrollmentDisplayState(str, Enum):
    """Operator-visible device-authority state owned by enrollment.

    Kept separate from ``connection.ConnectionState`` so the reviewed
    connection state machine is never widened by enrollment. ``CONNECTED`` is
    the one shared member: it is reached only when a server-projected ONLINE
    binding was observed, never by the connection machine alone.
    """

    UNREGISTERED = "unregistered"
    OFFLINE = "offline"
    REVOKED = "revoked"
    PAUSED = "paused"
    CONNECTING = "connecting"
    CONNECTED = "connected"

#: Contract version of the persisted enrollment record. A record written by an
#: older shape is rejected rather than silently reinterpreted.
ENROLLMENT_CONTRACT_VERSION = "claw-connector-enrollment.v1"

#: Canonical Local Agent Broker lifecycle values. The authority is kagent's
#: ``DeviceLifecycle``; this projection only mirrors the vocabulary so the
#: Windows tray has a single stable state contract.
LIFECYCLE_UNPAIRED = "unpaired"
LIFECYCLE_PAIRED_OFFLINE = "paired_offline"
LIFECYCLE_ONLINE = "online"
LIFECYCLE_REVOKED = "revoked"
LIFECYCLE_CREDENTIAL_EXPIRED = "credential_expired"
LIFECYCLE_UPDATE_REQUIRED = "update_required"

#: Bounded device-identity grammar. Mirrors the canonical safe-ref grammar so a
#: locally minted identifier is never rejected by the broker for shape.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")
#: A pairing code is exactly lowercase hexadecimal text (32 characters).
_PAIRING_CODE_RE = re.compile(r"^[0-9a-f]{32}$")
#: The broker endpoint must be an exact https origin on port 443 with no
#: credentials, query or fragment — outbound-only, TLS-only.
_BROKER_URL_RE = re.compile(r"^https://[A-Za-z0-9.\-]+(?::443)?(?:/[^\s?#]*)?$")

DEVICE_ID_BYTES = 16
MAX_STATE_FILE_BYTES = 64 * 1024

#: Fields persisted in the enrollment record. Deliberately free of the raw
#: device credential, the pairing code and the pairing challenge id: none of
#: them are ever written to this file.
RECORD_KEYS = frozenset(
    {
        "contract_version",
        "device_id",
        "binding_ref",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "credential_expires_at",
        "device_lifecycle",
        "enrolled_at",
        "revoked",
        "blocked_reason",
    }
)

#: S1 server contract this client aligns with (LOCAL1 PR #4438, read-only
#: mirror of ``padiem.connector-enrollment.v1``). The Connector never mints,
#: stores or modifies that contract; it only speaks the client side of it.
S1_ENROLLMENT_CONTRACT_VERSION = "padiem.connector-enrollment.v1"

#: Canonical pairing-proof transcript and prefix. Byte-identical to S1
#: ``local_agent_broker_pairing.PAIRING_PROOF_TRANSCRIPT`` /
#: ``PAIRING_PROOF_REF_PREFIX``; the proof-vector test pins the values so a
#: silent divergence can never ship.
ENROLLMENT_PROOF_TRANSCRIPT = "claw-local-agent-pairing-proof.v1"
ENROLLMENT_PROOF_REF_PREFIX = "pairing-proof:"
_PROOF_REF_RE = re.compile(r"^pairing-proof:[0-9a-f]{64}$")

#: The generic pairing route refuses enrollment-bound challenges with this S1
#: reason before any mutation. The Connector therefore never calls generic
#: ``redeem()`` for enrollment; attempting the legacy path raises with the
#: client-side reason below instead of registering anything.
ENROLLMENT_BOUND_CHALLENGE_GENERIC_REASON = (
    "enrollment_bound_challenge_requires_scoped_redemption"
)
ENROLLMENT_SCOPED_REDEMPTION_REQUIRED = "enrollment_scoped_redemption_required"

#: Bounded refusal vocabulary the enrollment server may return. Mirrors the S1
#: ``enrollment_*`` / ``canonical_*`` reasons. Unknown text is never echoed,
#: only mapped to the fallback.
ENROLLMENT_REFUSAL_REASONS = frozenset(
    {
        "canonical_session_required",
        "canonical_session_inactive",
        "canonical_subject_not_user",
        "canonical_tenant_required",
        "canonical_session_product_not_reviewed",
        "enrollment_scope_unavailable",
        "enrollment_scope_unverified",
        "enrollment_scope_owner_mismatch",
        "enrollment_scope_product_scoped_denied",
        "enrollment_consent_required",
        "enrollment_consent_withdrawn",
        "enrollment_consent_scope_mismatch",
        "enrollment_consent_device_mismatch",
        "enrollment_binding_absent",
        "enrollment_consent_swap_denied",
        "enrollment_device_swap_denied",
        "enrollment_binding_owner_mismatch",
        "enrollment_binding_scope_mismatch",
        "enrollment_consent_liveness_dependency_unmet",
        "enrollment_dependency_unavailable",
        "enrollment_challenge_not_found",
        "enrollment_challenge_expired",
        "enrollment_duplicate_redeem_denied",
        "enrollment_proof_invalid",
        "enrollment_rate_limited",
        "enrollment_capacity_exhausted",
        "enrollment_scoped_redemption_required",
        "enrollment_duplicate_device_denied",
        "enrollment_binding_revoked_denied",
        "enrollment_credential_expired_denied",
        "enrollment_dependency_refused",
    }
)
ENROLLMENT_REFUSAL_FALLBACK = "enrollment_dependency_refused"

#: No authenticated enrollment HTTP endpoint exists yet: S1 exposes library
#: functions only (``issue_connector_enrollment_challenge`` /
#: ``redeem_connector_enrollment``) and the pairing HTTP bridge serves the
#: generic route. Until CENTRAL wires a product route, every live redemption
#: fails closed through ``UnconfiguredEnrollmentServerPort``.
SERVER_ENROLLMENT_ENDPOINT_EXISTS = False
ENROLLMENT_SERVER_WIRED = False
#: Durable consent authority is server-side and unwired
#: (``CONSENT_LIVENESS_AUTHORITY_IMPLEMENTED=False`` in S1). The Connector
#: never substitutes its own liveness verdict.
DURABLE_CONSENT_AUTHORITY_WIRED = False


class BrokerNotConfiguredError(RuntimeError):
    """Raised when no pinned broker endpoint is configured.

    This is the honest, fail-closed answer for the current deployment state: the
    LOCAL1 pairing/session/heartbeat routes are not activated, so no live
    enrollment may be claimed.
    """


class EnrollmentContractError(RuntimeError):
    """Raised when caller-supplied enrollment material violates the contract."""


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise EnrollmentContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _now_default() -> datetime:
    return datetime.now(timezone.utc)


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise EnrollmentContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _pairing_code(value: Any) -> str:
    if not isinstance(value, str) or not _PAIRING_CODE_RE.fullmatch(value.strip()):
        raise EnrollmentContractError(
            "pairing code must be exact 32-character lowercase hexadecimal text"
        )
    return value.strip()


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value, "timestamp").isoformat().replace(
        "+00:00", "Z"
    )


#: Environment override for the per-user Connector state directory. Tests and
#: diagnostics use it so they never touch a real user profile; production uses
#: the per-user location above. It never relocates the credential store, which
#: stays owned by the canonical kagent credential store.
STATE_DIR_ENV_VAR = "CLAW_CONNECT_STATE_DIR"


def default_state_dir() -> Path:
    """Per-user Connector state directory. Never a system-wide path."""
    override = os.environ.get(STATE_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    if sys_platform_is_win32():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "Padiem" / "ClawConnect"
    return Path.home() / ".padiem-claw-connect"


def sys_platform_is_win32() -> bool:
    return os.name == "nt"


def project_connector_status(
    *,
    enrolled: bool,
    blocked: bool,
    paused: bool,
    connecting: bool,
    connected: bool,
) -> EnrollmentDisplayState:
    """Project the operator-visible Connector state from facts only.

    Precedence is fixed and deliberately conservative: an unenrolled device can
    never look connected, a revoked device can never look connected again, and
    ``CONNECTED`` is only reachable when a *server-projected* ONLINE binding was
    actually observed. ``OFFLINE`` is the honest answer for an enrolled device
    that currently has no live session — including one the user disconnected.
    """
    if not enrolled:
        return EnrollmentDisplayState.UNREGISTERED
    if blocked:
        return EnrollmentDisplayState.REVOKED
    if paused:
        return EnrollmentDisplayState.PAUSED
    if connecting:
        return EnrollmentDisplayState.CONNECTING
    if connected:
        return EnrollmentDisplayState.CONNECTED
    return EnrollmentDisplayState.OFFLINE


def _lifecycle_to_connector_state(lifecycle: str | None) -> tuple[bool, bool, bool]:
    """Map a canonical lifecycle value to (enrolled, blocked, online-capable)."""
    if lifecycle is None or lifecycle == LIFECYCLE_UNPAIRED:
        return (False, False, False)
    if lifecycle in (LIFECYCLE_REVOKED, LIFECYCLE_CREDENTIAL_EXPIRED):
        return (True, True, False)
    if lifecycle == LIFECYCLE_ONLINE:
        return (True, False, True)
    # paired_offline / update_required: enrolled, not blocked, not online.
    return (True, False, False)

@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    """Secret-free result of one enrollment attempt.

    ``device_id`` and ``binding_ref`` are the Broker device identity that every
    PADIEM product (Chat/Claw/B66) reads. Preserving them across re-installs is
    what prevents duplicate PC registrations.
    """

    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_expires_at: datetime
    enrolled_at: datetime
    lifecycle: str

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "credential_expires_at": _iso(self.credential_expires_at),
            "enrolled_at": _iso(self.enrolled_at),
            "lifecycle": self.lifecycle,
            "raw_device_credential": False,
            "pairing_code_persisted": False,
            "pairing_challenge_id_persisted": False,
            "public_inbound_port": False,
        }


@dataclass
class EnrollmentRecord:
    """Everything the Connector must remember between runs — and nothing else."""

    device_id: str
    binding_ref: str | None = None
    account_ref: str | None = None
    workspace_ref: str | None = None
    credential_generation: int | None = None
    credential_expires_at: datetime | None = None
    device_lifecycle: str = LIFECYCLE_UNPAIRED
    enrolled_at: datetime | None = None
    revoked: bool = False
    blocked_reason: str | None = None
    contract_version: str = ENROLLMENT_CONTRACT_VERSION

    def is_enrolled(self) -> bool:
        """True once this PC holds a Broker device binding.

        A revoked or expired device stays *enrolled* — the binding still exists
        — and is reported as **blocked** instead. That keeps "never registered"
        distinct from "access revoked", which the operator must be able to tell
        apart.
        """
        return self.binding_ref is not None

    def lifecycle(self) -> str | None:
        """The canonical Broker lifecycle value, or None when never enrolled."""
        if not self.is_enrolled():
            return None
        if self.revoked:
            return LIFECYCLE_REVOKED
        return self.device_lifecycle

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "credential_expires_at": _iso(self.credential_expires_at),
            "device_lifecycle": self.device_lifecycle,
            "enrolled_at": _iso(self.enrolled_at),
            "revoked": self.revoked,
            "blocked_reason": self.blocked_reason,
        }

    @classmethod
    def from_dict(cls, data: object) -> "EnrollmentRecord":
        if type(data) is not dict:
            raise EnrollmentContractError("enrollment record must be a mapping")
        if set(data) != RECORD_KEYS:
            raise EnrollmentContractError(
                "enrollment record schema is closed; refusing an unknown shape"
            )
        if data["contract_version"] != ENROLLMENT_CONTRACT_VERSION:
            raise EnrollmentContractError("enrollment record contract version is unsupported")
        device_id = _safe_ref(data["device_id"], "device_id")
        raw_expiry = data["credential_expires_at"]
        if raw_expiry is not None and not isinstance(raw_expiry, str):
            raise EnrollmentContractError("credential_expires_at must be ISO-8601 text or null")
        raw_enrolled = data["enrolled_at"]
        if raw_enrolled is not None and not isinstance(raw_enrolled, str):
            raise EnrollmentContractError("enrolled_at must be ISO-8601 text or null")
        generation = data["credential_generation"]
        if generation is not None and (isinstance(generation, bool) or not isinstance(generation, int)):
            raise EnrollmentContractError("credential_generation must be an integer or null")
        return cls(
            device_id=device_id,
            binding_ref=(
                None
                if data["binding_ref"] is None
                else _safe_ref(data["binding_ref"], "binding_ref")
            ),
            account_ref=(
                None if data["account_ref"] is None else _safe_ref(data["account_ref"], "account_ref")
            ),
            workspace_ref=(
                None
                if data["workspace_ref"] is None
                else _safe_ref(data["workspace_ref"], "workspace_ref")
            ),
            credential_generation=generation,
            credential_expires_at=(
                None if raw_expiry is None else _parse_iso(raw_expiry, "credential_expires_at")
            ),
            device_lifecycle=str(data["device_lifecycle"]),
            enrolled_at=None if raw_enrolled is None else _parse_iso(raw_enrolled, "enrolled_at"),
            revoked=bool(data["revoked"]),
            blocked_reason=(
                None if data["blocked_reason"] is None else str(data["blocked_reason"])
            ),
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "credential_expires_at": _iso(self.credential_expires_at),
            "device_lifecycle": self.lifecycle(),
            "revoked": self.revoked,
            "blocked_reason": self.blocked_reason,
        }


def _parse_iso(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EnrollmentContractError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def build_enrollment_proof_ref(
    *, challenge_id: str, device_id: str, pairing_code: str
) -> str:
    """HMAC-SHA256 possession proof over the canonical pairing transcript.

    Byte-identical to S1 ``pairing_proof_ref``: key is the one-time pairing
    code (UTF-8), message is
    ``"<transcript>\\n<challenge_id>\\n<device_id>"`` (UTF-8). The Connector
    sends only this proof — the raw code is never persisted, logged or sent
    beyond the single redemption call that computes it.
    """
    challenge = _safe_ref(challenge_id, "challenge_id")
    device = _safe_ref(device_id, "device_id")
    code = _pairing_code(pairing_code)
    message = f"{ENROLLMENT_PROOF_TRANSCRIPT}\n{challenge}\n{device}".encode("utf-8")
    digest = hmac.new(code.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{ENROLLMENT_PROOF_REF_PREFIX}{digest}"


def _proof_ref(value: Any, field_name: str = "proof_ref") -> str:
    if not isinstance(value, str) or not _PROOF_REF_RE.fullmatch(value.strip()):
        raise EnrollmentContractError(
            f"{field_name} must be a canonical HMAC-SHA256 proof reference"
        )
    return value.strip()


@dataclass(frozen=True, slots=True)
class EnrollmentRedemptionRequest:
    """The only thing the Connector ever sends to the enrollment server.

    Possession proof only: ``challenge_id`` + ``device_id`` + ``proof_ref``.
    There are deliberately NO owner / workspace / consent / password / cookie /
    session fields — the server derives scope from its own canonical session
    and reads consent from its own durable record. A request carrying any such
    field must be rejected by the server and is never built here.
    """

    challenge_id: str
    device_id: str
    proof_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "challenge_id", _safe_ref(self.challenge_id, "challenge_id")
        )
        object.__setattr__(self, "device_id", _safe_ref(self.device_id, "device_id"))
        object.__setattr__(self, "proof_ref", _proof_ref(self.proof_ref))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "device_id": self.device_id,
            "proof_ref": self.proof_ref,
            "client_asserted_owner": False,
            "client_asserted_scope": False,
            "client_asserted_consent": False,
            "password_transmitted": False,
            "cookie_transmitted": False,
        }


@dataclass(frozen=True, slots=True)
class EnrollmentRedemptionResponse:
    """Authenticated server verdict for one redemption request.

    Success carries the server-owned binding facts (scope included — the
    Connector accepts the server's account/workspace as authoritative and never
    supplies its own). Refusal carries one bounded ``reason`` only; upstream
    text is never echoed. Either shape is verified by
    :func:`verify_enrollment_receipt` before anything is persisted.
    """

    ok: bool
    binding_ref: str | None = None
    device_id: str | None = None
    account_ref: str | None = None
    workspace_ref: str | None = None
    credential_generation: int | None = None
    credential_expires_at: datetime | None = None
    consent_id: str | None = None
    reason: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        if self.ok is not True and self.ok is not False:
            raise EnrollmentContractError("enrollment response ok must be a boolean")
        if self.ok:
            if self.reason is not None:
                raise EnrollmentContractError(
                    "a successful enrollment response carries no refusal reason"
                )
            for field_name in (
                "binding_ref",
                "device_id",
                "account_ref",
                "workspace_ref",
                "consent_id",
            ):
                _safe_ref(getattr(self, field_name), field_name)
            generation = self.credential_generation
            if (
                not isinstance(generation, int)
                or isinstance(generation, bool)
                or generation < 1
            ):
                raise EnrollmentContractError(
                    "credential_generation must be a positive integer"
                )
            _aware(self.credential_expires_at, "credential_expires_at")
        else:
            if (
                not isinstance(self.reason, str)
                or self.reason not in ENROLLMENT_REFUSAL_REASONS
            ):
                raise EnrollmentContractError(
                    f"enrollment refusal must carry a bounded reason, "
                    f"got {self.reason!r}"
                )
            if self.retryable is not True and self.retryable is not False:
                raise EnrollmentContractError("retryable must be a boolean")

    def safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            payload.update(
                {
                    "binding_ref": self.binding_ref,
                    "device_id": self.device_id,
                    "account_ref": self.account_ref,
                    "workspace_ref": self.workspace_ref,
                    "credential_generation": self.credential_generation,
                    "credential_expires_at": _iso(self.credential_expires_at),
                    "consent_id": self.consent_id,
                    "raw_device_credential": False,
                }
            )
        else:
            payload.update({"reason": self.reason, "retryable": self.retryable})
        return payload


class EnrollmentServerPort(Protocol):
    """Authenticated S1 enrollment redemption endpoint (server side).

    Deployment contract for the future product route wrapping S1
    ``redeem_connector_enrollment``: the transport must present the canonical
    session server-side (never accept one from the Connector), resolve
    owner/workspace itself, re-read the durable consent record, probe the
    server-owned binding, call the scoped ``redeem_enrollment`` and return the
    receipt. Until such a route exists, deployments wire
    :class:`UnconfiguredEnrollmentServerPort` and every redemption fails
    closed — never as a synthetic success.
    """

    def redeem_enrollment(
        self, request: EnrollmentRedemptionRequest, *, now: datetime
    ) -> EnrollmentRedemptionResponse:
        ...


class UnconfiguredEnrollmentServerPort:
    """Fail-closed default: no enrollment server route, no enrollment."""

    def redeem_enrollment(
        self, request: EnrollmentRedemptionRequest, *, now: datetime
    ) -> EnrollmentRedemptionResponse:
        del request, now
        raise BrokerNotConfiguredError(
            "authenticated enrollment server route is not wired "
            "(BLOCKED_DEPENDENCY: S1 product route + durable consent authority); "
            "enrollment cannot be completed"
        )


def verify_enrollment_receipt(
    response: EnrollmentRedemptionResponse,
    *,
    expected_device_id: str,
    now: datetime,
) -> EnrollmentRedemptionResponse:
    """Verify an authenticated server success receipt before persisting anything.

    Refusals (``ok=False``) pass through for the caller to map to a bounded
    error. A success receipt is accepted only when it names this exact device,
    carries a live credential generation/expiry and well-formed scope refs.
    Anything else raises — an unauthenticated or mismatched receipt can never
    produce a binding record or a CONNECTED display.
    """
    if not isinstance(response, EnrollmentRedemptionResponse):
        raise EnrollmentContractError(
            "enrollment server returned an unauthenticated receipt shape"
        )
    if not response.ok:
        return response
    if response.device_id != expected_device_id:
        raise EnrollmentContractError("enrollment_device_swap_denied")
    observed_at = _aware(now, "now")
    expires_at = _aware(response.credential_expires_at, "credential_expires_at")
    if expires_at <= observed_at:
        raise EnrollmentContractError("enrollment_credential_expired_denied")
    return response


class ConnectorEnrollment:
    """The Connector's enrollment service.

    It answers three questions and nothing more: *is this PC registered?*,
    *what is its Broker device identity?*, and *what should the UI show?*.
    Every live redemption goes through the authenticated S1 enrollment server
    route (``EnrollmentServerPort``) so no second authority is created here.
    The Connector is never an authentication or approval authority: it proves
    possession of the one-time code and accepts the server's verdict.
    """

    def __init__(
        self,
        *,
        state_dir: str | os.PathLike[str] | None = None,
        web_url: str = WEB_URL,
        broker_base_url: str = "",
        clock: Callable[[], datetime] | None = None,
        pairing_client_factory: Callable[..., Any] | None = None,
        enrollment_server_factory: Callable[..., EnrollmentServerPort] | None = None,
    ) -> None:
        self._state_dir = (
            Path(state_dir).expanduser() if state_dir is not None else default_state_dir()
        )
        self._web_url = web_url
        self._broker_base_url = (broker_base_url or "").strip()
        self._clock = clock or _now_default
        # Legacy seam, retained only to fail closed with a migration signal:
        # the generic pairing client path is closed for enrollment (S1 refuses
        # enrollment-bound challenges on it before any mutation), so it is
        # never called from the enrollment flow.
        self._pairing_client_factory = pairing_client_factory
        self._enrollment_server_factory = enrollment_server_factory
        self._record: EnrollmentRecord | None = None

    # -- configuration ------------------------------------------------------
    @property
    def state_dir(self) -> Path:
        """Per-user Connector state directory (never a system-wide path)."""
        return self._state_dir

    @property
    def state_file(self) -> Path:
        return self._state_dir / "enrollment.json"

    def broker_configured(self) -> bool:
        """True only when a live, pinned broker endpoint is configured.

        Failing closed here is deliberate: with no endpoint the LOCAL1 routes are
        not activated, and an unconfigured Connector must look unregistered
        rather than pretend to be connected.
        """
        if not self._broker_base_url:
            return False
        if not _BROKER_URL_RE.fullmatch(self._broker_base_url):
            raise EnrollmentContractError(
                "broker base URL must be an https origin on port 443 without "
                "credentials, query or fragment"
            )
        return True

    # -- persistence (no secrets, ever) -------------------------------------
    def record(self) -> EnrollmentRecord:
        if self._record is None:
            self._record = self._load_or_create()
        return self._record

    def _load_or_create(self) -> EnrollmentRecord:
        path = self.state_file
        if not path.exists():
            # The device id must be stable from the *first* launch, before any
            # login: the reviewed pairing code is redeemed against this exact
            # identity, so generating it later would bind a different device.
            record = EnrollmentRecord(device_id=self._new_device_id())
            self._write(record)
            return record
        raw = path.read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > MAX_STATE_FILE_BYTES:
            raise EnrollmentContractError("enrollment record exceeds its size bound")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EnrollmentContractError("enrollment record is not valid JSON") from exc
        return EnrollmentRecord.from_dict(data)

    def _write(self, record: EnrollmentRecord) -> None:
        """Atomically persist the record. It contains no secret material."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        path = self.state_file
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)

    def flush(self) -> None:
        """Persist the record. Never contains a credential, code or challenge."""
        self._write(self.record())

    @staticmethod
    def _new_device_id() -> str:
        # A stable, per-installation, opaque Broker device id. It carries no
        # personal data and is reused across reinstalls so the same PC keeps one
        # Broker identity.
        return secrets.token_hex(DEVICE_ID_BYTES)

    def device_identity(self) -> dict[str, Any]:
        """Safe projection of the Broker device identity for status/web use."""
        record = self.record()
        return {
            "device_id": record.device_id,
            "binding_ref": record.binding_ref,
            "product": CONNECT_PRODUCT,
            "web_url": self._web_url,
            "broker_endpoint_configured": self.broker_configured(),
            "raw_device_credential": False,
        }

    # -- login / consent ----------------------------------------------------
    def login_url(self) -> str:
        """The official PADIEM authentication surface the user must use.

        The Connector never renders its own credential form and never captures a
        password or a browser cookie: the user signs in here, and the resulting
        session issues the pairing code the Connector redeems.
        """
        return self._web_url

    def begin_login(self) -> str:
        """Record that a login was started and return the official login URL."""
        self.record()
        return self.login_url()

    def complete_login(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        now: datetime | None = None,
    ) -> EnrollmentResult:
        """Redeem a reviewed pairing code into a canonical device binding.

        The code is proven through the authenticated S1 enrollment server
        route only (scoped redemption). Fails closed unless a pinned endpoint
        and a wired enrollment server port are both configured; every refusal
        leaves zero bindings and consumes nothing locally.
        """
        moment = _aware(now, "now") if now is not None else self._clock()
        challenge = _safe_ref(challenge_id, "challenge_id")
        code = _pairing_code(pairing_code)
        record = self.record()

        if not self.broker_configured():
            raise BrokerNotConfiguredError(
                "no pinned broker endpoint is configured; the LOCAL1 pairing route "
                "is not activated, so enrollment must not be claimed"
            )
        if record.revoked:
            raise BrokerNotConfiguredError(
                "this device binding was revoked; a fresh login is required"
            )

        # A recorded binding without its canonical owner/scope is corrupted.
        # These missing fields are already observable locally: refuse BEFORE
        # sending the one-time redemption proof to the server. Do not create a
        # fresh upstream binding/credential delivery only to reject it later.
        if record.is_enrolled():
            if record.account_ref is None:
                raise EnrollmentContractError("enrollment_binding_owner_mismatch")
            if record.workspace_ref is None:
                raise EnrollmentContractError("enrollment_binding_scope_mismatch")

        result = self._redeem_via_enrollment_server(
            challenge_id=challenge, pairing_code=code, device_id=record.device_id, now=moment
        )

        # #4139 S2 account isolation: an existing PC registration belongs to the
        # account that enrolled it. Re-pointing the same device identity at a
        # different account would hand the product sessions that were enrolled
        # against the previous account over to the new one, so the receipt is
        # refused here and the existing binding is left exactly as it was.
        #
        # This is a *local* fail-closed action and nothing more. It runs after
        # the server call because the account is only knowable from the
        # receipt, so by the time it refuses the request has already left the
        # device: the refusal proves that *this PC* did not adopt the receipt,
        # and never that the upstream challenge, the Broker binding or the
        # delivered credential were left untouched or compensated. Server-side
        # duplicate-binding, revoke and compensation authority stays with the
        # canonical Broker and the enrollment server; the connector neither
        # performs nor claims one. A divergence between what the server did and
        # what this device recorded is a server reconciliation/security matter,
        # not a routine user account switch.
        #
        # ``clear_enrollment`` is likewise *not* an ownership transfer. It
        # clears only the local view of the binding and deliberately leaves the
        # protected credential store, the Broker binding and any active Broker
        # session alone, so another owner still cannot adopt this device after a
        # local logout. An owner-authorized, server-confirmed
        # revocation/session invalidation, a reviewed credential-store cleanup
        # and a new enrollment are separately required first. The stable device
        # id is preserved throughout.
        #
        # The preflight above already refuses a binding missing a canonical
        # owner or workspace BEFORE contacting the server. The checks below
        # also defend against mismatched success receipts AFTER redemption:
        # that late refusal preserves local state but does not prove upstream
        # rollback. Both reasons remain in the bounded S1/S2 vocabulary and
        # no server text or identifier is echoed.
        #
        # Flipping this guard is not a local decision. Account switching is not
        # a valid relaxation: a PC's device identity must never silently change
        # owner. Any future relaxation needs a reviewed justification that
        # answers how the previous account's product sessions stop referring to
        # this device identity.
        if record.is_enrolled():
            if record.account_ref is None or result.account_ref != record.account_ref:
                raise EnrollmentContractError("enrollment_binding_owner_mismatch")
            if record.workspace_ref is None or result.workspace_ref != record.workspace_ref:
                raise EnrollmentContractError("enrollment_binding_scope_mismatch")

        record.binding_ref = result.binding_ref
        record.account_ref = result.account_ref
        record.workspace_ref = result.workspace_ref
        record.credential_generation = result.credential_generation
        record.credential_expires_at = result.credential_expires_at
        record.device_lifecycle = LIFECYCLE_PAIRED_OFFLINE
        record.enrolled_at = moment
        record.revoked = False
        record.blocked_reason = None
        self.flush()
        return result

    def _redeem_via_enrollment_server(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        device_id: str,
        now: datetime,
    ) -> EnrollmentResult:
        """Redeem through the authenticated S1 enrollment server route only.

        The generic pairing-client redeem path is never used here: S1 refuses
        enrollment-bound challenges on it with
        ``enrollment_bound_challenge_requires_scoped_redemption`` before any
        mutation, so calling it could never succeed. The seam is the server
        port so the offline tests never open a socket and so a deployment
        supplies the pinned production transport without this module growing
        a second contract. The one-time code is consumed into the possession
        proof and never persisted.
        """
        if self._enrollment_server_factory is None:
            if self._pairing_client_factory is not None:
                raise EnrollmentContractError(
                    f"{ENROLLMENT_SCOPED_REDEMPTION_REQUIRED}: this enrollment "
                    "challenge must be redeemed through the authenticated "
                    "enrollment server route; the generic pairing client path "
                    "is closed for enrollment"
                )
            raise BrokerNotConfiguredError(
                "authenticated enrollment server route is not wired "
                "(BLOCKED_DEPENDENCY: S1 product route + durable consent "
                "authority); enrollment cannot be completed"
            )
        try:
            server = self._enrollment_server_factory(
                broker_base_url=self._broker_base_url, device_id=device_id
            )
        except (BrokerNotConfiguredError, EnrollmentContractError):
            raise
        except Exception as exc:
            raise BrokerNotConfiguredError(
                "enrollment server port failed to initialise; failing closed"
            ) from exc
        proof_ref = build_enrollment_proof_ref(
            challenge_id=challenge_id, device_id=device_id, pairing_code=pairing_code
        )
        request = EnrollmentRedemptionRequest(
            challenge_id=challenge_id, device_id=device_id, proof_ref=proof_ref
        )
        try:
            response = server.redeem_enrollment(request, now=now)
        except (BrokerNotConfiguredError, EnrollmentContractError):
            raise
        except Exception as exc:
            raise BrokerNotConfiguredError(
                "enrollment server unreachable; failing closed without "
                "claiming any registration"
            ) from exc
        verified = verify_enrollment_receipt(
            response, expected_device_id=device_id, now=now
        )
        if not verified.ok:
            raise EnrollmentContractError(
                verified.reason or ENROLLMENT_REFUSAL_FALLBACK
            )
        # Success lands as paired_offline. ONLINE may only come later from the
        # server projection via mark_online(); the server receipt itself never
        # carries a lifecycle claim.
        return EnrollmentResult(
            device_id=device_id,
            binding_ref=_safe_ref(verified.binding_ref, "binding_ref"),
            account_ref=_safe_ref(verified.account_ref, "account_ref"),
            workspace_ref=_safe_ref(verified.workspace_ref, "workspace_ref"),
            credential_generation=int(verified.credential_generation),
            credential_expires_at=_aware(
                verified.credential_expires_at, "credential_expires_at"
            ),
            enrolled_at=now,
            lifecycle=LIFECYCLE_PAIRED_OFFLINE,
        )

    # -- revoke / logout ----------------------------------------------------
    def mark_revoked(self, reason: str) -> None:
        """Record an observed revocation. Auto-start must stop immediately."""
        record = self.record()
        record.revoked = True
        record.blocked_reason = str(reason)[:256]
        record.device_lifecycle = LIFECYCLE_REVOKED
        self.flush()

    def mark_credential_expired(self) -> None:
        record = self.record()
        record.device_lifecycle = LIFECYCLE_CREDENTIAL_EXPIRED
        record.blocked_reason = "credential_expired"
        self.flush()

    def mark_offline(self) -> None:
        """Observed loss of the live session (offline, sleep, network loss)."""
        record = self.record()
        if record.revoked:
            return
        record.device_lifecycle = LIFECYCLE_PAIRED_OFFLINE
        self.flush()

    def mark_online(self) -> None:
        """Record a *server-projected* ONLINE observation.

        The caller must already hold the server-owned session + heartbeat
        correlation from ``kagent.local_agent_server_projection``; this method
        only persists that observation and can never manufacture it.
        """
        record = self.record()
        if record.revoked:
            return
        record.device_lifecycle = LIFECYCLE_ONLINE
        self.flush()

    def clear_enrollment(self) -> None:
        """Log out: forget the *local* view of the binding. Not a revocation.

        The device id is preserved, and the protected credential is
        deliberately *not* deleted here — revocation and credential deletion
        are owned by the canonical credential store, and a rollback is a
        disable rather than a delete. The canonical Broker binding and any
        active Broker session are untouched too, and the canonical Broker
        refuses a second binding for a device that already has an active one.
        This call therefore cannot hand the device to another owner: an
        owner-authorized, server-confirmed revocation/session invalidation, a
        reviewed credential-store cleanup and a new enrollment are separately
        required first. The connector never performs or claims any of those.
        """
        record = self.record()
        record.binding_ref = None
        record.account_ref = None
        record.workspace_ref = None
        record.credential_generation = None
        record.credential_expires_at = None
        record.device_lifecycle = LIFECYCLE_UNPAIRED
        record.enrolled_at = None
        record.revoked = False
        record.blocked_reason = None
        self.flush()

    def project_state(
        self,
        *,
        paused: bool = False,
        connecting: bool = False,
        connected: bool = False,
    ) -> EnrollmentDisplayState:
        """Operator-visible Connector state projected from persisted device facts.

        A local ``connected=True`` can never produce ``CONNECTED`` on its own:
        the persisted lifecycle must already be ``online``, which only the
        server projection may set. This is the single place the Connector
        decides what the tray and the web claim.
        """
        lifecycle = self.record().lifecycle()
        enrolled, blocked, _ = _lifecycle_to_connector_state(lifecycle)
        server_online = lifecycle == LIFECYCLE_ONLINE and connected
        return project_connector_status(
            enrolled=enrolled,
            blocked=blocked,
            paused=paused,
            connecting=connecting,
            connected=server_online,
        )

    # -- status -------------------------------------------------------------
    def status_snapshot(
        self,
        *,
        paused: bool = False,
        connecting: bool = False,
        connected: bool = False,
    ) -> dict[str, Any]:
        """Machine-readable Connector status. Never claims an unobserved state."""
        record = self.record()
        state = self.project_state(
            paused=paused, connecting=connecting, connected=connected
        )
        enrolled, blocked, _ = _lifecycle_to_connector_state(record.lifecycle())
        return {
            "enrolled": record.is_enrolled(),
            "device_state": state.value,
            "device_lifecycle": record.lifecycle(),
            "device_id": record.device_id,
            "binding_ref": record.binding_ref,
            "account_ref": record.account_ref,
            "workspace_ref": record.workspace_ref,
            "blocked": blocked,
            "blocked_reason": record.blocked_reason,
            "broker_endpoint_configured": self.broker_configured(),
            "credential_expires_at": _iso(record.credential_expires_at),
            "pairing_code_persisted": False,
            "raw_device_credential": False,
            "public_inbound_port": False,
        }


__all__ = [
    "BrokerNotConfiguredError",
    "ConnectorEnrollment",
    "DURABLE_CONSENT_AUTHORITY_WIRED",
    "ENROLLMENT_CONTRACT_VERSION",
    "ENROLLMENT_PROOF_REF_PREFIX",
    "ENROLLMENT_PROOF_TRANSCRIPT",
    "ENROLLMENT_REFUSAL_FALLBACK",
    "ENROLLMENT_REFUSAL_REASONS",
    "ENROLLMENT_SCOPED_REDEMPTION_REQUIRED",
    "ENROLLMENT_SERVER_WIRED",
    "EnrollmentContractError",
    "EnrollmentRecord",
    "EnrollmentRedemptionRequest",
    "EnrollmentRedemptionResponse",
    "EnrollmentResult",
    "EnrollmentServerPort",
    "S1_ENROLLMENT_CONTRACT_VERSION",
    "SERVER_ENROLLMENT_ENDPOINT_EXISTS",
    "UnconfiguredEnrollmentServerPort",
    "build_enrollment_proof_ref",
    "verify_enrollment_receipt",
    "LIFECYCLE_ONLINE",
    "LIFECYCLE_PAIRED_OFFLINE",
    "LIFECYCLE_REVOKED",
    "LIFECYCLE_UNPAIRED",
    "project_connector_status",
]
