"""#3669 — canonical P01 + durable bounded-lease admission authority tests (CENTRAL ruling §3–§4).

Exercises the implementation in `kagent.browser_control_lease_authority`
against the ruling's closed matrix: the P01 decision (approved / missing /
denied / expired), the capability and correlation bindings, the local policy
recompute where a DENY wins, the three-way TTL cap, idempotent lazy issuance,
and the loopback P01 evidence client that reuses the existing
`/v1/broker/p01-evidence` route without any durable run-store precondition.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

from kagent.browser_control_lease_authority import (
    AUTO_RECOVERY_REAUTHORIZE,
    BROWSER_CONTROL_TOOL_ID,
    CANONICAL_LEASE_REFUSAL_CODES,
    DESKTOP_DURABLE_LEASE_AUTHORITY,
    DURABLE_RUN_STORE_TOUCHED,
    ISSUANCE_REFUSAL_CODES,
    LEASE_RENEWAL_SUPPORTED,
    NEW_APPROVAL_STORE,
    NEW_DURABLE_LEASE_STORE,
    P01LoopbackBrowserControlEvidenceClient,
    P01PerCommandBrowserControlEvidenceClient,
    BrowserControlP01CommandCorrelation,
    RENDERER_LEASE_MINTING,
    STEP_UP_EXECUTION,
    BrowserControlAuthorityEvidence,
    BrowserControlLeaseAuthority,
    BrowserControlLeaseRefusal,
    BrowserControlLeaseRequest,
    DeterministicBrowserControlEvidencePort,
    UnconfiguredBrowserControlEvidencePort,
)
from kagent.browser_control_lease_store import (
    LEASE_REFUSAL_CODES,
    BrowserControlLeaseIssuance,
    BrowserControlLeaseStore,
)
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPermissionRequest,
    LocalPolicyMode,
    default_device_permission_profile,
)

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
ORIGIN = "https://example.com"

DEVICE = LocalAgentDeviceProfile(
    device_id="device_3669",
    workspace_ref="workspace_3669",
    platform=LocalAgentPlatform.WINDOWS,
    roots=(LocalRoot(root_ref="root_work", windows_path=r"E:\work"),),
)


def make_request(**overrides: Any) -> BrowserControlLeaseRequest:
    fields: dict[str, Any] = {
        "browser_session_ref": "run/session-1",
        "run_ref": "run_3669",
        "workspace_ref": "workspace_3669",
        "owner_ref": "owner_3669",
        "device_id": "device_3669",
        "origin_scope": ORIGIN,
        "allowed_action_classes": ("click", "type"),
    }
    fields.update(overrides)
    return BrowserControlLeaseRequest(**fields)


def make_evidence(
    request: BrowserControlLeaseRequest,
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    evidence_expires_at: datetime | None = None,
    pause_expires_at: datetime | None = None,
    decision_id: str = "decision_3669",
) -> BrowserControlAuthorityEvidence:
    pause_expires = pause_expires_at or (NOW + timedelta(seconds=600))
    evidence_expires = evidence_expires_at or (NOW + timedelta(seconds=300))
    permission_request = LocalPermissionRequest(
        action_id="browser_control_session_1",
        run_id=request.run_ref,
        device_id=request.device_id,
        capability=request.capability,
        target_ref=request.target_ref(),
    )
    pause = ApprovalPause(
        pause_id="pause_3669",
        run_id=request.run_ref,
        agent_runtime_id="runtime_3669",
        tool_id=BROWSER_CONTROL_TOOL_ID,
        invocation_sha256=request.fingerprint(),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(seconds=5),
        expires_at=pause_expires,
        approval_scope=(BROWSER_CONTROL_TOOL_ID,),
    )
    decision = VerifiedApprovalDecision(
        decision_id=decision_id,
        pause_id="pause_3669",
        outcome=outcome,
        authority_ref="p01_authority.3669",
        evidence_ref="evidence.p01.3669",
        decided_at=NOW - timedelta(seconds=4),
    )
    return BrowserControlAuthorityEvidence(
        evidence_ref="evidence.p01.3669",
        request_fingerprint=request.fingerprint(),
        permission_request=permission_request,
        approval_pause=pause,
        approval_decision=decision,
        local_policy_ref="local:require_p01_approval",
        expires_at=evidence_expires,
    )


class AuthorityBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="claw-3669-authority-")
        self.path = os.path.join(self._tmp.name, "browser-control-leases.sqlite3")
        self.store = BrowserControlLeaseStore(self.path)
        self.profile = default_device_permission_profile(device=DEVICE)

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def make_authority(
        self,
        evidence: BrowserControlAuthorityEvidence | None = None,
        *,
        profile: DevicePermissionProfile | None = None,
    ) -> BrowserControlLeaseAuthority:
        port: DeterministicBrowserControlEvidencePort | None = None
        if evidence is not None:
            port = DeterministicBrowserControlEvidencePort((evidence,))
        return BrowserControlLeaseAuthority(
            device=DEVICE,
            permission_profile=profile or self.profile,
            store=self.store,
            evidence_port=port,
        )


class TestApprovedIssuance(AuthorityBase):
    def test_an_approved_p01_issues_the_durable_lease_exactly_once(self) -> None:
        request = make_request()
        evidence = make_evidence(request)
        authority = self.make_authority(evidence)
        projection, issued = authority.issue_from_p01(request, now=NOW)
        self.assertTrue(issued)
        self.assertEqual(projection.consumed_actions, 0)
        self.assertEqual(projection.max_actions, request.max_actions)
        self.assertEqual(projection.approval_ref, "p01_authority.3669")
        self.assertEqual(projection.evidence_ref, "evidence.p01.3669")
        # The second resolve is idempotent: same row, nothing re-minted, and the
        # evidence port is consulted exactly once for the whole session.
        port: DeterministicBrowserControlEvidencePort = authority._evidence_port  # noqa: SLF001
        second = authority.resolve_or_issue(request, now=NOW)
        self.assertEqual(second.lease_id, projection.lease_id)
        self.assertEqual(len(port.calls), 1)

    def test_the_expiry_is_capped_by_the_requested_ttl(self) -> None:
        request = make_request(ttl_seconds=120)
        evidence = make_evidence(request, evidence_expires_at=NOW + timedelta(seconds=600))
        authority = self.make_authority(evidence)
        projection, _ = authority.issue_from_p01(request, now=NOW)
        self.assertEqual(projection.expires_at, NOW + timedelta(seconds=120))

    def test_the_expiry_is_capped_by_the_pause_expiration(self) -> None:
        request = make_request(ttl_seconds=300)
        # The evidence can never outlive the P01 pause, so a tight pause bound
        # the lease even with a roomy requested TTL.
        tight = make_evidence(
            request,
            evidence_expires_at=NOW + timedelta(seconds=120),
            pause_expires_at=NOW + timedelta(seconds=120),
        )
        authority = self.make_authority(tight)
        projection, _ = authority.issue_from_p01(request, now=NOW)
        self.assertEqual(projection.expires_at, NOW + timedelta(seconds=120))

    def test_missing_evidence_fails_closed(self) -> None:
        authority = self.make_authority(evidence=None)
        request = make_request()
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "evidence_unavailable")

    def test_no_evidence_for_the_fingerprint_fails_closed(self) -> None:
        other = make_request(owner_ref="owner_other")
        foreign = make_evidence(other)  # binds a different session fingerprint
        authority = self.make_authority(foreign)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(make_request(), now=NOW)
        self.assertEqual(ctx.exception.code, "evidence_unavailable")


class TestP01DecisionMatrix(AuthorityBase):
    def test_a_denied_decision_refuses(self) -> None:
        request = make_request()
        evidence = make_evidence(request, outcome=ApprovalOutcome.DENIED)
        authority = self.make_authority(evidence)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "p01_approval_not_approved")

    def test_expired_evidence_refuses(self) -> None:
        request = make_request()
        evidence = make_evidence(request, evidence_expires_at=NOW - timedelta(seconds=1))
        authority = self.make_authority(evidence)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "p01_approval_expired")

    def test_a_pause_expired_now_refuses(self) -> None:
        request = make_request()
        # Evidence and pause both die together (evidence can never outlive the
        # pause); the pause expiry therefore surfaces through the same check.
        evidence = make_evidence(
            request,
            evidence_expires_at=NOW + timedelta(seconds=60),
            pause_expires_at=NOW + timedelta(seconds=60),
        )
        authority = self.make_authority(evidence)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW + timedelta(seconds=61))
        self.assertEqual(ctx.exception.code, "p01_approval_expired")


class TestCorrelationMatrix(AuthorityBase):
    def test_a_device_correlation_mismatch_refuses(self) -> None:
        authority = self.make_authority()
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(make_request(device_id="device_other"), now=NOW)
        self.assertEqual(ctx.exception.code, "lease_correlation_mismatch")

    def test_a_workspace_correlation_mismatch_refuses(self) -> None:
        authority = self.make_authority()
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(make_request(workspace_ref="workspace_other"), now=NOW)
        self.assertEqual(ctx.exception.code, "lease_correlation_mismatch")

    def test_an_unbound_evidence_fingerprint_refuses(self) -> None:
        # Evidence bound to a DIFFERENT session's fingerprint is not
        # retrievable under this session: the port keys evidence by the
        # fingerprint the authority asks for, so a foreign build does not
        # answer this session and the authority fails closed at the fetch —
        # the P01 material can never be redressed onto it.
        request = make_request(origin_scope="https://other.example")
        foreign = make_evidence(make_request())
        authority = self.make_authority(foreign)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "evidence_unavailable")
        self.assertIsNone(self.store.get(request.fingerprint()))

    def test_a_wrong_invocation_digest_refuses(self) -> None:
        request = make_request()
        evidence = make_evidence(request)
        drifted = BrowserControlAuthorityEvidence(
            evidence_ref=evidence.evidence_ref,
            request_fingerprint="d" * 64,
            permission_request=evidence.permission_request,
            approval_pause=ApprovalPause(
                pause_id=evidence.approval_pause.pause_id,
                run_id=request.run_ref,
                agent_runtime_id=evidence.approval_pause.agent_runtime_id,
                tool_id=BROWSER_CONTROL_TOOL_ID,
                invocation_sha256="d" * 64,
                requirement=ApprovalRequirement.USER_CONFIRMATION,
                step_index=1,
                created_at=NOW - timedelta(seconds=5),
                expires_at=evidence.approval_pause.expires_at,
                approval_scope=(BROWSER_CONTROL_TOOL_ID,),
            ),
            approval_decision=evidence.approval_decision,
            local_policy_ref=evidence.local_policy_ref,
            expires_at=evidence.expires_at,
        )
        authority = self.make_authority(drifted)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        # The drifted evidence is keyed under its own ("d"*64) fingerprint,
        # so this session's fetch finds no bound evidence at all — the closed
        # fetch-step refusal, and no row may land. The internal-digest
        # re-check is covered by the run-mismatch case, where the evidence
        # answers this session and then fails validation.
        self.assertEqual(ctx.exception.code, "evidence_unavailable")
        self.assertIsNone(self.store.get(request.fingerprint()))

    def test_a_run_mismatch_in_the_evidence_refuses(self) -> None:
        request = make_request()
        evidence = make_evidence(request)
        drifted = BrowserControlAuthorityEvidence(
            evidence_ref=evidence.evidence_ref,
            request_fingerprint=request.fingerprint(),
            permission_request=LocalPermissionRequest(
                action_id=evidence.permission_request.action_id,
                run_id="run_other",
                device_id=request.device_id,
                capability=request.capability,
                target_ref=request.target_ref(),
            ),
            approval_pause=ApprovalPause(
                pause_id=evidence.approval_pause.pause_id,
                run_id="run_other",
                agent_runtime_id=evidence.approval_pause.agent_runtime_id,
                tool_id=BROWSER_CONTROL_TOOL_ID,
                invocation_sha256=request.fingerprint(),
                requirement=ApprovalRequirement.USER_CONFIRMATION,
                step_index=1,
                created_at=NOW - timedelta(seconds=5),
                expires_at=evidence.approval_pause.expires_at,
                approval_scope=(BROWSER_CONTROL_TOOL_ID,),
            ),
            approval_decision=evidence.approval_decision,
            local_policy_ref=evidence.local_policy_ref,
            expires_at=evidence.expires_at,
        )
        authority = self.make_authority(drifted)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "p01_approval_invalid")

    def test_a_claimed_fingerprint_mismatch_refuses(self) -> None:
        request = make_request()
        authority = self.make_authority(make_evidence(request))
        projection = authority.resolve_or_issue(request, now=NOW)
        self.assertEqual(projection.consumed_actions, 0)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.resolve_or_issue(request, now=NOW, provided_fingerprint="d" * 64)
        self.assertEqual(ctx.exception.code, "lease_correlation_mismatch")

    def test_correlation_drift_on_an_existing_row_refuses(self) -> None:
        # A row under this fingerprint carrying a different owner is drift, not
        # a second session: PHASE A refuses instead of reissuing.
        request = make_request()
        store_issued = BrowserControlLeaseIssuance(
            request_fingerprint=request.fingerprint(),
            browser_session_ref=request.browser_session_ref,
            run_ref=request.run_ref,
            workspace_ref=request.workspace_ref,
            owner_ref="owner_other",
            allowed_action_classes=request.allowed_action_classes,
            origin_scope=request.origin_scope,
            max_actions=request.max_actions,
            issued_at=NOW,
            expires_at=NOW + timedelta(seconds=300),
            approval_ref="decision_3669",
            evidence_ref="evidence_3669",
        )
        self.store.issue_from_p01(store_issued)
        authority = self.make_authority(make_evidence(request))
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.resolve_or_issue(request, now=NOW)
        self.assertEqual(ctx.exception.code, "lease_correlation_mismatch")

    def test_capability_mismatch_is_refused_at_evidence_validation(self) -> None:
        # The validator itself refuses a non-browser-control permission record
        # and a non-browser.control pause tool — the P01 material is bound to
        # exactly one capability.
        request = make_request()
        evidence = make_evidence(request)
        with self.assertRaises(ContractError):
            BrowserControlAuthorityEvidence(
                evidence_ref=evidence.evidence_ref,
                request_fingerprint=request.fingerprint(),
                permission_request=LocalPermissionRequest(
                    action_id="browser_open_1",
                    run_id=request.run_ref,
                    device_id=request.device_id,
                    capability=LocalCapability.BROWSER_OPEN,
                    target_ref=request.target_ref(),
                ),
                approval_pause=evidence.approval_pause,
                approval_decision=evidence.approval_decision,
                local_policy_ref=evidence.local_policy_ref,
                expires_at=evidence.expires_at,
            )
        with self.assertRaises(ContractError):
            BrowserControlAuthorityEvidence(
                evidence_ref=evidence.evidence_ref,
                request_fingerprint=request.fingerprint(),
                permission_request=evidence.permission_request,
                approval_pause=ApprovalPause(
                    pause_id=evidence.approval_pause.pause_id,
                    run_id=request.run_ref,
                    agent_runtime_id=evidence.approval_pause.agent_runtime_id,
                    tool_id="browser.open",
                    invocation_sha256=request.fingerprint(),
                    requirement=ApprovalRequirement.USER_CONFIRMATION,
                    step_index=1,
                    created_at=NOW - timedelta(seconds=5),
                    expires_at=evidence.approval_pause.expires_at,
                    approval_scope=(BROWSER_CONTROL_TOOL_ID,),
                ),
                approval_decision=evidence.approval_decision,
                local_policy_ref=evidence.local_policy_ref,
                expires_at=evidence.expires_at,
            )


class TestLocalPolicy(AuthorityBase):
    def test_a_local_deny_wins_over_an_approved_decision(self) -> None:
        request = make_request()
        evidence = make_evidence(request)
        deny_rules = tuple(
            CapabilityRule(
                rule.capability,
                LocalPolicyMode.DENY
                if rule.capability is LocalCapability.BROWSER_CONTROL
                else rule.mode,
            )
            for rule in self.profile.global_rules
        )
        deny_profile = DevicePermissionProfile(
            device_id=self.profile.device_id,
            workspace_ref=self.profile.workspace_ref,
            roots=self.profile.roots,
            global_rules=deny_rules,
        )
        authority = self.make_authority(evidence, profile=deny_profile)
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            authority.issue_from_p01(request, now=NOW)
        self.assertEqual(ctx.exception.code, "local_policy_denied")

    def test_the_constructor_refuses_profile_device_drift(self) -> None:
        other_profile = default_device_permission_profile(
            device=LocalAgentDeviceProfile(
                device_id="device_other",
                workspace_ref="workspace_3669",
                platform=LocalAgentPlatform.WINDOWS,
                roots=DEVICE.roots,
            )
        )
        with self.assertRaises(ContractError):
            BrowserControlLeaseAuthority(
                device=DEVICE, permission_profile=other_profile, store=self.store
            )


class TestTwoPhaseDelegation(AuthorityBase):
    def test_the_two_phases_delegate_to_the_durable_store(self) -> None:
        request = make_request()
        authority = self.make_authority(make_evidence(request))
        projection = authority.resolve_or_issue(request, now=NOW)
        self.assertEqual(projection.consumed_actions, 0)
        consumed = authority.consume_action(
            projection.request_fingerprint,
            browser_session_ref=request.browser_session_ref,
            run_ref=request.run_ref,
            workspace_ref=request.workspace_ref,
            owner_ref=request.owner_ref,
            action="click",
            observed_origin=ORIGIN,
            now=NOW + timedelta(seconds=1),
        )
        self.assertEqual(consumed.consumed_actions, 1)
        revoked = authority.revoke_lease(projection.lease_id, reason="explicit", now=NOW + timedelta(seconds=2))
        self.assertEqual(revoked.revoke_reason, "explicit")
        self.assertEqual(authority.get(projection.request_fingerprint).revoked_at, revoked.revoked_at)


class TestLoopbackEvidenceClient(AuthorityBase):
    def _envelope(self, request: BrowserControlLeaseRequest, **overrides: Any) -> dict[str, Any]:
        pause_payload: dict[str, Any] = {
            "pause_id": "pause_3669",
            "run_id": request.run_ref,
            "agent_runtime_id": "runtime_3669",
            "tool_id": BROWSER_CONTROL_TOOL_ID,
            "invocation_sha256": request.fingerprint(),
            "requirement": "user_confirmation",
            "step_index": 1,
            "created_at": (NOW - timedelta(seconds=5)).isoformat(),
            "expires_at": (NOW + timedelta(seconds=600)).isoformat(),
            "approval_scope": [BROWSER_CONTROL_TOOL_ID],
        }
        decision_payload: dict[str, Any] = {
            "decision_id": "decision_3669",
            "pause_id": "pause_3669",
            "outcome": "approved",
            "authority_ref": "p01_authority.3669",
            "evidence_ref": "evidence.p01.3669",
            "decided_at": (NOW - timedelta(seconds=4)).isoformat(),
        }
        permission_payload: dict[str, Any] = {
            "action_id": "browser_control_session_1",
            "run_id": request.run_ref,
            "device_id": request.device_id,
            "capability": "browser.control",
            "target_ref": request.target_ref(),
        }
        envelope: dict[str, Any] = {
            "evidence_ref": "evidence.p01.3669",
            "request_fingerprint": request.fingerprint(),
            "approval_pause": pause_payload,
            "approval_decision": decision_payload,
            "permission_requests": [permission_payload],
            "local_policy_ref": "local:require_p01_approval",
            "expires_at": (NOW + timedelta(seconds=300)).isoformat(),
        }
        envelope.update(overrides)
        return envelope

    def test_the_client_reuses_the_existing_p01_route_without_a_run_precondition(self) -> None:
        request = make_request()
        bodies: list[dict[str, Any]] = []

        def opener(body: bytes) -> dict[str, Any]:
            parsed = json.loads(body)
            bodies.append(parsed)
            return {"envelope": self._envelope(request)}

        client = P01LoopbackBrowserControlEvidenceClient(
            base_url="", binding_ref="pairing-binding.3669", request_id="request.3669", opener=opener
        )
        evidence = client.resolve(request.fingerprint())
        self.assertEqual(evidence.approval_decision.outcome, ApprovalOutcome.APPROVED)
        self.assertIsNone(evidence.command_id)
        # The request body is the closed 4-key canonical envelope request.
        self.assertEqual(
            sorted(bodies[0]),
            ["binding_ref", "command_id", "request_fingerprint", "request_id"],
        )
        self.assertEqual(bodies[0]["request_fingerprint"], request.fingerprint())

    def test_the_client_copies_the_command_correlation_when_present(self) -> None:
        request = make_request()

        def opener(body: bytes) -> dict[str, Any]:
            return {"envelope": self._envelope(request, command_id="command.3669")}

        client = P01LoopbackBrowserControlEvidenceClient(
            base_url="", binding_ref="pairing-binding.3669", request_id="request.3669", opener=opener
        )
        evidence = client.resolve(request.fingerprint())
        self.assertEqual(evidence.command_id, "command.3669")

    def test_a_mismatched_envelope_fingerprint_refuses(self) -> None:
        request = make_request()
        client = P01LoopbackBrowserControlEvidenceClient(
            base_url="",
            binding_ref="pairing-binding.3669",
            request_id="request.3669",
            opener=lambda body: {"envelope": self._envelope(request, request_fingerprint="d" * 64)},
        )
        with self.assertRaises(ContractError):
            client.resolve(request.fingerprint())

    def test_no_boundary_configured_fails_closed(self) -> None:
        client = P01LoopbackBrowserControlEvidenceClient(
            base_url="", binding_ref="pairing-binding.3669", request_id="request.3669"
        )
        request = make_request()
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            client.resolve(request.fingerprint())
        self.assertEqual(ctx.exception.code, "evidence_unavailable")

    def test_the_loopback_client_end_to_end_issues_through_the_existing_route(self) -> None:
        request = make_request()
        client = P01LoopbackBrowserControlEvidenceClient(
            base_url="",
            binding_ref="pairing-binding.3669",
            request_id="request.3669",
            opener=lambda body: {"envelope": self._envelope(request)},
        )
        authority = BrowserControlLeaseAuthority(
            device=DEVICE, permission_profile=self.profile, store=self.store, evidence_port=client
        )
        projection, issued = authority.issue_from_p01(request, now=NOW)
        self.assertTrue(issued)
        self.assertEqual(projection.approval_ref, "p01_authority.3669")



class Test3778PerCommandP01Evidence(AuthorityBase):
    """The #3140 connection approval cannot silently become browser.control."""

    @staticmethod
    def correlation(request: BrowserControlLeaseRequest) -> BrowserControlP01CommandCorrelation:
        return BrowserControlP01CommandCorrelation(
            command_id="command.3778.browser.control",
            request_id="request.3778.browser.control",
            binding_ref="binding.3778.canonical",
            request_fingerprint=request.fingerprint(),
            run_ref=request.run_ref,
        )

    def envelope(self, request: BrowserControlLeaseRequest, **overrides: Any) -> dict[str, Any]:
        base = TestLoopbackEvidenceClient._envelope(None, request)
        base.update(
            command_id="command.3778.browser.control",
            request_id="request.3778.browser.control",
            binding_ref="binding.3778.canonical",
        )
        base.update(overrides)
        return base

    def test_pairing_command_and_request_sentinels_cannot_be_reused(self) -> None:
        req = make_request()
        for command_id, request_id in (
            ("command.3140.p01.1", "request.3778.browser.control"),
            ("command.3778.browser.control", "request.3140.p01.1"),
        ):
            with self.assertRaises(ContractError):
                BrowserControlP01CommandCorrelation(
                    command_id=command_id,
                    request_id=request_id,
                    binding_ref="binding.3778.canonical",
                    request_fingerprint=req.fingerprint(),
                    run_ref=req.run_ref,
                )

    def test_real_distinct_command_echo_and_p01_scope_issue_one_lease(self) -> None:
        req = make_request()
        bodies: list[dict[str, Any]] = []

        def opener(body: bytes) -> dict[str, Any]:
            bodies.append(json.loads(body))
            return {"envelope": self.envelope(req)}

        client = P01PerCommandBrowserControlEvidenceClient(
            correlation=self.correlation(req), base_url="", opener=opener,
        )
        authority = BrowserControlLeaseAuthority(
            device=DEVICE, permission_profile=self.profile, store=self.store,
            evidence_port=client,
        )
        lease, issued = authority.issue_from_p01(req, now=NOW)
        self.assertTrue(issued)
        self.assertEqual(lease.request_fingerprint, req.fingerprint())
        self.assertEqual(
            bodies,
            [{
                "command_id": "command.3778.browser.control",
                "request_id": "request.3778.browser.control",
                "binding_ref": "binding.3778.canonical",
                "request_fingerprint": req.fingerprint(),
            }],
        )

    def test_mismatched_command_request_binding_or_run_refuses_without_issuance(self) -> None:
        req = make_request()
        for change in (
            {"command_id": "command.other"},
            {"request_id": "request.other"},
            {"binding_ref": "binding.other"},
            {"request_fingerprint": "e" * 64},
        ):
            client = P01PerCommandBrowserControlEvidenceClient(
                correlation=self.correlation(req),
                base_url="",
                opener=lambda body, change=change: {
                    "envelope": self.envelope(req, **change)
                },
            )
            with self.assertRaises((BrowserControlLeaseRefusal, ContractError)):
                client.resolve(req.fingerprint())
        client = P01PerCommandBrowserControlEvidenceClient(
            correlation=self.correlation(req),
            base_url="",
            opener=lambda body: {"envelope": self.envelope(req, approval_pause={
                **self.envelope(req)["approval_pause"], "run_id": "other_run"
            })},
        )
        # The canonical P01 envelope validator may reject the mismatched run
        # even earlier than the stricter per-command adapter. Both fail closed.
        with self.assertRaises((BrowserControlLeaseRefusal, ContractError)):
            client.resolve(req.fingerprint())
        self.assertIsNone(self.store.get(req.fingerprint()))

    def test_a_different_requested_fingerprint_must_not_contact_broker(self) -> None:
        req = make_request()
        calls: list[bytes] = []
        client = P01PerCommandBrowserControlEvidenceClient(
            correlation=self.correlation(req), base_url="",
            opener=lambda body: calls.append(body) or {"envelope": self.envelope(req)},
        )
        with self.assertRaises(BrowserControlLeaseRefusal):
            client.resolve("b" * 64)
        self.assertEqual(calls, [])

    def test_resident_only_accepts_a_matching_per_command_correlation(self) -> None:
        from unittest.mock import patch
        from kagent.local_agent_resident_process import _browser_control_lease_authority
        req = make_request()
        correlation = self.correlation(req)
        with tempfile.TemporaryDirectory() as base:
            for match in (False, True):
                name = "match" if match else "mismatch"
                root = os.path.join(base, name)
                os.mkdir(root)
                with patch.dict(os.environ, {"PADIEM_AGENT_BROKER_URL": "http://127.0.0.1:1234"}):
                    authority = _browser_control_lease_authority(
                        device=DEVICE, credential_dir=root, root_source="env",
                        redeemed_device_binding_ref=(
                            correlation.binding_ref if match else "binding.other"
                        ),
                        approved_command_correlation=correlation,
                    )
                try:
                    self.assertIsInstance(
                        authority._evidence_port,
                        P01PerCommandBrowserControlEvidenceClient
                        if match else UnconfiguredBrowserControlEvidencePort,
                    )
                finally:
                    authority._store.close()

    def test_resident_pairing_factory_does_not_arm_browser_control(self) -> None:
        from unittest.mock import patch
        from kagent.local_agent_resident_process import _browser_control_lease_authority
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"PADIEM_AGENT_BROKER_URL": "http://127.0.0.1:1234"}):
                authority = _browser_control_lease_authority(
                    device=DEVICE, credential_dir=root, root_source="env",
                    redeemed_device_binding_ref="binding.3778.canonical",
                    approved_command_correlation=None,
                )
            self.assertIsInstance(
                authority._evidence_port, UnconfiguredBrowserControlEvidencePort
            )
            authority._store.close()



class TestModuleFacts(unittest.TestCase):
    def test_the_ruling_markers_are_declared_facts(self) -> None:
        self.assertEqual(NEW_APPROVAL_STORE, 0)
        self.assertEqual(NEW_DURABLE_LEASE_STORE, 1)
        self.assertFalse(DESKTOP_DURABLE_LEASE_AUTHORITY)
        self.assertFalse(DURABLE_RUN_STORE_TOUCHED)
        self.assertEqual(STEP_UP_EXECUTION, 0)
        self.assertFalse(LEASE_RENEWAL_SUPPORTED)
        self.assertFalse(AUTO_RECOVERY_REAUTHORIZE)
        self.assertEqual(RENDERER_LEASE_MINTING, 0)

    def test_the_canonical_refusal_vocabulary_is_the_union_of_both_closed_sets(self) -> None:
        self.assertEqual(CANONICAL_LEASE_REFUSAL_CODES, LEASE_REFUSAL_CODES + ISSUANCE_REFUSAL_CODES)
        self.assertEqual(len(set(CANONICAL_LEASE_REFUSAL_CODES)), len(CANONICAL_LEASE_REFUSAL_CODES))

    def test_the_unconfigured_port_refuses_with_the_closed_code(self) -> None:
        port = UnconfiguredBrowserControlEvidencePort()
        with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
            port.resolve("a" * 64)
        self.assertEqual(ctx.exception.code, "evidence_unavailable")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
