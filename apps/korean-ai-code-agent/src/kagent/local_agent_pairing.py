from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Protocol

from .contracts import ContractError


_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value.strip()):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value.strip()


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _positive_ttl(value: int, *, field_name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ContractError(f"{field_name} must be between {minimum} and {maximum}")
    return value


class DeviceLifecycle(str, Enum):
    UNPAIRED = "unpaired"
    PAIRED_OFFLINE = "paired_offline"
    ONLINE = "online"
    REVOKED = "revoked"
    CREDENTIAL_EXPIRED = "credential_expired"
    UPDATE_REQUIRED = "update_required"


@dataclass(frozen=True, slots=True)
class PairingChallenge:
    challenge_id: str
    account_ref: str
    workspace_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("challenge_id", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 600:
            raise ContractError("pairing challenge lifetime must be positive and at most 600 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "single_use": True,
            "raw_pairing_secret": False,
        }


@dataclass(frozen=True, slots=True)
class DeviceBinding:
    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    credential_ref: str
    credential_generation: int
    issued_at: datetime
    credential_expires_at: datetime
    state: DeviceLifecycle = DeviceLifecycle.PAIRED_OFFLINE

    def __post_init__(self) -> None:
        for field_name in ("device_id", "binding_ref", "account_ref", "workspace_ref", "credential_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if (
            isinstance(self.credential_generation, bool)
            or not isinstance(self.credential_generation, int)
            or self.credential_generation < 1
        ):
            raise ContractError("credential_generation must be a positive integer")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.credential_expires_at, "credential_expires_at")
        if expires <= issued:
            raise ContractError("credential_expires_at must be after issued_at")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "credential_expires_at", expires)
        if not isinstance(self.state, DeviceLifecycle):
            try:
                object.__setattr__(self, "state", DeviceLifecycle(self.state))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid device lifecycle state") from exc

    def safe_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "credential_generation": self.credential_generation,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "credential_expires_at": self.credential_expires_at.isoformat().replace("+00:00", "Z"),
            "state": self.state.value,
            "credential_ref_exposed": False,
            "raw_device_secret": False,
        }


@dataclass(frozen=True, slots=True)
class DeviceSession:
    session_id: str
    device_id: str
    binding_ref: str
    account_ref: str
    workspace_ref: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("session_id", "device_id", "binding_ref", "account_ref", "workspace_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 3600:
            raise ContractError("device session lifetime must be positive and at most 3600 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_id": self.device_id,
            "binding_ref": self.binding_ref,
            "account_ref": self.account_ref,
            "workspace_ref": self.workspace_ref,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "outbound_only": True,
            "transport_secret": False,
        }


@dataclass(frozen=True, slots=True)
class DeviceCommandEnvelope:
    command_id: str
    run_id: str
    tool_request_ref: str
    binding_ref: str
    sequence: int
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("command_id", "run_id", "tool_request_ref", "binding_ref"):
            object.__setattr__(self, field_name, _ref(getattr(self, field_name), field_name))
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence < 1:
            raise ContractError("sequence must be a positive integer")
        issued = _aware(self.issued_at, "issued_at")
        expires = _aware(self.expires_at, "expires_at")
        if expires <= issued or (expires - issued).total_seconds() > 900:
            raise ContractError("command envelope lifetime must be positive and at most 900 seconds")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "run_id": self.run_id,
            "tool_request_ref": self.tool_request_ref,
            "binding_ref": self.binding_ref,
            "sequence": self.sequence,
            "issued_at": self.issued_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "raw_tool_args": False,
            "client_authority": False,
        }


class LocalAgentPairingPort(Protocol):
    def issue_pairing(
        self,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> PairingChallenge:
        ...

    def pair_device(
        self,
        *,
        challenge_id: str,
        proof_ref: str,
        device_id: str,
        now: datetime,
    ) -> DeviceBinding:
        ...

    def rotate_credential(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        ...

    def revoke(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        ...

    def connect(
        self,
        binding_ref: str,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> DeviceSession:
        ...

    def accept_command(self, session_id: str, command: DeviceCommandEnvelope, *, now: datetime) -> None:
        ...


class UnconfiguredLocalAgentPairingPort:
    def issue_pairing(self, **kwargs: Any) -> PairingChallenge:
        raise ContractError("Local Agent pairing authority is not configured")

    def pair_device(self, **kwargs: Any) -> DeviceBinding:
        raise ContractError("Local Agent pairing authority is not configured")

    def rotate_credential(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        raise ContractError("Local Agent pairing authority is not configured")

    def revoke(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        raise ContractError("Local Agent pairing authority is not configured")

    def connect(self, binding_ref: str, **kwargs: Any) -> DeviceSession:
        raise ContractError("Local Agent pairing authority is not configured")

    def accept_command(self, session_id: str, command: DeviceCommandEnvelope, *, now: datetime) -> None:
        raise ContractError("Local Agent pairing authority is not configured")


def deterministic_fake_pairing_proof(challenge_id: str) -> str:
    challenge_id = _ref(challenge_id, "challenge_id")
    digest = hashlib.sha256(f"fake-pairing-proof:{challenge_id}".encode("utf-8")).hexdigest()[:24]
    return f"proof:{digest}"


class DeterministicFakeLocalAgentPairingPort:
    def __init__(self) -> None:
        self._counter = 0
        self._challenges: dict[str, PairingChallenge] = {}
        self._used_challenges: set[str] = set()
        self._bindings: dict[str, DeviceBinding] = {}
        self._sessions: dict[str, DeviceSession] = {}
        self._accepted_command_ids: set[str] = set()
        self._last_sequence_by_binding: dict[str, int] = {}

    def issue_pairing(
        self,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 300,
    ) -> PairingChallenge:
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = _ref(workspace_ref, "workspace_ref")
        now = _aware(now, "now")
        ttl_seconds = _positive_ttl(ttl_seconds, field_name="ttl_seconds", minimum=30, maximum=600)
        self._counter += 1
        digest = hashlib.sha256(
            f"{account_ref}:{workspace_ref}:{now.isoformat()}:{self._counter}".encode("utf-8")
        ).hexdigest()[:24]
        challenge = PairingChallenge(
            challenge_id=f"pair:{digest}",
            account_ref=account_ref,
            workspace_ref=workspace_ref,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._challenges[challenge.challenge_id] = challenge
        return challenge

    def pair_device(
        self,
        *,
        challenge_id: str,
        proof_ref: str,
        device_id: str,
        now: datetime,
    ) -> DeviceBinding:
        challenge_id = _ref(challenge_id, "challenge_id")
        proof_ref = _ref(proof_ref, "proof_ref")
        device_id = _ref(device_id, "device_id")
        now = _aware(now, "now")
        try:
            challenge = self._challenges[challenge_id]
        except KeyError as exc:
            raise ContractError("pairing challenge not found") from exc
        if challenge_id in self._used_challenges:
            raise ContractError("pairing challenge is single-use")
        if now >= challenge.expires_at:
            raise ContractError("pairing challenge expired")
        if proof_ref != deterministic_fake_pairing_proof(challenge_id):
            raise ContractError("pairing proof is invalid")
        if any(binding.device_id == device_id and binding.state is not DeviceLifecycle.REVOKED for binding in self._bindings.values()):
            raise ContractError("device already has an active binding")
        digest = hashlib.sha256(f"{challenge_id}:{device_id}".encode("utf-8")).hexdigest()[:24]
        binding_ref = f"device-binding:{digest}"
        credential_ref = f"device-credential:{digest}:1"
        binding = DeviceBinding(
            device_id=device_id,
            binding_ref=binding_ref,
            account_ref=challenge.account_ref,
            workspace_ref=challenge.workspace_ref,
            credential_ref=credential_ref,
            credential_generation=1,
            issued_at=now,
            credential_expires_at=now + timedelta(days=30),
        )
        self._bindings[binding_ref] = binding
        self._used_challenges.add(challenge_id)
        return binding

    def rotate_credential(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        binding = self._active_binding(binding_ref, now=now)
        generation = binding.credential_generation + 1
        digest = hashlib.sha256(
            f"{binding.binding_ref}:{generation}:{_aware(now, 'now').isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        rotated = DeviceBinding(
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_ref=f"device-credential:{digest}:{generation}",
            credential_generation=generation,
            issued_at=_aware(now, "now"),
            credential_expires_at=_aware(now, "now") + timedelta(days=30),
            state=DeviceLifecycle.PAIRED_OFFLINE,
        )
        self._bindings[binding.binding_ref] = rotated
        self._drop_sessions_for_binding(binding.binding_ref)
        return rotated

    def revoke(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        binding_ref = _ref(binding_ref, "binding_ref")
        now = _aware(now, "now")
        try:
            binding = self._bindings[binding_ref]
        except KeyError as exc:
            raise ContractError("device binding not found") from exc
        if binding.state is DeviceLifecycle.REVOKED:
            raise ContractError("device binding is already revoked")
        revoked = DeviceBinding(
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_ref=binding.credential_ref,
            credential_generation=binding.credential_generation,
            issued_at=binding.issued_at,
            credential_expires_at=binding.credential_expires_at,
            state=DeviceLifecycle.REVOKED,
        )
        self._bindings[binding_ref] = revoked
        self._drop_sessions_for_binding(binding_ref)
        return revoked

    def connect(
        self,
        binding_ref: str,
        *,
        account_ref: str,
        workspace_ref: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> DeviceSession:
        binding = self._active_binding(binding_ref, now=now)
        account_ref = _ref(account_ref, "account_ref")
        workspace_ref = _ref(workspace_ref, "workspace_ref")
        now = _aware(now, "now")
        ttl_seconds = _positive_ttl(ttl_seconds, field_name="ttl_seconds", minimum=60, maximum=3600)
        if binding.account_ref != account_ref or binding.workspace_ref != workspace_ref:
            raise ContractError("device account/workspace binding mismatch")
        digest = hashlib.sha256(
            f"{binding.binding_ref}:{binding.credential_generation}:{now.isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        session = DeviceSession(
            session_id=f"device-session:{digest}",
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            issued_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        self._sessions[session.session_id] = session
        self._bindings[binding.binding_ref] = DeviceBinding(
            device_id=binding.device_id,
            binding_ref=binding.binding_ref,
            account_ref=binding.account_ref,
            workspace_ref=binding.workspace_ref,
            credential_ref=binding.credential_ref,
            credential_generation=binding.credential_generation,
            issued_at=binding.issued_at,
            credential_expires_at=binding.credential_expires_at,
            state=DeviceLifecycle.ONLINE,
        )
        return session

    def accept_command(self, session_id: str, command: DeviceCommandEnvelope, *, now: datetime) -> None:
        session_id = _ref(session_id, "session_id")
        if not isinstance(command, DeviceCommandEnvelope):
            raise ContractError("command must be DeviceCommandEnvelope")
        now = _aware(now, "now")
        try:
            session = self._sessions[session_id]
        except KeyError as exc:
            raise ContractError("device session not found") from exc
        if now >= session.expires_at:
            raise ContractError("device session expired")
        binding = self._active_binding(session.binding_ref, now=now)
        if binding.state is not DeviceLifecycle.ONLINE:
            raise ContractError("device is not online")
        if command.binding_ref != binding.binding_ref:
            raise ContractError("command binding mismatch")
        if now < command.issued_at or now >= command.expires_at:
            raise ContractError("command is not currently valid")
        if command.command_id in self._accepted_command_ids:
            raise ContractError("command replay rejected")
        last_sequence = self._last_sequence_by_binding.get(binding.binding_ref, 0)
        if command.sequence <= last_sequence:
            raise ContractError("command sequence must increase monotonically")
        self._accepted_command_ids.add(command.command_id)
        self._last_sequence_by_binding[binding.binding_ref] = command.sequence

    def _active_binding(self, binding_ref: str, *, now: datetime) -> DeviceBinding:
        binding_ref = _ref(binding_ref, "binding_ref")
        now = _aware(now, "now")
        try:
            binding = self._bindings[binding_ref]
        except KeyError as exc:
            raise ContractError("device binding not found") from exc
        if binding.state is DeviceLifecycle.REVOKED:
            raise ContractError("device binding revoked")
        if now >= binding.credential_expires_at:
            expired = DeviceBinding(
                device_id=binding.device_id,
                binding_ref=binding.binding_ref,
                account_ref=binding.account_ref,
                workspace_ref=binding.workspace_ref,
                credential_ref=binding.credential_ref,
                credential_generation=binding.credential_generation,
                issued_at=binding.issued_at,
                credential_expires_at=binding.credential_expires_at,
                state=DeviceLifecycle.CREDENTIAL_EXPIRED,
            )
            self._bindings[binding_ref] = expired
            self._drop_sessions_for_binding(binding_ref)
            raise ContractError("device credential expired")
        if binding.state is DeviceLifecycle.CREDENTIAL_EXPIRED:
            raise ContractError("device credential expired")
        return binding

    def _drop_sessions_for_binding(self, binding_ref: str) -> None:
        self._sessions = {
            session_id: session
            for session_id, session in self._sessions.items()
            if session.binding_ref != binding_ref
        }


OUTBOUND_ONLY_TRANSPORT = True
PUBLIC_INBOUND_PORT_REQUIRED = False
UPNP_PORT_FORWARD_SUPPORTED = False
PAIRING_SINGLE_USE = True
PAIRING_REPLAY_ALLOWED = False
RAW_DEVICE_SECRET_IN_LOG = False
REAL_PAIRING_BROKER_CONFIGURED = False
FAKE_COUNTS_AS_LIVE = False
