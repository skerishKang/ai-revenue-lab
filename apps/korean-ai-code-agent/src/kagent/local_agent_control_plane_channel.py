from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .contracts import ContractError
from .local_agent_command_material import OutboundCommandMaterialRequest, ResolvedLocalCommandMaterial
from .local_agent_control_plane_https import ControlPlaneHttpsLongPollTransport
from .local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceSession
from .local_agent_secure_channel import PinnedOutboundBrokerBinding, PinnedOutboundLocalAgentChannel
from .local_agent_secure_transport import OutboundPollRequest


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


class ControlPlanePinnedHttpsChannel(PinnedOutboundLocalAgentChannel):
    """Pinned-channel composition for the physical Control Plane HTTPS source.

    It reuses the existing channel's poll/material correlation and adds only the
    physical operations that require trusted broker metadata not present in the
    generic M2a port: session opening, fingerprint-derived material requests and
    admission/evidence-bound acknowledgement.
    """

    def __init__(
        self,
        *,
        authority: PinnedOutboundBrokerBinding,
        transport: ControlPlaneHttpsLongPollTransport,
    ) -> None:
        if not isinstance(transport, ControlPlaneHttpsLongPollTransport):
            raise ContractError("transport must be ControlPlaneHttpsLongPollTransport")
        super().__init__(authority=authority, transport=transport)
        self._control_plane_transport = transport

    def open_session(
        self,
        *,
        binding: DeviceBinding,
        session_id: str,
        now: datetime,
        ttl_seconds: int = 900,
    ) -> DeviceSession:
        now = _aware(now, "now")
        self.authority.require_current_binding(binding, now=now)
        session = self._control_plane_transport.open_session(
            config=self.authority.config,
            binding=binding,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
        )
        self.authority.require_session(session, now=now)
        return session

    def build_material_request(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        request_ref: str,
        now: datetime,
    ) -> OutboundCommandMaterialRequest:
        now = _aware(now, "now")
        self.authority.require_current_binding(binding, now=now)
        self.authority.require_session(session, now=now)
        self._prune_polled_commands(now=now)
        observed = self._polled_commands.get(command.command_id)
        if observed is None:
            raise ContractError("material request requires exact command previously polled by this channel")
        observed_session_id, observed_command = observed
        if observed_session_id != session.session_id or observed_command != command:
            raise ContractError("material request does not match exact polled command/session")
        fingerprint = self._control_plane_transport.request_fingerprint_for(
            config=self.authority.config,
            binding=binding,
            session=session,
            command=command,
            now=now,
        )
        return OutboundCommandMaterialRequest(
            request_ref=request_ref,
            session=session,
            command=command,
            request_fingerprint=fingerprint,
            requested_at=now,
        )

    def resolve_broker_material(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command: DeviceCommandEnvelope,
        request_ref: str,
        now: datetime,
    ) -> ResolvedLocalCommandMaterial:
        request = self.build_material_request(
            binding=binding,
            session=session,
            command=command,
            request_ref=request_ref,
            now=now,
        )
        return self.resolve_material(binding=binding, request=request)

    def acknowledge_admitted(
        self,
        *,
        binding: DeviceBinding,
        session: DeviceSession,
        command_id: str,
        admission_ref: str,
        evidence_ref: str,
        now: datetime,
    ) -> None:
        now = _aware(now, "now")
        self.authority.require_current_binding(binding, now=now)
        self.authority.require_session(session, now=now)
        self._prune_polled_commands(now=now)
        observed = self._polled_commands.get(command_id)
        if observed is None or observed[0] != session.session_id:
            raise ContractError("acknowledgement requires exact command previously polled by this channel/session")
        self._control_plane_transport.acknowledge(
            config=self.authority.config,
            binding=binding,
            session=session,
            command_id=command_id,
            admission_ref=admission_ref,
            evidence_ref=evidence_ref,
            now=now,
        )
        self._polled_commands.pop(command_id, None)

    def safe_dict(self) -> dict[str, Any]:
        base = super().safe_dict()
        return {
            **base,
            "physical_transport": self._control_plane_transport.safe_dict(),
            "material_fingerprint_caller_supplied": False,
            "ack_admission_ref_required": True,
            "ack_evidence_ref_required": True,
            "public_inbound_port": False,
            "production_broker_configured": False,
            "real_remote_execution": False,
        }


PINNED_CONTROL_PLANE_HTTPS_CHANNEL = True
MATERIAL_FINGERPRINT_CALLER_SUPPLIED = False
ACK_ADMISSION_REF_REQUIRED = True
ACK_EVIDENCE_REF_REQUIRED = True
PUBLIC_INBOUND_PORT = False
PRODUCTION_BROKER_CONFIGURED = False
PRODUCTION_READY = False
