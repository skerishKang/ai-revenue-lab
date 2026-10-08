"""#3782: private, injected canonical P01 approval source contract.

Only a service-identity-authenticated first-party approval resolver may be
injected at the Broker composition root. No such source is connected today.
This module does NOT accept a caller's decision JSON or mint user approval.
The approval and local device permission decision belong to their existing
canonical authorities. Product registration remains disabled without a source.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from local_agent_broker_browser_control_take import BrowserControlCommandTakeCorrelation

_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("P01 browser approval requires an aware datetime")
    return value.astimezone(timezone.utc)


def browser_control_tool_invocation_digest(material: dict[str, Any]) -> str:
    """Match Core tool_invocation_digest(BrowserControlLeaseRequest.tool_invocation()).

    Material validation and recomputed session fingerprint are mandatory
    BEFORE this helper is used. It does not authenticate material or P01.
    """
    ctx = material["context"]
    args = {
        "browser_session_ref": ctx["browserSessionRef"],
        "run_ref": ctx["runRef"],
        "workspace_ref": ctx["workspaceRef"],
        "owner_ref": ctx["ownerRef"],
        "device_id": ctx["deviceRef"],
        "origin_scope": ctx["originScope"],
        "allowed_action_classes": ctx["allowedActionClasses"],
        "ttl_seconds": ctx["ttlSeconds"],
        "max_actions": ctx["maxActions"],
    }
    encoded = json.dumps(
        {"tool_id": "browser.control", "arguments": args},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class AuthenticatedBrowserControlP01Approval:
    """Server-resolved evidence projection; data itself is NOT a bearer grant.

    The upstream resolver is responsible for querying the *existing* real P01
    decision + pause using first-party authenticated service identity, checking
    the user and local device policy, and returning this closed proof. Caller-
    supplied instance/JSON must NEVER be accepted as a resolver.
    """

    command_ref: str
    binding_ref: str
    request_id: str
    run_ref: str
    request_fingerprint: str
    admission_ref: str
    revision_ref: str
    evidence_ref: str
    pause_ref: str
    decision_ref: str
    approval_tool_id: str
    approval_invocation_sha256: str
    approval_scope: tuple[str, ...]
    decision_outcome: str
    local_permission_result: str
    decided_at: datetime
    expires_at: datetime

    def assert_matches(
        self, *,
        scope: BrowserControlCommandTakeCorrelation,
        expected_invocation_sha256: str,
        now: datetime,
    ) -> None:
        if type(self) is not AuthenticatedBrowserControlP01Approval:
            raise ValueError("P01 browser approval has wrong provenance shape")
        if not isinstance(scope, BrowserControlCommandTakeCorrelation):
            raise TypeError("canonical Broker correlation required")
        for name in (
            "command_ref", "binding_ref", "request_id", "run_ref",
            "request_fingerprint", "admission_ref", "revision_ref",
        ):
            if getattr(self, name) != getattr(scope, name):
                raise ValueError("P01 browser approval is for another Broker command")
        if not all(
            isinstance(value, str) and _SAFE_REF.fullmatch(value)
            for value in (self.evidence_ref, self.pause_ref, self.decision_ref)
        ):
            raise ValueError("P01 browser approval references invalid")
        if (
            self.approval_tool_id != "browser.control"
            or self.decision_outcome != "approved"
            or self.local_permission_result not in
            ("locally_allowed", "require_p01_approval")
            or type(self.approval_scope) is not tuple
            or "browser.control" not in self.approval_scope
            or len(self.approval_scope) != 1
            or not isinstance(self.approval_invocation_sha256, str)
            or _SHA256.fullmatch(self.approval_invocation_sha256) is None
            or self.approval_invocation_sha256 != expected_invocation_sha256
        ):
            raise ValueError("P01 browser approval does not authorize this exact action scope")
        current = _aware(now)
        decision_at = _aware(self.decided_at)
        expiry = _aware(self.expires_at)
        if decision_at > current or expiry <= current or expiry <= decision_at:
            raise ValueError("P01 browser approval unavailable or expired")


class CanonicalBrowserControlP01ApprovalSource(Protocol):
    """Only the authenticated first-party Broker composition may implement.

    It must obtain an actually verified, independently APPROVED per-command
    browser.control decision from the canonical Engine P01 continuation owner,
    not from the #3140 process.execute acceptance lane or device-supplied JSON.
    """

    def resolve_approved_command(
        self, *,
        scope: BrowserControlCommandTakeCorrelation,
        now: datetime,
    ) -> AuthenticatedBrowserControlP01Approval: ...


BROKER_BROWSER_CONTROL_P01_SOURCE_WIRED = False
