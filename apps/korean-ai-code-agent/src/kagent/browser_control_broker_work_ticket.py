"""#3782 — closed *validation* seam for canonical per-command browser.control work.

The broker must first durably authenticate/admit the command and the existing
P01 authority must separately verify the browser.control pause/decision.
Neither this validator nor its caller can create an approval, take a command,
or execute a browser action. Product ingress remains unconfigured.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from padiem_ai_core.agent_approval import ApprovalOutcome
from padiem_control_plane.local_agent_broker import BrokerCommandAdmission

from .browser_control_actions import BrowserControlActionRequest
from .browser_control_lease_authority import (
    BROWSER_CONTROL_TOOL_ID,
    BrowserControlAuthorityEvidence,
    BrowserControlLeaseRequest,
    BrowserControlP01CommandCorrelation,
)
from .contracts import ContractError
from .local_agent_pairing import (
    DeviceBinding,
    DeviceCommandEnvelope,
    DeviceLifecycle,
    DeviceSession,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedBrowserControlWorkTicket:
    """Correlate already-verified broker/P01 facts; NEVER authenticate raw client JSON.

    Creation requires a server-owned BrokerCommandAdmission and independently
    verified P01 evidence. A constructed object is NOT a durable command take:
    the broker must still enforce an atomic, restart-safe take before delivery.
    """

    command: DeviceCommandEnvelope
    admission: BrokerCommandAdmission
    binding: DeviceBinding
    session: DeviceSession
    correlation: BrowserControlP01CommandCorrelation
    lease_request: BrowserControlLeaseRequest
    evidence: BrowserControlAuthorityEvidence
    action: BrowserControlActionRequest
    host_lease_ref: str

    def validate_at(self, now: datetime) -> None:
        """Refuse mismatches BEFORE any Desktop delivery or Input.* execution."""
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ContractError("browser.control ticket requires an aware timestamp")
        now = now.astimezone(timezone.utc)
        if not all((
            isinstance(self.command, DeviceCommandEnvelope),
            isinstance(self.admission, BrokerCommandAdmission),
            isinstance(self.binding, DeviceBinding),
            isinstance(self.session, DeviceSession),
            isinstance(self.correlation, BrowserControlP01CommandCorrelation),
            isinstance(self.lease_request, BrowserControlLeaseRequest),
            isinstance(self.evidence, BrowserControlAuthorityEvidence),
            isinstance(self.action, BrowserControlActionRequest),
        )):
            raise ContractError("browser.control ticket requires canonical typed evidence")
        if (not isinstance(self.host_lease_ref, str) or not self.host_lease_ref
                or len(self.host_lease_ref) > 256 or not self.host_lease_ref.isascii()
                or not self.host_lease_ref[0].isalnum()):
            raise ContractError("browser.control ticket host lease reference is invalid")
        if not all(c.isalnum() or c in "._:/@+-" for c in self.host_lease_ref):
            raise ContractError("browser.control ticket host lease reference is unsafe")

        c, a, b, s, p, l, e, action = (
            self.command, self.admission, self.binding, self.session,
            self.correlation, self.lease_request, self.evidence, self.action,
        )
        # All three identity surfaces (broker command, live device, user scope)
        # must describe exactly the same device/workspace/run.
        if not (
            c.command_id == a.command_id == p.command_id == e.command_id
            and c.binding_ref == a.binding_ref == b.binding_ref == s.binding_ref == p.binding_ref
            and c.run_id == a.run_id == p.run_ref == l.run_ref
            and a.request_id == p.request_id
            and c.revision_ref == a.revision_ref == e.revision_ref
            and a.admission_ref == e.admission_ref
            and c.sequence == a.sequence
            and a.session_id == s.session_id
            and b.device_id == s.device_id == l.device_id == e.permission_request.device_id
            and b.account_ref == s.account_ref
            and b.workspace_ref == s.workspace_ref == l.workspace_ref
            and c.tool_request_ref == a.tool_request_ref
            and a.request_fingerprint == p.request_fingerprint == e.request_fingerprint == l.fingerprint()
        ):
            raise ContractError("browser.control ticket broker/device/P01 correlation mismatch")
        if not (
            e.approval_pause.run_id == l.run_ref
            and e.permission_request.run_id == l.run_ref
            and e.approval_pause.invocation_sha256 == l.approval_invocation_sha256()
            and BROWSER_CONTROL_TOOL_ID in e.approval_pause.approval_scope
            and e.permission_request.target_ref == l.target_ref()
            and e.approval_decision.outcome is ApprovalOutcome.APPROVED
            and e.approval_pause.pause_id == e.approval_decision.pause_id
            and action.browser_session_ref == l.browser_session_ref
            and action.origin_ref == l.origin_scope
            and action.action in l.allowed_action_classes
        ):
            raise ContractError("browser.control work ticket lacks exact approved action scope")
        if not (
            b.state in (DeviceLifecycle.PAIRED_OFFLINE, DeviceLifecycle.ONLINE)
            and b.issued_at <= now < b.credential_expires_at
            and s.issued_at <= now < s.expires_at
            and c.issued_at <= a.accepted_at <= now < c.expires_at
            and a.accepted_at <= now < a.expires_at
            and e.approval_pause.created_at <= e.approval_decision.decided_at <= now < e.approval_pause.expires_at
            and e.approval_decision.decided_at <= now < e.expires_at
        ):
            raise ContractError("browser.control work ticket or approval has expired")

    def safe_dict(self) -> dict[str, str | bool]:
        """No action text, page bytes, raw evidence, credentials or URL."""
        return {
            "command_id": self.command.command_id,
            "request_id": self.correlation.request_id,
            "binding_ref": self.correlation.binding_ref,
            "revision_ref": self.admission.revision_ref,
            "admission_ref": self.admission.admission_ref,
            "request_fingerprint": self.correlation.request_fingerprint,
            "capability": "browser.control",
            "approval_payload_exposed": False,
            "browser_action_executed": False,
            "durable_take_performed": False,
        }


BROKER_BROWSER_CONTROL_SOURCE_WIRED = False
DESKTOP_ACTION_DELIVERY_WIRED = False
