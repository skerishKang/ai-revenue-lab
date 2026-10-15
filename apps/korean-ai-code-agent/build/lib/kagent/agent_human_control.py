from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from typing import Any, Callable

from .contracts import ContractError
from .security import redact_secrets

HELP_REQUEST_TTL_SECONDS = 600
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,511}$")


def _ref(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    normalized = value.strip()
    if not _SAFE_REF_RE.fullmatch(normalized):
        raise ContractError(f"{field_name} must be a bounded safe reference")
    if redact_secrets(normalized) != normalized:
        raise ContractError(f"{field_name} must not contain credential material")
    return normalized


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _reason(value: str | None) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        return "The agent needs a person to continue."
    normalized = redact_secrets(value.strip())
    if len(normalized) > 1_000:
        raise ContractError("help reason exceeds 1000 characters")
    return normalized


class ControlHolder(str, Enum):
    AGENT = "agent"
    HUMAN = "human"


@dataclass(frozen=True, slots=True)
class PendingSecretRequest:
    label: str
    field_ref: str
    snapshot_ref: str | None = None

    def __post_init__(self) -> None:
        label = redact_secrets(self.label.strip()) if isinstance(self.label, str) else ""
        if not label:
            label = "the value this page is asking for"
        if len(label) > 160:
            raise ContractError("secret label exceeds 160 characters")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "field_ref", _ref(self.field_ref, "field_ref"))
        if self.snapshot_ref is not None:
            object.__setattr__(self, "snapshot_ref", _ref(self.snapshot_ref, "snapshot_ref"))

    def safe_dict(self) -> dict[str, str | bool | None]:
        return {
            "label": self.label,
            "field_ref": self.field_ref,
            "snapshot_ref": self.snapshot_ref,
            "secret_value_present": False,
        }


@dataclass(frozen=True, slots=True)
class AgentHumanControlState:
    computer_id: str
    holder: ControlHolder
    since: datetime
    help_requested: bool
    reason: str | None = None
    requested_at: datetime | None = None
    control_session_ref: str | None = None
    pending_secret: PendingSecretRequest | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "computer_id", _ref(self.computer_id, "computer_id"))
        if not isinstance(self.holder, ControlHolder):
            try:
                object.__setattr__(self, "holder", ControlHolder(self.holder))
            except (TypeError, ValueError) as exc:
                raise ContractError("invalid control holder") from exc
        object.__setattr__(self, "since", _aware(self.since, "since"))
        if not isinstance(self.help_requested, bool):
            raise ContractError("help_requested must be boolean")
        if self.reason is not None:
            object.__setattr__(self, "reason", _reason(self.reason))
        if self.requested_at is not None:
            object.__setattr__(self, "requested_at", _aware(self.requested_at, "requested_at"))
        if self.control_session_ref is not None:
            object.__setattr__(
                self,
                "control_session_ref",
                _ref(self.control_session_ref, "control_session_ref"),
            )
        if self.pending_secret is not None and not isinstance(self.pending_secret, PendingSecretRequest):
            raise ContractError("pending_secret must be PendingSecretRequest")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-agent-human-control.v1",
            "computer_id": self.computer_id,
            "holder": self.holder.value,
            "since": self.since.isoformat().replace("+00:00", "Z"),
            "help_requested": self.help_requested,
            "reason": self.reason,
            "requested_at": (
                self.requested_at.isoformat().replace("+00:00", "Z")
                if self.requested_at is not None
                else None
            ),
            "control_session_ref": self.control_session_ref,
            "pending_secret": (
                self.pending_secret.safe_dict() if self.pending_secret is not None else None
            ),
            "raw_secret_value": False,
            "queued_agent_actions": False,
        }


class AgentHumanControl:
    """OpenBot-derived takeover state machine, strengthened for Padiem.

    The trusted server/P01 layer authorizes who may take control. This physical
    state machine requires an opaque authorization/session ref and never sees
    the credential or secret value itself.
    """

    def __init__(self, computer_id: str, now: Callable[[], datetime] | None = None) -> None:
        self._computer_id = _ref(computer_id, "computer_id")
        self._now = now or (lambda: datetime.now(timezone.utc))
        current = _aware(self._now(), "now")
        self._state = AgentHumanControlState(
            computer_id=self._computer_id,
            holder=ControlHolder.AGENT,
            since=current,
            help_requested=False,
        )

    def _current_time(self) -> datetime:
        return _aware(self._now(), "now")

    def get(self) -> AgentHumanControlState:
        now = self._current_time()
        state = self._state
        if (
            state.help_requested
            and state.holder is ControlHolder.AGENT
            and state.requested_at is not None
            and now - state.requested_at > timedelta(seconds=HELP_REQUEST_TTL_SECONDS)
        ):
            self._state = AgentHumanControlState(
                computer_id=state.computer_id,
                holder=ControlHolder.AGENT,
                since=state.since,
                help_requested=False,
                pending_secret=state.pending_secret,
            )
        return self._state

    def request_help(self, reason: str | None = None) -> AgentHumanControlState:
        state = self.get()
        if state.holder is ControlHolder.HUMAN:
            raise ContractError("human already has control")
        now = self._current_time()
        self._state = AgentHumanControlState(
            computer_id=state.computer_id,
            holder=ControlHolder.AGENT,
            since=state.since,
            help_requested=True,
            reason=_reason(reason),
            requested_at=now,
            pending_secret=state.pending_secret,
        )
        return self._state

    def request_secret(
        self,
        *,
        label: str | None,
        field_ref: str,
        snapshot_ref: str | None = None,
    ) -> AgentHumanControlState:
        state = self.get()
        if state.holder is ControlHolder.HUMAN:
            raise ContractError("scoped secret entry is unavailable while human has full control")
        pending = PendingSecretRequest(
            label=label or "the value this page is asking for",
            field_ref=field_ref,
            snapshot_ref=snapshot_ref,
        )
        self._state = AgentHumanControlState(
            computer_id=state.computer_id,
            holder=state.holder,
            since=state.since,
            help_requested=state.help_requested,
            reason=state.reason,
            requested_at=state.requested_at,
            pending_secret=pending,
        )
        return self._state

    def pending_secret(self) -> PendingSecretRequest | None:
        return self.get().pending_secret

    def mark_secret_supplied(self) -> AgentHumanControlState:
        state = self.get()
        if state.pending_secret is None:
            raise ContractError("nothing is waiting for a secret")
        self._state = AgentHumanControlState(
            computer_id=state.computer_id,
            holder=state.holder,
            since=state.since,
            help_requested=state.help_requested,
            reason=state.reason,
            requested_at=state.requested_at,
        )
        return self._state

    def take(self, *, control_session_ref: str) -> AgentHumanControlState:
        state = self.get()
        if state.holder is ControlHolder.HUMAN:
            raise ContractError("human already has control")
        session_ref = _ref(control_session_ref, "control_session_ref")
        now = self._current_time()
        self._state = AgentHumanControlState(
            computer_id=state.computer_id,
            holder=ControlHolder.HUMAN,
            since=now,
            help_requested=False,
            reason=state.reason,
            control_session_ref=session_ref,
        )
        return self._state

    def release(self, *, control_session_ref: str) -> AgentHumanControlState:
        state = self.get()
        if state.holder is not ControlHolder.HUMAN:
            raise ContractError("human does not hold control")
        session_ref = _ref(control_session_ref, "control_session_ref")
        if session_ref != state.control_session_ref:
            raise ContractError("control session does not match current human control")
        now = self._current_time()
        self._state = AgentHumanControlState(
            computer_id=state.computer_id,
            holder=ControlHolder.AGENT,
            since=now,
            help_requested=False,
        )
        return self._state

    def assert_agent_may_act(self) -> None:
        if self.get().holder is ControlHolder.HUMAN:
            raise ContractError(
                "a person has control of the computer; agent actions are refused until control is released"
            )

    def human_may_drive(self, *, control_session_ref: str) -> bool:
        state = self.get()
        if state.holder is not ControlHolder.HUMAN:
            return False
        return _ref(control_session_ref, "control_session_ref") == state.control_session_ref


HUMAN_CONTROL_SUPPORTED = True
RAW_SECRET_ENTRY_STORED = False
AGENT_ACTIONS_QUEUE_DURING_HUMAN_CONTROL = False
