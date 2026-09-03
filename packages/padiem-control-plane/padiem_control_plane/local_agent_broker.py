"""Server-trusted Local Agent broker authority contracts.

This module owns only Control Plane broker state: device credential verification,
bounded device sessions, monotonic command metadata, admission and acknowledgement.
It does not carry raw argv/file contents, execute local processes, approve P01 tools,
or perform network/database I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import hmac
import re
from typing import Any

from .contracts import ControlPlaneContractError

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_DEVICE_CREDENTIAL_BYTES = 16_384
MAX_SESSION_TTL_SECONDS = 3_600
MAX_COMMAND_TTL_SECONDS = 900
MAX_POLL_BATCH = 32


def _ref(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ControlPlaneContractError("invalid_local_agent_broker_ref", f"{name} must be a bounded safe reference")
    return value


def _digest(name: str, value: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ControlPlaneContractError("invalid_local_agent_broker_digest", f"{name} must be a lowercase SHA-256 digest")
    return value


def _aware(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ControlPlaneContractError("invalid_local_agent_broker_time", f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _credential(value: bytes) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > MAX_DEVICE_CREDENTIAL_BYTES:
        raise ControlPlaneContractError("invalid_device_credential", "device credential must be bounded non-empty bytes")
    return value


def _ttl(name: str, value: int, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ControlPlaneContractError("invalid_local_agent_broker_ttl", f"{name} must be between {minimum} and {maximum}")
    return value


class BrokerBindingState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class BrokerCommandState(str, Enum):
    QUEUED = "queued"
    ADMITTED = "admitted"
    ACKNOWLEDGED = "acknowledged"


@dataclass(frozen=True, slots=True)
class BrokerDeviceBinding:
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    credential_digest: str
    issued_at: datetime
    credential_expires_at: datetime
    state: BrokerBindingState = BrokerBindingState.ACTIVE

    def __post_init__(self) -> None:
        for name in ("binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        if isinstance(self.credential_generation, bool) or not isinstance(self.credential_generation, int) or self.credential_generation < 1:
            raise ControlPlaneContractError("invalid_device_binding", "credential_generation must be positive")
        object.__setattr__(self, "credential_digest", _digest("credential_digest", self.credential_digest))
        issued = _aware("issued_at", self.issued_at)
        expires = _aware("credential_expires_at", self.credential_expires_at)
        if expires <= issued:
            raise ControlPlaneContractError("invalid_device_binding", "credential expiry must follow issuance")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "credential_expires_at", expires)
        if not isinstance(self.state, BrokerBindingState):
            raise ControlPlaneContractError("invalid_device_binding", "state must be BrokerBindingState")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "issued_at": self.issued_at.isoformat(),
            "credential_expires_at": self.credential_expires_at.isoformat(),
            "state": self.state.value,
            "credential_digest_exposed": False,
            "raw_device_credential": False,
        }


@dataclass(frozen=True, slots=True)
class BrokerDeviceSession:
    session_id: str
    binding_ref: str
    device_id: str
    account_ref: str
    workspace_ref: str
    credential_generation: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("session_id", "binding_ref", "device_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        if isinstance(self.credential_generation, bool) or not isinstance(self.credential_generation, int) or self.credential_generation < 1:
            raise ControlPlaneContractError("invalid_device_session", "credential_generation must be positive")
        issued = _aware("issued_at", self.issued_at)
        expires = _aware("expires_at", self.expires_at)
        if expires <= issued or (expires - issued).total_seconds() > MAX_SESSION_TTL_SECONDS:
            raise ControlPlaneContractError("invalid_device_session", "device session lifetime must be positive and at most one hour")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "raw_session_secret": False,
        }


@dataclass(frozen=True, slots=True)
class BrokerCommandRecord:
    command_id: str
    run_id: str
    tool_request_ref: str
    binding_ref: str
    sequence: int
    request_fingerprint: str
    issued_at: datetime
    expires_at: datetime
    state: BrokerCommandState = BrokerCommandState.QUEUED
    admission_ref: str | None = None
    evidence_ref: str | None = None
    admitted_session_id: str | None = None
    admitted_at: datetime | None = None
    acknowledged_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("command_id", "run_id", "tool_request_ref", "binding_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ControlPlaneContractError("invalid_broker_command", "sequence must be positive")
        object.__setattr__(self, "request_fingerprint", _digest("request_fingerprint", self.request_fingerprint))
        issued = _aware("issued_at", self.issued_at)
        expires = _aware("expires_at", self.expires_at)
        if expires <= issued or (expires - issued).total_seconds() > MAX_COMMAND_TTL_SECONDS:
            raise ControlPlaneContractError("invalid_broker_command", "command lifetime must be positive and at most 900 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)
        if not isinstance(self.state, BrokerCommandState):
            raise ControlPlaneContractError("invalid_broker_command", "state must be BrokerCommandState")
        for name in ("admission_ref", "evidence_ref", "admitted_session_id"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _ref(name, value))
        if self.admitted_at is not None:
            object.__setattr__(self, "admitted_at", _aware("admitted_at", self.admitted_at))
        if self.acknowledged_at is not None:
            object.__setattr__(self, "acknowledged_at", _aware("acknowledged_at", self.acknowledged_at))
        if self.state is BrokerCommandState.QUEUED and any(
            value is not None for value in (self.admission_ref, self.evidence_ref, self.admitted_session_id, self.admitted_at, self.acknowledged_at)
        ):
            raise ControlPlaneContractError("invalid_broker_command", "queued command cannot contain admission state")
        if self.state is not BrokerCommandState.QUEUED and any(
            value is None for value in (self.admission_ref, self.evidence_ref, self.admitted_session_id, self.admitted_at)
        ):
            raise ControlPlaneContractError("invalid_broker_command", "admitted command requires complete admission correlation")
        if self.state is BrokerCommandState.ACKNOWLEDGED and self.acknowledged_at is None:
            raise ControlPlaneContractError("invalid_broker_command", "acknowledged command requires acknowledged_at")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "binding_ref": self.binding_ref,
            "sequence": self.sequence,
            "request_fingerprint": self.request_fingerprint,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "state": self.state.value,
            "admission_ref": self.admission_ref,
            "evidence_ref": self.evidence_ref,
            "admitted_session_id": self.admitted_session_id,
            "admitted_at": self.admitted_at.isoformat() if self.admitted_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "raw_argv": False,
            "raw_file_content": False,
            "raw_device_credential": False,
            "p01_approval_payload": False,
        }


@dataclass(frozen=True, slots=True)
class BrokerCommandAdmission:
    admission_ref: str
    authority_ref: str
    command_id: str
    session_id: str
    binding_ref: str
    run_id: str
    tool_request_ref: str
    sequence: int
    request_fingerprint: str
    evidence_ref: str
    accepted_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for name in ("admission_ref", "authority_ref", "command_id", "session_id", "binding_ref", "run_id", "tool_request_ref", "evidence_ref"):
            object.__setattr__(self, name, _ref(name, getattr(self, name)))
        object.__setattr__(self, "request_fingerprint", _digest("request_fingerprint", self.request_fingerprint))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ControlPlaneContractError("invalid_command_admission", "sequence must be positive")
        accepted = _aware("accepted_at", self.accepted_at)
        expires = _aware("expires_at", self.expires_at)
        if expires <= accepted:
            raise ControlPlaneContractError("invalid_command_admission", "admission expiry must follow acceptance")
        object.__setattr__(self, "accepted_at", accepted)
        object.__setattr__(self, "expires_at", expires)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "admission_ref": self.admission_ref,
            "authority_ref": self.authority_ref,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "binding_ref": self.binding_ref,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "sequence": self.sequence,
            "request_fingerprint": self.request_fingerprint,
            "evidence_ref": self.evidence_ref,
            "accepted_at": self.accepted_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "raw_argv": False,
            "raw_device_credential": False,
        }


class InMemoryLocalAgentBrokerAuthority:
    """Deterministic server-side authority core; persistence/transport are injected later."""

    def __init__(self, *, pepper: bytes, authority_ref: str) -> None:
        if not isinstance(pepper, bytes) or len(pepper) < 16:
            raise ValueError("Local Agent broker pepper must contain at least 16 bytes")
        self._pepper = pepper
        self.authority_ref = _ref("authority_ref", authority_ref)
        self._bindings: dict[str, BrokerDeviceBinding] = {}
        self._sessions: dict[str, BrokerDeviceSession] = {}
        self._commands: dict[str, BrokerCommandRecord] = {}
        self._last_sequence_by_binding: dict[str, int] = {}

    def _credential_digest(self, credential: bytes) -> str:
        return hmac.new(self._pepper, _credential(credential), hashlib.sha256).hexdigest()

    def register_binding(
        self,
        *,
        binding_ref: str,
        device_id: str,
        account_ref: str,
        workspace_ref: str,
        credential: bytes,
        now: datetime,
        credential_ttl_seconds: int = 2_592_000,
    ) -> BrokerDeviceBinding:
        binding_ref = _ref("binding_ref", binding_ref)
        now = _aware("now", now)
        ttl = _ttl("credential_ttl_seconds", credential_ttl_seconds, minimum=300, maximum=2_592_000)
        if binding_ref in self._bindings:
            raise ControlPlaneContractError("duplicate_device_binding", "device binding already exists")
        if any(item.device_id == device_id and item.state is BrokerBindingState.ACTIVE for item in self._bindings.values()):
            raise ControlPlaneContractError("duplicate_device_binding", "device already has an active binding")
        binding = BrokerDeviceBinding(
            binding_ref=binding_ref,
            device_id=device_id,
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            credential_generation=1,
            credential_digest=self._credential_digest(credential),
            issued_at=now,
            credential_expires_at=now + timedelta(seconds=ttl),
        )
        self._bindings[binding_ref] = binding
        return binding

    def _binding(self, binding_ref: str, *, now: datetime) -> BrokerDeviceBinding:
        binding_ref = _ref("binding_ref", binding_ref)
        now = _aware("now", now)
        try:
            binding = self._bindings[binding_ref]
        except KeyError as exc:
            raise ControlPlaneContractError("device_binding_not_found", "device binding was not found") from exc
        if binding.state is BrokerBindingState.REVOKED:
            raise ControlPlaneContractError("device_binding_revoked", "device binding is revoked")
        if now >= binding.credential_expires_at:
            raise ControlPlaneContractError("device_credential_expired", "device credential is expired")
        return binding

    def _authenticate(self, binding_ref: str, credential: bytes, *, now: datetime) -> BrokerDeviceBinding:
        binding = self._binding(binding_ref, now=now)
        candidate = self._credential_digest(credential)
        if not hmac.compare_digest(candidate, binding.credential_digest):
            raise ControlPlaneContractError("invalid_device_credential", "device credential is invalid")
        return binding

    def rotate_credential(
        self,
        binding_ref: str,
        *,
        expected_generation: int,
        new_credential: bytes,
        now: datetime,
        credential_ttl_seconds: int = 2_592_000,
    ) -> BrokerDeviceBinding:
        binding = self._binding(binding_ref, now=now)
        if expected_generation != binding.credential_generation:
            raise ControlPlaneContractError("stale_device_credential_generation", "credential generation is stale")
        now = _aware("now", now)
        ttl = _ttl("credential_ttl_seconds", credential_ttl_seconds, minimum=300, maximum=2_592_000)
        rotated = BrokerDeviceBinding(
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation + 1,
            credential_digest=self._credential_digest(new_credential),
            issued_at=now,
            credential_expires_at=now + timedelta(seconds=ttl),
        )
        self._bindings[binding.binding_ref] = rotated
        self._sessions = {key: value for key, value in self._sessions.items() if value.binding_ref != binding.binding_ref}
        return rotated

    def revoke_binding(self, binding_ref: str, *, now: datetime) -> BrokerDeviceBinding:
        binding = self._binding(binding_ref, now=now)
        revoked = replace(binding, state=BrokerBindingState.REVOKED)
        self._bindings[binding.binding_ref] = revoked
        self._sessions = {key: value for key, value in self._sessions.items() if value.binding_ref != binding.binding_ref}
        return revoked

    def open_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> BrokerDeviceSession:
        now = _aware("now", now)
        binding = self._authenticate(binding_ref, credential, now=now)
        if binding.account_ref != _ref("account_ref", account_ref) or binding.workspace_ref != _ref("workspace_ref", workspace_ref):
            raise ControlPlaneContractError("device_binding_scope_mismatch", "device account/workspace binding does not match")
        session_id = _ref("session_id", session_id)
        if session_id in self._sessions:
            raise ControlPlaneContractError("duplicate_device_session", "device session already exists")
        ttl = _ttl("ttl_seconds", ttl_seconds, minimum=60, maximum=MAX_SESSION_TTL_SECONDS)
        expires = min(now + timedelta(seconds=ttl), binding.credential_expires_at)
        session = BrokerDeviceSession(
            session_id=session_id,
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_generation=binding.credential_generation,
            issued_at=now,
            expires_at=expires,
        )
        self._sessions[session_id] = session
        return session

    def _session(self, session_id: str, *, binding: BrokerDeviceBinding, now: datetime) -> BrokerDeviceSession:
        session_id = _ref("session_id", session_id)
        now = _aware("now", now)
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise ControlPlaneContractError("device_session_not_found", "device session was not found") from exc
        if now < session.issued_at or now >= session.expires_at:
            raise ControlPlaneContractError("device_session_expired", "device session is not current")
        expected = (binding.binding_ref, binding.device_id, binding.account_ref, binding.workspace_ref, binding.credential_generation)
        actual = (session.binding_ref, session.device_id, session.account_ref, session.workspace_ref, session.credential_generation)
        if actual != expected:
            raise ControlPlaneContractError("device_session_scope_mismatch", "device session does not match current binding")
        return session

    def enqueue_command(
        self,
        *,
        command_id: str,
        binding_ref: str,
        run_id: str,
        tool_request_ref: str,
        request_fingerprint: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> BrokerCommandRecord:
        now = _aware("now", now)
        binding = self._binding(binding_ref, now=now)
        command_id = _ref("command_id", command_id)
        if command_id in self._commands:
            raise ControlPlaneContractError("duplicate_broker_command", "command_id has already been used")
        ttl = _ttl("ttl_seconds", ttl_seconds, minimum=1, maximum=MAX_COMMAND_TTL_SECONDS)
        sequence = self._last_sequence_by_binding.get(binding.binding_ref, 0) + 1
        command = BrokerCommandRecord(
            command_id=command_id,
            run_id=run_id,
            tool_request_ref=tool_request_ref,
            binding_ref=binding.binding_ref,
            sequence=sequence,
            request_fingerprint=request_fingerprint,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl),
        )
        self._commands[command_id] = command
        self._last_sequence_by_binding[binding.binding_ref] = sequence
        return command

    def poll(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        after_sequence: int,
        now: datetime,
        limit: int = MAX_POLL_BATCH,
    ) -> tuple[BrokerCommandRecord, ...]:
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ControlPlaneContractError("invalid_poll_cursor", "after_sequence must be a non-negative integer")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_POLL_BATCH:
            raise ControlPlaneContractError("invalid_poll_limit", "poll limit must be between 1 and 32")
        now = _aware("now", now)
        binding = self._authenticate(binding_ref, credential, now=now)
        self._session(session_id, binding=binding, now=now)
        items = [
            item for item in self._commands.values()
            if item.binding_ref == binding.binding_ref
            and item.state is BrokerCommandState.QUEUED
            and item.sequence > after_sequence
            and item.issued_at <= now < item.expires_at
        ]
        items.sort(key=lambda item: item.sequence)
        return tuple(items[:limit])

    def admit_command(
        self,
        *,
        admission_ref: str,
        evidence_ref: str,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        request_fingerprint: str,
        now: datetime,
    ) -> BrokerCommandAdmission:
        now = _aware("now", now)
        binding = self._authenticate(binding_ref, credential, now=now)
        session = self._session(session_id, binding=binding, now=now)
        command_id = _ref("command_id", command_id)
        try:
            command = self._commands[command_id]
        except KeyError as exc:
            raise ControlPlaneContractError("broker_command_not_found", "command was not found") from exc
        if command.binding_ref != binding.binding_ref:
            raise ControlPlaneContractError("broker_command_scope_mismatch", "command does not belong to this device binding")
        if command.state is not BrokerCommandState.QUEUED:
            raise ControlPlaneContractError("broker_command_replay", "command has already been admitted or acknowledged")
        if now < command.issued_at or now >= command.expires_at:
            raise ControlPlaneContractError("broker_command_expired", "command is not currently valid")
        fingerprint = _digest("request_fingerprint", request_fingerprint)
        if fingerprint != command.request_fingerprint:
            raise ControlPlaneContractError("broker_command_fingerprint_mismatch", "materialized request fingerprint does not match queued command")
        admission_ref = _ref("admission_ref", admission_ref)
        evidence_ref = _ref("evidence_ref", evidence_ref)
        if any(item.admission_ref == admission_ref for item in self._commands.values() if item.admission_ref is not None):
            raise ControlPlaneContractError("duplicate_command_admission", "admission_ref has already been used")
        if any(item.evidence_ref == evidence_ref for item in self._commands.values() if item.evidence_ref is not None):
            raise ControlPlaneContractError("duplicate_command_evidence", "evidence_ref has already been used")
        admitted = replace(
            command,
            state=BrokerCommandState.ADMITTED,
            admission_ref=admission_ref,
            evidence_ref=evidence_ref,
            admitted_session_id=session.session_id,
            admitted_at=now,
        )
        self._commands[command.command_id] = admitted
        return BrokerCommandAdmission(
            admission_ref=admission_ref,
            authority_ref=self.authority_ref,
            command_id=command.command_id,
            session_id=session.session_id,
            binding_ref=command.binding_ref,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            sequence=command.sequence,
            request_fingerprint=command.request_fingerprint,
            evidence_ref=evidence_ref,
            accepted_at=now,
            expires_at=command.expires_at,
        )

    def acknowledge(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        now: datetime,
    ) -> BrokerCommandRecord:
        now = _aware("now", now)
        binding = self._authenticate(binding_ref, credential, now=now)
        session = self._session(session_id, binding=binding, now=now)
        command_id = _ref("command_id", command_id)
        try:
            command = self._commands[command_id]
        except KeyError as exc:
            raise ControlPlaneContractError("broker_command_not_found", "command was not found") from exc
        if command.state is not BrokerCommandState.ADMITTED:
            raise ControlPlaneContractError("broker_ack_without_admission", "command must be admitted exactly once before acknowledgement")
        expected = (
            binding.binding_ref,
            session.session_id,
            _ref("admission_ref", admission_ref),
            _ref("evidence_ref", evidence_ref),
        )
        actual = (command.binding_ref, command.admitted_session_id, command.admission_ref, command.evidence_ref)
        if actual != expected:
            raise ControlPlaneContractError("broker_ack_correlation_mismatch", "acknowledgement does not match admitted command evidence")
        if now >= command.expires_at:
            raise ControlPlaneContractError("broker_command_expired", "expired command cannot be acknowledged")
        acknowledged = replace(command, state=BrokerCommandState.ACKNOWLEDGED, acknowledged_at=now)
        self._commands[command.command_id] = acknowledged
        return acknowledged


SERVER_SIDE_LOCAL_AGENT_BROKER_AUTHORITY = True
KEYED_DEVICE_CREDENTIAL_DIGEST_ONLY = True
BOUND_BROKER_SESSION = True
MONOTONIC_COMMAND_SEQUENCE = True
EXACT_REQUEST_FINGERPRINT = True
ADMISSION_BEFORE_ACK = True
RAW_ARGV_IN_BROKER_COMMAND = False
RAW_DEVICE_CREDENTIAL_PERSISTED = False
P01_AUTHORITY_DUPLICATED = False
PUBLIC_HTTP_ENDPOINT = False
PRODUCTION_DEPLOYMENT = False
PRODUCTION_READY = False
