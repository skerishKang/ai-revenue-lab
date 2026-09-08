from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import ControlPlaneContractError
from .local_agent_broker import BrokerDeviceBinding, InMemoryLocalAgentBrokerAuthority
from .local_agent_broker_state import (
    LocalAgentBrokerStatePort,
    VersionedLocalAgentBrokerState,
)


def authenticate_local_agent_binding(
    authority: InMemoryLocalAgentBrokerAuthority,
    *,
    binding_ref: str,
    credential: bytes,
    now: datetime,
) -> BrokerDeviceBinding:
    """Read-only public seam over the canonical broker credential verifier.

    Credential digesting, constant-time comparison, expiry, revocation and binding
    validation remain owned by ``InMemoryLocalAgentBrokerAuthority._authenticate``.
    This function intentionally adds no second credential algorithm.
    """

    if not isinstance(authority, InMemoryLocalAgentBrokerAuthority):
        raise ValueError("authority must be InMemoryLocalAgentBrokerAuthority")
    return authority._authenticate(binding_ref, credential, now=now)


class StateBackedLocalAgentBindingAuthenticator:
    """Read-only authentication projection over persisted canonical broker state."""

    def __init__(
        self,
        *,
        pepper: bytes,
        authority_ref: str,
        state_port: LocalAgentBrokerStatePort,
    ) -> None:
        probe = InMemoryLocalAgentBrokerAuthority(pepper=pepper, authority_ref=authority_ref)
        if not callable(getattr(state_port, "load", None)):
            raise ValueError("state_port must implement broker state load")
        if type(getattr(state_port, "durable", None)) is not bool:
            raise ValueError("state_port must explicitly declare durable boolean")
        self._pepper = pepper
        self.authority_ref = probe.authority_ref
        self._state_port = state_port

    def authenticate(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        now: datetime,
    ) -> BrokerDeviceBinding:
        stored = self._state_port.load(authority_ref=self.authority_ref)
        if not isinstance(stored, VersionedLocalAgentBrokerState):
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state",
                "state port returned invalid broker state",
            )
        if stored.snapshot.authority_ref != self.authority_ref:
            raise ControlPlaneContractError(
                "invalid_local_agent_broker_state",
                "state port returned wrong authority state",
            )
        authority = stored.snapshot.restore(pepper=self._pepper)
        return authenticate_local_agent_binding(
            authority,
            binding_ref=binding_ref,
            credential=credential,
            now=now,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "read_only_binding_authentication": True,
            "canonical_broker_credential_verifier_reused": True,
            "second_credential_verifier": False,
            "state_mutation": False,
            "credential_digest_exposed": False,
            "raw_device_credential_returned": False,
            "production_ready": False,
        }


READ_ONLY_BINDING_AUTHENTICATION = True
CANONICAL_BROKER_CREDENTIAL_VERIFIER_REUSED = True
SECOND_CREDENTIAL_VERIFIER = False
AUTHENTICATION_STATE_MUTATION = False
RAW_DEVICE_CREDENTIAL_RETURNED = False
PRODUCTION_READY = False
