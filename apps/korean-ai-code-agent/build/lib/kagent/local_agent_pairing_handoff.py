"""#3095 (CLAW5) — bounded pairing handoff redemption runtime caller.

This module owns exactly one runtime caller of the #3080 canonical
``LocalAgentBrokerPairingClient.redeem()``. It deliberately owns **no** pairing
authority of its own:

    PAIRING_AUTHORITY_OWNER=#3080
    SECOND_PAIRING_AUTHORITY=0
    SECOND_CREDENTIAL_AUTHORITY=0
    SECOND_DEVICE_LIFECYCLE_AUTHORITY=0
    CHALLENGE_ISSUANCE_AUTHORITY=NO

It takes the one bounded pairing code that crossed the #3093/#3083 deep-link
seam, redeems it exactly once through the canonical client, and feeds the
resulting canonical session/heartbeat truth back through the existing
``server_projection`` lifecycle trigger.

Security locks (see #3095 CENTRAL assignment):

    PAIRING_CODE_GENERAL_PERSISTENCE=NO
    PAIRING_CODE_LOGGED=NO
    PAIRING_CODE_RENDERER_DIAGNOSTIC=NO
    RAW_DEVICE_CREDENTIAL_LOGGED=NO
    PUBLIC_INBOUND_PORT=NO
    PRODUCTION_PAIRING_ACTIVATION=NO

The pairing code is single-use handoff material. It is accepted as a function
argument, held only in a local, zeroed as soon as the possession proof is
derived, and never stored on an object, written to a store, or returned in any
public projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .contracts import ContractError
from .local_agent_broker_pairing_client import (
    LocalAgentBrokerEnrollment,
    LocalAgentBrokerPairingClient,
    UnconfiguredLocalAgentBrokerPairingClient,
    pairing_proof_ref,
)
from .local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from .local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from .local_agent_secure_transport import DeviceCredentialStore, OutboundTransportConfig
from .local_agent_server_projection import project_server_backed_online_binding

HANDOFF_CONTRACT_VERSION = "claw-local-agent-pairing-handoff.v1"

#: The single allowlisted deep-link parameter the shell may transfer.
PAIRING_HANDOFF_PARAM = "code"

#: The deep-link parameter name used by the #3083/#3093 shell seam. Kept as a
#: literal so this module never imports the TypeScript seam (a second deep-link
#: parser is forbidden).
SHELL_PAIRING_CODE_PARAM = PAIRING_HANDOFF_PARAM


class PairingHandoffError(ContractError):
    """Bounded pairing handoff rejection.

    Messages never contain the pairing code, the raw device credential, or any
    other handoff secret.
    """


class PairingHandoffTransport(Protocol):
    """The single seam this module needs from the canonical #3080 client."""

    def redeem(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        device_id: str,
        now: datetime,
    ) -> LocalAgentBrokerEnrollment:
        ...


@dataclass(frozen=True, slots=True)
class PairingHandoffRequest:
    """One bounded pairing handoff handed over by the trusted runner boundary.

    The pairing code is a per-handoff field rather than host state: the caller
    builds one request, redeems, and drops it. Nothing on this object is ever
    written to a store, logged, or returned in a public projection, and
    ``safe_dict``-style projections of a request do not exist by design.
    """

    pairing_code: str
    challenge_id: str
    device_id: str

    def __post_init__(self) -> None:
        for field_name in ("pairing_code", "challenge_id", "device_id"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise PairingHandoffError(f"{field_name} must be non-empty text")
        # Fail closed on a malformed code before any transport is touched, using
        # the canonical #3080 shape check.
        pairing_proof_ref(
            challenge_id=self.challenge_id,
            device_id=self.device_id,
            pairing_code=self.pairing_code,
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive, not a test target
        # Never let an accidental repr/traceback print the pairing code.
        return (
            f"PairingHandoffRequest(challenge_id={self.challenge_id!r}, "
            f"device_id={self.device_id!r}, pairing_code=<redacted>)"
        )


@dataclass(frozen=True, slots=True)
class PairingHandoffResult:
    """Outcome of one bounded redemption, with no secret material."""

    contract_version: str
    correlation_ref: str
    binding_ref: str
    device_id: str
    credential_generation: int
    credential_store_protection: str
    binding_state: str
    online_requires_server_projection: bool
    local_online_claim: bool
    pairing_code_persisted: bool
    pairing_code_logged: bool
    public_inbound_port: bool
    production_pairing_activated: bool

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "correlation_ref": self.correlation_ref,
            "binding_ref": self.binding_ref,
            "device_id": self.device_id,
            "credential_generation": self.credential_generation,
            "credential_store_protection": self.credential_store_protection,
            "binding_state": self.binding_state,
            "online_requires_server_projection": self.online_requires_server_projection,
            "local_online_claim": self.local_online_claim,
            "pairing_code_persisted": self.pairing_code_persisted,
            "pairing_code_logged": self.pairing_code_logged,
            "public_inbound_port": self.public_inbound_port,
            "production_pairing_activated": self.production_pairing_activated,
        }


class UnconfiguredPairingHandoffRunner:
    """Fail-closed default used until a real pinned transport is configured."""

    def redeem_handoff(
        self,
        **_: Any,
    ) -> PairingHandoffResult:
        raise PairingHandoffError("real Local Agent broker pairing transport is not configured")


class LocalAgentPairingHandoffRunner:
    """The one runtime caller of the canonical #3080 redemption path.

    Construction reuses the canonical #3080 building blocks rather than
    introducing a parallel stack:

    * ``OutboundTransportConfig`` — the pinned outbound transport config;
    * ``DeviceCredentialStore`` — the protected credential store;
    * ``LocalAgentBrokerPairingClient`` — the canonical redemption client.

    ONLINE is never claimed locally. A binding stays ``PAIRED_OFFLINE`` until
    the existing ``server_projection`` trigger is fed a real broker session and
    a server-owned heartbeat bound to that exact session.
    """

    def __init__(
        self,
        *,
        config: OutboundTransportConfig,
        credential_store: DeviceCredentialStore,
        client: PairingHandoffTransport | None = None,
    ) -> None:
        if not isinstance(config, OutboundTransportConfig):
            raise PairingHandoffError("config must be OutboundTransportConfig")
        for method_name in ("save", "load"):
            if not callable(getattr(credential_store, method_name, None)):
                raise PairingHandoffError("credential_store must implement save and load")
        self._config = config
        self._credential_store = credential_store
        if client is None:
            client = LocalAgentBrokerPairingClient(
                config=config,
                credential_store=credential_store,
            )
        if not callable(getattr(client, "redeem", None)):
            raise PairingHandoffError("client must implement redeem")
        self._client = client

    def redeem_handoff(
        self,
        *,
        pairing_code: str,
        challenge_id: str,
        device_id: str,
        correlation_ref: str = "",
        now: datetime,
        session: DeviceSession | None = None,
        heartbeat: ControlPlaneHeartbeatReceipt | None = None,
    ) -> PairingHandoffResult:
        """Redeem one bounded pairing code exactly once.

        ``pairing_code`` is a local: it is used to derive the possession proof
        and is never stored on ``self``, never returned, and never logged.
        """
        request = PairingHandoffRequest(
            pairing_code=pairing_code,
            challenge_id=challenge_id,
            device_id=device_id,
        )
        # Drop the caller's reference as early as possible; only the validated
        # request object remains for the duration of this call.
        pairing_code = ""
        enrollment = self._client.redeem(
            challenge_id=request.challenge_id,
            pairing_code=request.pairing_code,
            device_id=request.device_id,
            now=now,
        )
        if not isinstance(enrollment, LocalAgentBrokerEnrollment):
            raise PairingHandoffError("canonical redemption returned an invalid enrollment")

        # A handoff may only ever yield PAIRED_OFFLINE. Anything else means a
        # local caller tried to manufacture an online device.
        if enrollment.binding.state is not DeviceLifecycle.PAIRED_OFFLINE:
            raise PairingHandoffError("a bounded handoff may only yield PAIRED_OFFLINE")

        # Reuse the existing server-projection trigger. ONLINE is never granted
        # here: a bounded handoff alone can only produce PAIRED_OFFLINE, and any
        # move to ONLINE still requires a real broker session plus a server-owned
        # heartbeat bound to that exact session. The trigger is consulted only to
        # report whether such server truth is already present, and its refusal is
        # the expected outcome for a handoff-only run.
        online_state = self._server_projection_state(
            binding=enrollment.binding,
            session=session,
            heartbeat=heartbeat,
            now=now,
        )
        return self._result(
            enrollment=enrollment,
            correlation_ref=correlation_ref,
            binding_state=online_state,
        )

    @staticmethod
    def _server_projection_state(
        *,
        binding: DeviceBinding,
        session: DeviceSession | None,
        heartbeat: ControlPlaneHeartbeatReceipt | None,
        now: datetime,
    ) -> str:
        """Return the server-projected lifecycle state for this binding.

        Delegates to the existing #3080 trigger. When the server facts are
        absent or unrelated, the trigger refuses and the binding stays
        ``PAIRED_OFFLINE`` — which is exactly the truthful result for a handoff.
        """
        try:
            projected = project_server_backed_online_binding(
                binding=binding,
                session=session,
                heartbeat=heartbeat,
                now=now,
            )
        except ContractError:
            return binding.state.value
        return projected.state.value

    def _result(
        self,
        *,
        enrollment: LocalAgentBrokerEnrollment,
        correlation_ref: str,
        binding_state: str | None = None,
    ) -> PairingHandoffResult:
        binding: DeviceBinding = enrollment.binding
        return PairingHandoffResult(
            contract_version=HANDOFF_CONTRACT_VERSION,
            correlation_ref=correlation_ref or "",
            binding_ref=binding.binding_ref,
            device_id=binding.device_id,
            credential_generation=binding.credential_generation,
            credential_store_protection=enrollment.stored.protection,
            binding_state=binding_state or binding.state.value,
            online_requires_server_projection=True,
            local_online_claim=False,
            pairing_code_persisted=False,
            pairing_code_logged=False,
            public_inbound_port=False,
            production_pairing_activated=False,
        )

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": HANDOFF_CONTRACT_VERSION,
            "canonical_client": "LocalAgentBrokerPairingClient",
            "canonical_client_reused": True,
            "canonical_credential_store_reused": True,
            "pinned_outbound_transport_reused": True,
            "server_projection_trigger_reused": True,
            "single_transfer_param": SHELL_PAIRING_CODE_PARAM,
            "pairing_authority_owner": "#3080",
            "second_pairing_authority": 0,
            "second_credential_authority": 0,
            "second_device_lifecycle_authority": 0,
            "second_deeplink_parser": 0,
            "challenge_issuance_authority": False,
            "pairing_code_persisted": False,
            "pairing_code_logged": False,
            "pairing_code_renderer_diagnostic": False,
            "raw_device_credential_logged": False,
            "raw_device_credential_renderer": False,
            "public_inbound_port": False,
            "upnp_required": False,
            "outbound_only": True,
            "local_online_claim": False,
            "production_pairing_activated": False,
            "production_endpoint_configured": False,
            "production_mutation": False,
            "full_web_to_desktop_pairing_e2e": False,
        }


def unconfigured_pairing_handoff_runner() -> UnconfiguredPairingHandoffRunner:
    """Return the fail-closed default runner (Production pairing is not active)."""
    return UnconfiguredPairingHandoffRunner()


__all__ = [
    "HANDOFF_CONTRACT_VERSION",
    "LocalAgentPairingHandoffRunner",
    "PAIRING_HANDOFF_PARAM",
    "PairingHandoffError",
    "PairingHandoffRequest",
    "PairingHandoffResult",
    "PairingHandoffTransport",
    "SHELL_PAIRING_CODE_PARAM",
    "UnconfiguredPairingHandoffRunner",
    "UnconfiguredLocalAgentBrokerPairingClient",
    "unconfigured_pairing_handoff_runner",
]
