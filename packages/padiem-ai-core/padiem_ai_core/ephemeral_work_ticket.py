"""#3330: product-neutral, non-authorizing ephemeral execution work-ticket envelope.

A ticket is a *bounded metadata plan*, never a Drive OAuth grant, P01 approval,
Broker command admission or permission to dispatch. Only an already-authorized
host may choose a backend and exercise the existing Drive READ/WRITE and
idempotent execution authorities. There is no provider/client implementation,
per-account persistent filesystem, bearer token or user-document byte field.

Existing canonical DriveIndexSourceSnapshot remains the source version/freshness
contract; this module does not create a second Drive credential/file authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

from .drive_index_freshness import DriveIndexSourceSnapshot

MAX_WORK_TICKET_INPUTS = 16
MAX_WORK_TICKET_TTL_SECONDS = 3_600  # Existing Cloud M1 lease upper bound.
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DRIVE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CAPABILITY = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
MODES = frozenset({"inspect", "produce_artifact"})


class WorkTicketContractError(ValueError):
    """No caller/provider secret or raw file text is included in failures."""


def _ref(value: object, field: str, *, drive: bool = False) -> str:
    pattern = _DRIVE_ID if drive else _REF
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise WorkTicketContractError(f"{field} requires a bounded opaque reference")
    return value


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkTicketContractError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class EphemeralExecutionWorkTicket:
    """Server-composed file references and time scope, with *zero* dispatch power.

    'inputs' reference Drive file versions and are *not* pre-authorized reads.
    Every backend must obtain the existing Control Plane connector/Drive proof
    at the time of operation, independently of a ticket's local validation.
    'output_folder_ref' names a candidate destination, *not* WRITE consent;
    the host's canonical approval/receipt and Drive authorization remain required.

    The task's actual backend is intentionally absent: existing P01/Broker
    authorities choose among available browser/Worker/cloud/Desktop targets.
    """

    run_ref: str
    owner_ref: str
    workspace_ref: str
    capability: str
    mode: str
    inputs: tuple[DriveIndexSourceSnapshot, ...]
    output_folder_ref: str | None
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        for field in ("run_ref", "owner_ref", "workspace_ref"):
            _ref(getattr(self, field), field)
        if not isinstance(self.capability, str) or _CAPABILITY.fullmatch(self.capability) is None:
            raise WorkTicketContractError("capability must be a bounded capability name")
        if not isinstance(self.mode, str) or self.mode not in MODES:
            raise WorkTicketContractError("unknown execution output mode")
        if not isinstance(self.inputs, tuple) or not 1 <= len(self.inputs) <= MAX_WORK_TICKET_INPUTS:
            raise WorkTicketContractError("ticket requires bounded immutable Drive input refs")
        seen: set[tuple[str | None, str]] = set()
        for item in self.inputs:
            if not isinstance(item, DriveIndexSourceSnapshot):
                raise WorkTicketContractError("input requires canonical Drive version metadata")
            _ref(item.file_id, "file_id", drive=True)
            if item.drive_id is not None:
                _ref(item.drive_id, "drive_id", drive=True)
            if not item.has_version_evidence:
                raise WorkTicketContractError("input must carry Drive source version evidence")
            identifier = (item.drive_id, item.file_id)
            if identifier in seen:
                raise WorkTicketContractError("duplicate Drive input")
            seen.add(identifier)
        if self.mode == "inspect":
            if self.output_folder_ref is not None:
                raise WorkTicketContractError("inspect ticket must not name a WRITE destination")
        else:
            _ref(self.output_folder_ref, "output_folder_ref", drive=True)
        issued = _utc(self.issued_at, "issued_at")
        expires = _utc(self.expires_at, "expires_at")
        if not issued < expires <= issued + timedelta(seconds=MAX_WORK_TICKET_TTL_SECONDS):
            raise WorkTicketContractError("ticket lifetime is outside the bounded lease window")

    def is_within_time_window(self, now: datetime) -> bool:
        """Time predicate ONLY. NOT evidence of ownership, approval or dispatch."""
        observed = _utc(now, "now")
        return _utc(self.issued_at, "issued_at") <= observed < _utc(self.expires_at, "expires_at")


__all__ = [
    "EphemeralExecutionWorkTicket",
    "WorkTicketContractError",
    "MAX_WORK_TICKET_INPUTS",
    "MAX_WORK_TICKET_TTL_SECONDS",
]
