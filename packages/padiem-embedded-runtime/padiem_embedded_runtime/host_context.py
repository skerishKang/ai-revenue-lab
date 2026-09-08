"""Host-context boundary for IP-SIDECAR.

Host-provided context is untrusted input by default. It is never identity,
entitlement, or system authority: reserved authority keys are dropped (names
only are recorded, values never retained), and the envelope always reports
``trust_level="untrusted"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .errors import SidecarContractError

RESERVED_AUTHORITY_KEYS = frozenset(
    {
        "identity",
        "subject",
        "session",
        "role",
        "admin",
        "entitlement",
        "tenant",
        "tenant_id",
        "billing",
        "audit",
        "system",
        "authority",
    }
)

TRUST_LEVEL_UNTRUSTED = "untrusted"

MAX_CONTEXT_FIELDS = 16
MAX_KEY_CHARS = 64
MAX_VALUE_CHARS = 512
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class HostContextEnvelope:
    """Immutable envelope over sanitized host context."""

    host_id: str
    trust_level: str = TRUST_LEVEL_UNTRUSTED
    fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    dropped_reserved: tuple[str, ...] = field(default_factory=tuple)

    def sanitized_view(self) -> dict[str, str]:
        """Return the untrusted key/value view (never authority)."""
        return {key: value for key, value in self.fields}

    def to_public_dict(self) -> dict[str, object]:
        return {
            "host_id": self.host_id,
            "trust_level": self.trust_level,
            "fields": self.sanitized_view(),
            "dropped_reserved_count": len(self.dropped_reserved),
        }


def envelop_host_context(host_id: str, raw: Mapping[str, object]) -> HostContextEnvelope:
    """Validate untrusted host input into a :class:`HostContextEnvelope`."""
    if not isinstance(host_id, str) or not host_id:
        raise SidecarContractError("host_id must be non-empty text")
    if not isinstance(raw, Mapping):
        raise SidecarContractError("host context must be a mapping")
    if len(raw) > MAX_CONTEXT_FIELDS:
        raise SidecarContractError("host context exceeds the field bound")

    kept: list[tuple[str, str]] = []
    dropped: list[str] = []
    for key, value in raw.items():
        if not isinstance(key, str) or _KEY_RE.fullmatch(key) is None:
            raise SidecarContractError("host context keys must be bounded names")
        if len(key) > MAX_KEY_CHARS:
            raise SidecarContractError("host context key exceeds the bound")
        if key in RESERVED_AUTHORITY_KEYS:
            dropped.append(key)
            continue
        if not isinstance(value, str):
            raise SidecarContractError("host context values must be text")
        if len(value) > MAX_VALUE_CHARS:
            raise SidecarContractError("host context value exceeds the bound")
        kept.append((key, value))

    return HostContextEnvelope(
        host_id=host_id,
        trust_level=TRUST_LEVEL_UNTRUSTED,
        fields=tuple(kept),
        dropped_reserved=tuple(sorted(set(dropped))),
    )
