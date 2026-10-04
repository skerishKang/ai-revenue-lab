from __future__ import annotations

from datetime import datetime
from typing import Any

from .contracts import ControlPlaneContractError
from .local_agent_broker import (
    BrokerDeviceBinding,
    BrokerDeviceSession,
    InMemoryLocalAgentBrokerAuthority,
)
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


def authenticate_local_agent_device_session(
    authority: InMemoryLocalAgentBrokerAuthority,
    *,
    session_id: str,
    binding_ref: str,
    credential: bytes,
    now: datetime,
) -> BrokerDeviceSession:
    """#3436 B2c — read-only public seam over the canonical broker session verifier.

    Exactly the authentication preamble the canonical ``poll`` path has always
    taken, and nothing more: the binding is verified by
    ``InMemoryLocalAgentBrokerAuthority._authenticate`` (digest, expiry,
    revocation) and the session by ``InMemoryLocalAgentBrokerAuthority._session``
    (existence, lifetime, and the full binding-scope correlation
    binding/device/account/workspace/credential-generation). No new credential
    algorithm, no state mutation, and no caller-supplied identity is accepted:
    ``account_ref`` and ``workspace_ref`` come only from the verified canonical
    binding state.
    """

    if not isinstance(authority, InMemoryLocalAgentBrokerAuthority):
        raise ValueError("authority must be InMemoryLocalAgentBrokerAuthority")
    binding = authority._authenticate(binding_ref, credential, now=now)
    return authority._session(session_id, binding=binding, now=now)


def authenticated_device_session_projection(session: BrokerDeviceSession) -> dict[str, Any]:
    """The closed safe projection of one authenticated canonical device session.

    Assembled field-by-field from the server-verified session/binding facts.
    The raw device credential and its digest never appear, and nothing here is
    persisted or mutated.
    """

    return {
        "authenticated": True,
        "session_id": session.session_id,
        "binding_ref": session.binding_ref,
        "device_id": session.device_id,
        "account_ref": session.account_ref,
        "workspace_ref": session.workspace_ref,
        "credential_generation": session.credential_generation,
        "session_expires_at": session.expires_at.isoformat(),
        "credential_digest_exposed": False,
        "raw_device_credential": False,
    }


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

    def authenticate_device_session(
        self,
        *,
        session_id: str,
        binding_ref: str,
        credential: bytes,
        now: datetime,
    ) -> dict[str, Any]:
        """#3436 B2c — the read-only device-session authentication projection.

        Loads the canonical persisted broker state, restores the canonical
        authority over it, and reuses the one canonical verifier through
        ``authenticate_local_agent_device_session``. The state port is only
        ever read: no compare-and-swap, no snapshot write, no compaction. The
        result is the closed safe projection — the caller-supplied material
        names nothing but itself, and ``account_ref``/``workspace_ref`` are
        derived from the verified canonical binding state.
        """

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
        session = authenticate_local_agent_device_session(
            authority,
            session_id=session_id,
            binding_ref=binding_ref,
            credential=credential,
            now=now,
        )
        return authenticated_device_session_projection(session)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "read_only_binding_authentication": True,
            "canonical_broker_credential_verifier_reused": True,
            "second_credential_verifier": False,
            "state_mutation": False,
            "credential_digest_exposed": False,
            "raw_device_credential_returned": False,
            "device_session_authentication_read_only": True,
            "device_session_scope_correlation_reused": True,
            "production_ready": False,
        }


READ_ONLY_BINDING_AUTHENTICATION = True
CANONICAL_BROKER_CREDENTIAL_VERIFIER_REUSED = True
SECOND_CREDENTIAL_VERIFIER = False
AUTHENTICATION_STATE_MUTATION = False
RAW_DEVICE_CREDENTIAL_RETURNED = False
PRODUCTION_READY = False

# --- #3436 B2c: the device-session authentication projection -----------------
DEVICE_SESSION_AUTHENTICATION_READ_ONLY = True
DEVICE_SESSION_AUTHENTICATION_STATE_MUTATION = False
CANONICAL_BROKER_SESSION_VERIFIER_REUSED = True
AUTHENTICATED_DEVICE_SESSION_PROJECTION_ONLY = True
CALLER_IDENTITY_AUTHORITY = False
SERVER_DERIVED_ACCOUNT_REF = True
SERVER_DERIVED_WORKSPACE_REF = True
RAW_DEVICE_CREDENTIAL_LOGGED = False
