"""Public-safe event projection primitives for IP-SIDECAR.

Only allowlisted event types with bounded text-only payloads may be
projected. Anything resembling hidden reasoning, raw tool arguments/results,
raw terminal output, credentials, or provider payloads fails closed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .errors import SidecarContractError

ALLOWED_EVENT_TYPES = frozenset(
    {
        "shell.opened",
        "shell.closed",
        "shell.disabled",
        "shell.open_failed",
        "context.received",
        "notice.posted",
    }
)

_FORBIDDEN_FIELD_RE = re.compile(
    r"reason|thought|chain|tool|argument|result|terminal|stdout|stderr|"
    r"secret|token|credential|password|key|provider|payload|raw|trace|log",
    re.IGNORECASE,
)

MAX_TEXT_CHARS = 280
MAX_DATA_FIELDS = 8
MAX_DATA_KEY_CHARS = 64
MAX_DATA_VALUE_CHARS = 512
_DATA_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class PublicEvent:
    """Immutable, JSON-serializable, public-safe event."""

    type: str
    host_id: str
    seq: int
    text: str = ""
    data: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def to_public_dict(self) -> dict[str, object]:
        return {
            "type": self.type,
            "host_id": self.host_id,
            "seq": self.seq,
            "text": self.text,
            "data": {key: value for key, value in self.data},
        }


def project_event(
    event_type: str,
    host_id: str,
    seq: int,
    text: str = "",
    data: Mapping[str, object] | None = None,
) -> PublicEvent:
    """Build a validated :class:`PublicEvent` or fail closed."""
    if event_type not in ALLOWED_EVENT_TYPES:
        raise SidecarContractError(f"event type {event_type!r} is not public-safe")
    if not isinstance(host_id, str) or not host_id:
        raise SidecarContractError("host_id must be non-empty text")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        raise SidecarContractError("seq must be a non-negative integer")
    if not isinstance(text, str):
        raise SidecarContractError("event text must be text")
    if len(text) > MAX_TEXT_CHARS:
        raise SidecarContractError("event text exceeds the bound")
    if _FORBIDDEN_FIELD_RE.search(text):
        raise SidecarContractError("event text resembles non-public material")

    pairs: list[tuple[str, str]] = []
    if data is not None:
        if not isinstance(data, Mapping):
            raise SidecarContractError("event data must be a mapping")
        if len(data) > MAX_DATA_FIELDS:
            raise SidecarContractError("event data exceeds the field bound")
        for key, value in data.items():
            if not isinstance(key, str) or _DATA_KEY_RE.fullmatch(key) is None:
                raise SidecarContractError("event data keys must be bounded names")
            if len(key) > MAX_DATA_KEY_CHARS:
                raise SidecarContractError("event data key exceeds the bound")
            if _FORBIDDEN_FIELD_RE.search(key):
                raise SidecarContractError(f"event data key {key!r} is not public-safe")
            if not isinstance(value, str):
                raise SidecarContractError("event data values must be text")
            if len(value) > MAX_DATA_VALUE_CHARS:
                raise SidecarContractError("event data value exceeds the bound")
            if _FORBIDDEN_FIELD_RE.search(value):
                raise SidecarContractError("event data value resembles non-public material")
            pairs.append((key, value))

    return PublicEvent(
        type=event_type,
        host_id=host_id,
        seq=seq,
        text=text,
        data=tuple(pairs),
    )
