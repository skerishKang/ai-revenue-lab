"""#3782: hermetic per-command P01 fetch and live-policy recheck.

Test-only local opener simulates an independent canonical evidence owner. No
production P01 service, approval or browser command is activated.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from kagent.browser_control_broker_work_ticket import (
    AuthenticatedBrowserControlWorkTicket,
)
from kagent.browser_control_lease_authority import (
    BrowserControlLeaseAuthority,
    BrowserControlLeaseRefusal,
    P01PerCommandBrowserControlEvidenceClient,
)
from kagent.browser_control_lease_store import BrowserControlLeaseStore
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule,
    LocalCapability,
    LocalPolicyMode,
    default_device_permission_profile,
)
from test_browser_control_broker_work_ticket import NOW, ticket


def envelope(t: AuthenticatedBrowserControlWorkTicket):
    e = t.evidence
    p = e.approval_pause
    d = e.approval_decision
    r = e.permission_request
    return {
        "command_id": t.command.command_id,
        "binding_ref": t.binding.binding_ref,
        "request_id": t.admission.request_id,
        "admission_ref": t.admission.admission_ref,
        "revision_ref": t.admission.revision_ref,
        "evidence_ref": e.evidence_ref,
        "request_fingerprint": e.request_fingerprint,
        "approval_pause": {
            "pause_id": p.pause_id, "run_id": p.run_id,
            "agent_runtime_id": p.agent_runtime_id, "tool_id": p.tool_id,
            "invocation_sha256": p.invocation_sha256,
            "requirement": p.requirement.value, "step_index": p.step_index,
            "created_at": p.created_at.isoformat(),
            "expires_at": p.expires_at.isoformat(),
            "approval_scope": list(p.approval_scope),
        },
        "approval_decision": {
            "decision_id": d.decision_id, "pause_id": d.pause_id,
            "outcome": d.outcome.value, "authority_ref": d.authority_ref,
            "evidence_ref": d.evidence_ref, "decided_at": d.decided_at.isoformat(),
        },
        "permission_requests": [{
            "action_id": r.action_id, "run_id": r.run_id,
            "device_id": r.device_id, "capability": r.capability.value,
            "target_ref": r.target_ref, "root_ref": r.root_ref,
        }],
        "local_policy_ref": e.local_policy_ref,
        "expires_at": e.expires_at.isoformat(),
    }


def make_authority(t, store, *, correlation=None, edit_envelope=None, deny=False):
    device = LocalAgentDeviceProfile(
        device_id=t.lease_request.device_id,
        workspace_ref=t.lease_request.workspace_ref,
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="work.3782", windows_path=r"E:\\work"),),
    )
    profile = default_device_permission_profile(device=device)
    if deny:
        rules = tuple(
            CapabilityRule(
                rule.capability,
                LocalPolicyMode.DENY if rule.capability == LocalCapability.BROWSER_CONTROL else rule.mode,
            )
            for rule in profile.global_rules
        )
        profile = replace(profile, global_rules=rules)
    seen = []
    def opener(data):
        seen.append(json.loads(data))
        body = envelope(t)
        if edit_envelope is not None:
            edit_envelope(body)
        return {"envelope": body}

    evidence_port = P01PerCommandBrowserControlEvidenceClient(
        correlation=correlation or t.correlation,
        base_url="", opener=opener,
    )
    authority = BrowserControlLeaseAuthority(
        device=device, permission_profile=profile, store=store, evidence_port=evidence_port,
    )
    return authority, seen


def test_current_p01_verification_reuses_real_lease_validation_but_does_not_issue():
    t = ticket()
    with tempfile.TemporaryDirectory() as directory:
        store = BrowserControlLeaseStore(str(Path(directory) / "leases.sqlite"))
        try:
            authority, seen = make_authority(t, store)
            assert store.get(t.lease_request.fingerprint()) is None
            result = t.verify_current_p01(authority, now=NOW)
            assert result == t.evidence
            assert len(seen) == 1
            assert seen[0] == {
                "command_id": t.correlation.command_id,
                "binding_ref": t.correlation.binding_ref,
                "request_id": t.correlation.request_id,
                "request_fingerprint": t.correlation.request_fingerprint,
            }
            assert store.get(t.lease_request.fingerprint()) is None
            assert t.safe_dict()["durable_take_performed"] is False
            assert t.safe_dict()["browser_action_executed"] is False
        finally:
            store.close()


@pytest.mark.parametrize("change", [
    "wrong_command", "wrong_binding", "wrong_request", "wrong_revision",
    "wrong_admission", "wrong_run", "wrong_digest", "denied_decision",
    "expired_p01", "different_ticket_evidence", "locally_denied",
])
def test_live_p01_mismatch_or_denial_leaves_zero_lease_rows(change):
    t = ticket()
    correlation = None
    edit = None
    deny = change == "locally_denied"
    if change == "wrong_command":
        edit = lambda body: body.__setitem__("command_id", "command.other")
    elif change == "wrong_binding":
        edit = lambda body: body.__setitem__("binding_ref", "binding.other")
    elif change == "wrong_request":
        edit = lambda body: body.__setitem__("request_id", "request.other")
    elif change == "wrong_revision":
        edit = lambda body: body.__setitem__("revision_ref", "revision.other")
    elif change == "wrong_admission":
        edit = lambda body: body.__setitem__("admission_ref", "admission.other")
    elif change == "wrong_run":
        edit = lambda body: body["approval_pause"].__setitem__("run_id", "run.other")
    elif change == "wrong_digest":
        edit = lambda body: body["approval_pause"].__setitem__(
            "invocation_sha256", "a" * 64,
        )
    elif change == "denied_decision":
        edit = lambda body: body["approval_decision"].__setitem__("outcome", "denied")
    elif change == "expired_p01":
        edit = lambda body: body.__setitem__(
            "expires_at", "2026-10-08T10:59:00+00:00",
        )
    elif change == "different_ticket_evidence":
        edit = lambda body: body["approval_decision"].__setitem__(
            "decision_id", "decision.other",
        )
    with tempfile.TemporaryDirectory() as directory:
        store = BrowserControlLeaseStore(str(Path(directory) / "leases.sqlite"))
        try:
            authority, _seen = make_authority(
                t, store, correlation=correlation, edit_envelope=edit, deny=deny,
            )
            with pytest.raises((ContractError, BrowserControlLeaseRefusal)):
                t.verify_current_p01(authority, now=NOW)
            assert store.get(t.lease_request.fingerprint()) is None
        finally:
            store.close()


def test_same_fingerprint_does_not_accept_a_different_broker_command_context():
    t = ticket()
    bad_correlation = replace(
        t.correlation,
        command_id="command.different",
    )
    with tempfile.TemporaryDirectory() as directory:
        store = BrowserControlLeaseStore(str(Path(directory) / "leases.sqlite"))
        try:
            authority, seen = make_authority(t, store, correlation=bad_correlation)
            with pytest.raises(ContractError, match="per-command"):
                t.verify_current_p01(authority, now=NOW)
            assert seen == []
            assert store.get(t.lease_request.fingerprint()) is None
        finally:
            store.close()
