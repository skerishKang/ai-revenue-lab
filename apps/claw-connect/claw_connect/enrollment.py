"""PADIEM Connector enrollment — one reviewed login, then one canonical binding.

Authority boundaries (see ``docs/architecture/PADIEM_CONNECTOR_PLATFORM_DECISION_20261012.md``):

* The **browser is never authoritative** for account or workspace identity. This
  module only carries the proofs the reviewed user supplies from the official
  PADIEM authentication surface; it never collects a password, a browser cookie
  or a private browser profile.
* Device pairing, credential custody and the ONLINE transition are **delegated**
  to the canonical Local Agent Broker surfaces in ``kagent``
  (``local_agent_broker_pairing_client``, ``local_agent_secure_transport``,
  ``local_agent_server_projection``). This file adds **no** second pairing,
  device-lifecycle, session or credential authority.
* The raw device credential is never read, logged, projected or written here. It
  is persisted only by the canonical protected credential store.
* Enrollment is **outbound-only**. No inbound socket is opened, no public inbound
  port is required and no UPnP/port mapping is attempted.
* Registration is **not** a P01 READ/WRITE approval. Nothing here grants one.

Because the LOCAL1 server side is not deployed yet
(``PRODUCTION_ACTIVATION=NO`` / ``LIVE_PRODUCTION_PAIRING_CALL=0`` in
``local_agent_pairing_activation_3102``), every live call fails closed until a
pinned broker endpoint is explicitly configured. A missing or partial
configuration is reported as blocked, never as a success.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from . import CONNECT_PRODUCT, WEB_URL
from .connection import ConnectionState

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
) -> ConnectionState:
    """Project the operator-visible Connector state from facts only.

    Precedence is fixed and deliberately conservative: an unenrolled device can
    never look connected, a revoked device can never look connected again, and
    ``CONNECTED`` is only reachable when a *server-projected* ONLINE binding was
    actually observed. ``OFFLINE`` is the honest answer for an enrolled device
    that currently has no live session — including one the user disconnected.
    """
    if not enrolled:
        return ConnectionState.UNREGISTERED
    if blocked:
        return ConnectionState.REVOKED
    if paused:
        return ConnectionState.PAUSED
    if connecting:
        return ConnectionState.CONNECTING
    if connected:
        return ConnectionState.CONNECTED
    return ConnectionState.OFFLINE


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


class ConnectorEnrollment:
    """The Connector's enrollment service.

    It answers three questions and nothing more: *is this PC registered?*,
    *what is its Broker device identity?*, and *what should the UI show?*.
    Every live network operation is delegated to the canonical Local Agent
    Broker client so no second authority is created here.
    """

    def __init__(
        self,
        *,
        state_dir: str | os.PathLike[str] | None = None,
        web_url: str = WEB_URL,
        broker_base_url: str = "",
        clock: Callable[[], datetime] | None = None,
        pairing_client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._state_dir = (
            Path(state_dir).expanduser() if state_dir is not None else default_state_dir()
        )
        self._web_url = web_url
        self._broker_base_url = (broker_base_url or "").strip()
        self._clock = clock or _now_default
        self._pairing_client_factory = pairing_client_factory
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

        Fails closed unless a pinned broker endpoint is configured.
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

        result = self._redeem_with_canonical_client(
            challenge_id=challenge, pairing_code=code, device_id=record.device_id, now=moment
        )

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

    def _redeem_with_canonical_client(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        device_id: str,
        now: datetime,
    ) -> EnrollmentResult:
        """Delegate redemption to the canonical Local Agent Broker pairing client.

        The seam is the request port so the offline tests never open a socket
        and so a deployment supplies the pinned production transport without
        this module growing a second contract.
        """
        if self._pairing_client_factory is None:
            raise BrokerNotConfiguredError(
                "canonical Local Agent Broker pairing client is not wired; "
                "enrollment cannot be completed"
            )
        client = self._pairing_client_factory(
            broker_base_url=self._broker_base_url, device_id=device_id
        )
        enrollment = client.redeem(
            challenge_id=challenge_id, pairing_code=pairing_code, device_id=device_id, now=now
        )
        binding = enrollment.binding
        if binding.state is not None and getattr(binding.state, "value", None) not in (
            None,
            LIFECYCLE_PAIRED_OFFLINE,
        ):
            raise EnrollmentContractError(
                "canonical pairing client returned a non-offline binding; "
                "ONLINE may only come from the server projection"
            )
        return EnrollmentResult(
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=int(binding.credential_generation),
            credential_expires_at=_aware(binding.credential_expires_at, "credential_expires_at"),
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
        """Log out: forget the binding, keep the device id and the credential store.

        The protected credential is deliberately *not* deleted here — revocation
        and credential deletion are owned by the canonical credential store, and
        a rollback is a disable rather than a delete.
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
    ) -> ConnectionState:
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
    "EnrollmentContractError",
    "EnrollmentRecord",
    "EnrollmentResult",
    "ENROLLMENT_CONTRACT_VERSION",
    "LIFECYCLE_ONLINE",
    "LIFECYCLE_PAIRED_OFFLINE",
    "LIFECYCLE_REVOKED",
    "LIFECYCLE_UNPAIRED",
    "project_connector_status",
]
