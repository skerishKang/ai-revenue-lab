"""Abstract Engine port for IP-SIDECAR (S2).

S2 must not implement Engine transport. Any Engine call surface is
represented only by the injected abstract :class:`EnginePort` interface or
by the deterministic :class:`DeterministicFakeEnginePort` used in tests and
the reference host. No network, no credentials, no machine auth.
"""

from __future__ import annotations

import abc
import copy
from typing import Mapping

from .errors import SidecarContractError

ALLOWED_FAKE_CAPABILITIES = frozenset({"context.project", "notice.render"})


class EnginePort(abc.ABC):
    """Abstract capability port. Transport is explicitly out of S2 scope."""

    @abc.abstractmethod
    def invoke_capability(self, capability: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        """Invoke one allowlisted capability. Transport-defined in later slices."""
        raise NotImplementedError


class DeterministicFakeEnginePort(EnginePort):
    """Deterministic canned-response port for tests and the reference host."""

    def __init__(self, canned: Mapping[str, Mapping[str, object]]) -> None:
        if not isinstance(canned, Mapping):
            raise SidecarContractError("canned responses must be a mapping")
        for capability in canned:
            if capability not in ALLOWED_FAKE_CAPABILITIES:
                raise SidecarContractError(
                    f"fake capability {capability!r} is not reviewed for S2"
                )
        self._canned = copy.deepcopy(dict(canned))
        self.calls: list[tuple[str, dict[str, object]]] = []

    def invoke_capability(self, capability: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        if capability not in ALLOWED_FAKE_CAPABILITIES:
            raise SidecarContractError(f"capability {capability!r} is not reviewed for S2")
        if not isinstance(payload, Mapping):
            raise SidecarContractError("capability payload must be a mapping")
        self.calls.append((capability, dict(payload)))
        response = self._canned.get(capability, {"ok": True})
        return copy.deepcopy(dict(response))
