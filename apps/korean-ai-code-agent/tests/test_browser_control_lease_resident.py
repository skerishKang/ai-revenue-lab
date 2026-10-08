"""#3669 — the two bounded lease phases on the existing supervised resident pipe.

The claims under test:

1. the closed dispatcher grew from two to FOUR literal request kinds on the
   same single stdin reader — the two lease phases carry the trusted-composition
   session context only, and no second reader, no generic dispatch, no lease
   minting or consumption ever happens on the Desktop side;
2. the PHASE A / PHASE B answer lines are exact-closed: bounded correlation
   plus (A) the 14-key desktop lease shape, or (B) the new durable count — and a
   refusal carries one closed reason code, nothing the Desktop could launder.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any

from kagent.browser_control_lease_authority import (
    BROWSER_CONTROL_TOOL_ID,
    CANONICAL_LEASE_REFUSAL_CODES,
    BrowserControlLeaseAuthority,
    BrowserControlLeaseRequest,
    DeterministicBrowserControlEvidencePort,
)
from kagent.browser_control_lease_store import BrowserControlLeaseStore
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_desktop_material import (
    BROWSER_CONTROL_LEASE_TRANSPORT_KINDS_ADDED,
    DESKTOP_LEASE_CONSUMPTION,
    DESKTOP_LEASE_MINTING,
    LEASE_CONSUME_REQUEST_KIND,
    LEASE_RESPONSE_CONTRACT_VERSION,
    LEASE_RESPONSE_EVENT,
    LEASE_RESOLVE_REQUEST_KIND,
    LEASE_TRANSPORT_CARRIES_CREDENTIAL,
    LEASE_TRANSPORT_CARRIES_PAGE_CONTENT,
    LEASE_TRANSPORT_CARRIES_P01_PAYLOAD,
    MAX_DESKTOP_REQUEST_LINE_CHARS,
    ResidentDesktopMaterialResponder,
    lease_consume_response_line,
    lease_refusal_reason,
    lease_resolve_response_line,
    parse_desktop_request,
)
from kagent.local_agent_permissions import default_device_permission_profile
from kagent.contracts import ContractError

NOW = datetime.now(timezone.utc).replace(microsecond=0)
ORIGIN = "https://example.com"


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3669",
        workspace_ref="workspace_3669",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="root_work", windows_path=r"E:\work"),),
    )


def request(**overrides: Any) -> BrowserControlLeaseRequest:
    values: dict[str, Any] = {
        "browser_session_ref": "run/session-3669",
        "run_ref": "run_3669",
        "workspace_ref": "workspace_3669",
        "owner_ref": "owner_3669",
        "device_id": "device_3669",
        "origin_scope": ORIGIN,
        "allowed_action_classes": ("click", "type"),
    }
    values.update(overrides)
    return BrowserControlLeaseRequest(**values)


def evidence(item: BrowserControlLeaseRequest):
    from kagent.browser_control_lease_authority import BrowserControlAuthorityEvidence
    from kagent.local_agent_permissions import LocalPermissionRequest
    from padiem_ai_core.agent_approval import (
        ApprovalOutcome,
        ApprovalPause,
        ApprovalRequirement,
        VerifiedApprovalDecision,
    )

    pause = ApprovalPause(
        pause_id="pause_3669",
        run_id=item.run_ref,
        agent_runtime_id="runtime_3669",
        tool_id=BROWSER_CONTROL_TOOL_ID,
        invocation_sha256=item.approval_invocation_sha256(),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=600),
        approval_scope=(BROWSER_CONTROL_TOOL_ID,),
    )
    return BrowserControlAuthorityEvidence(
        evidence_ref="evidence.p01.3669",
        request_fingerprint=item.fingerprint(),
        permission_request=LocalPermissionRequest(
            action_id="browser_control_session_3669",
            run_id=item.run_ref,
            device_id=item.device_id,
            capability=item.capability,
            target_ref=item.target_ref(),
        ),
        approval_pause=pause,
        approval_decision=VerifiedApprovalDecision(
            decision_id="decision_3669",
            pause_id="pause_3669",
            outcome=ApprovalOutcome.APPROVED,
            authority_ref="p01_authority.3669",
            evidence_ref="evidence.p01.3669",
            decided_at=NOW - timedelta(seconds=4),
        ),
        local_policy_ref="local:require_p01_approval",
        expires_at=NOW + timedelta(seconds=300),
    )


def lease_resolve_request_line(item: BrowserControlLeaseRequest, **overrides: Any) -> str:
    fields: dict[str, Any] = {
        "contract_version": "claw-browser-control-lease-request.v1",
        "request": LEASE_RESOLVE_REQUEST_KIND,
        "requestFingerprint": item.fingerprint(),
        "browserSessionRef": item.browser_session_ref,
        "deviceRef": item.device_id,
        "runRef": item.run_ref,
        "workspaceRef": item.workspace_ref,
        "ownerRef": item.owner_ref,
        "originScope": item.origin_scope,
        "allowedActionClasses": list(item.allowed_action_classes),
        "ttlSeconds": item.ttl_seconds,
        "maxActions": item.max_actions,
    }
    fields.update(overrides)
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def lease_consume_request_line(item: BrowserControlLeaseRequest, **overrides: Any) -> str:
    fields: dict[str, Any] = {
        "contract_version": "claw-browser-control-lease-request.v1",
        "request": LEASE_CONSUME_REQUEST_KIND,
        "requestFingerprint": item.fingerprint(),
        "browserSessionRef": item.browser_session_ref,
        "runRef": item.run_ref,
        "workspaceRef": item.workspace_ref,
        "ownerRef": item.owner_ref,
        "action": "click",
        "observedOrigin": item.origin_scope,
    }
    fields.update(overrides)
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def lease_callables(authority: BrowserControlLeaseAuthority):
    """The exact PHASE A / PHASE B closures the resident composition wires."""

    def lease_resolve(**payload: Any) -> dict[str, Any]:
        item = BrowserControlLeaseRequest(
            browser_session_ref=payload["browser_session_ref"],
            run_ref=payload["run_ref"],
            workspace_ref=payload["workspace_ref"],
            owner_ref=payload["owner_ref"],
            device_id=payload["device_ref"],
            origin_scope=payload["origin_scope"],
            allowed_action_classes=tuple(payload["allowed_action_classes"]),
            ttl_seconds=payload["ttl_seconds"],
            max_actions=payload["max_actions"],
        )
        projection = authority.resolve_or_issue(
            item,
            now=datetime.now(timezone.utc).replace(microsecond=0),
            provided_fingerprint=payload["request_fingerprint"],
        )
        return projection.wire_lease_dict()

    def lease_consume(**payload: Any) -> int:
        projection = authority.consume_action(
            payload["request_fingerprint"],
            browser_session_ref=payload["browser_session_ref"],
            run_ref=payload["run_ref"],
            workspace_ref=payload["workspace_ref"],
            owner_ref=payload["owner_ref"],
            action=payload["action"],
            observed_origin=payload["observed_origin"],
            now=datetime.now(timezone.utc).replace(microsecond=0),
        )
        return int(projection.consumed_actions)

    return lease_resolve, lease_consume


class ResidentLeaseHarness:
    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="claw-3669-resident-")
        item = request()
        store = BrowserControlLeaseStore(os.path.join(self._tmp.name, "leases.sqlite3"))
        self.authority = BrowserControlLeaseAuthority(
            device=device(),
            permission_profile=default_device_permission_profile(device=device()),
            store=store,
            evidence_port=DeterministicBrowserControlEvidencePort((evidence(item),)),
        )
        self.store = store
        self.item = item
        self.request_fp = item.fingerprint()

    def close(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def responder(self, *, configured: bool = True) -> ResidentDesktopMaterialResponder:
        if configured:
            resolve, consume = lease_callables(self.authority)
        else:
            resolve = consume = None
        return ResidentDesktopMaterialResponder(
            material_projection=lambda: {"ok": True},
            lease_resolve=resolve,
            lease_consume=consume,
            reader=None,
            emit=lambda line: None,
        )


# --- the closed request shapes -------------------------------------------------


class LeaseRequestParsingTests(unittest.TestCase):
    def test_the_resolve_request_parses_to_its_closed_field_set(self) -> None:
        item = request()
        parsed = parse_desktop_request(lease_resolve_request_line(item))
        self.assertEqual(parsed["kind"], LEASE_RESOLVE_REQUEST_KIND)
        self.assertEqual(
            sorted(parsed["payload"]),
            sorted(
                [
                    "requestFingerprint",
                    "browserSessionRef",
                    "deviceRef",
                    "runRef",
                    "workspaceRef",
                    "ownerRef",
                    "originScope",
                    "allowedActionClasses",
                    "ttlSeconds",
                    "maxActions",
                ]
            ),
        )

    def test_the_consume_request_parses_to_its_closed_field_set(self) -> None:
        item = request()
        parsed = parse_desktop_request(lease_consume_request_line(item))
        self.assertEqual(parsed["kind"], LEASE_CONSUME_REQUEST_KIND)
        self.assertEqual(
            sorted(parsed["payload"]),
            sorted(
                [
                    "requestFingerprint",
                    "browserSessionRef",
                    "runRef",
                    "workspaceRef",
                    "ownerRef",
                    "action",
                    "observedOrigin",
                ]
            ),
        )

    def test_an_unknown_field_is_refused(self) -> None:
        item = request()
        raw = json.loads(lease_resolve_request_line(item))
        raw["rawUrl"] = "https://example.com"
        with self.assertRaises(ContractError):
            parse_desktop_request(json.dumps(raw))

    def test_a_wrong_contract_version_is_refused(self) -> None:
        item = request()
        raw = json.loads(lease_resolve_request_line(item))
        raw["contract_version"] = "claw-browser-control-lease-request.v0"
        with self.assertRaises(ContractError):
            parse_desktop_request(json.dumps(raw))

    def test_a_non_canonical_fingerprint_is_refused(self) -> None:
        item = request()
        # Non-hex, too short, and missing hex digits are all refused. Note the
        # fingerprint check lowercases before matching, so case is not a refusal
        # reason — character set and length are.
        for bad in ("g" * 64, item.fingerprint()[:63], "0" * 32):
            with self.assertRaises(ContractError, msg=bad):
                parse_desktop_request(lease_resolve_request_line(item, requestFingerprint=bad))

    def test_the_request_line_stays_within_the_dispatcher_bound(self) -> None:
        item = request()
        self.assertLessEqual(len(lease_resolve_request_line(item)), MAX_DESKTOP_REQUEST_LINE_CHARS)
        self.assertLessEqual(len(lease_consume_request_line(item)), MAX_DESKTOP_REQUEST_LINE_CHARS)


# --- the closed answer lines ---------------------------------------------------


class LeaseResponseLineTests(unittest.TestCase):
    def test_the_resolve_answer_carries_exactly_the_closed_keys(self) -> None:
        item = request()
        lease = {
            "leaseId": "lease_x",
            "requestFingerprint": item.fingerprint(),
            "browserSessionRef": item.browser_session_ref,
            "runRef": item.run_ref,
            "workspaceRef": item.workspace_ref,
            "ownerRef": item.owner_ref,
            "allowedActionClasses": ["click", "type"],
            "originScope": item.origin_scope,
            "maxActions": 25,
            "issuedAtIso": NOW.isoformat().replace("+00:00", "Z"),
            "expiresAtIso": (NOW + timedelta(seconds=300)).isoformat().replace("+00:00", "Z"),
            "approvalRef": "decision_3669",
            "evidenceRef": "evidence_3669",
        }
        parsed = json.loads(
            lease_resolve_response_line(
                request_fingerprint=item.fingerprint(), ok=True, reason=None, lease=lease
            )
        )
        self.assertEqual(
            set(parsed),
            {"event", "contract_version", "request", "ok", "request_fingerprint", "reason", "lease"},
        )
        self.assertEqual(parsed["event"], LEASE_RESPONSE_EVENT)
        self.assertEqual(parsed["contract_version"], LEASE_RESPONSE_CONTRACT_VERSION)
        self.assertEqual(set(lease), set(parsed["lease"]))

    def test_a_refused_resolve_may_not_carry_a_lease(self) -> None:
        item = request()
        with self.assertRaises(ContractError):
            lease_resolve_response_line(
                request_fingerprint=item.fingerprint(),
                ok=False,
                reason="lease_unknown",
                lease={"leaseId": "x"},
            )

    def test_the_consume_answer_carries_exactly_the_closed_keys(self) -> None:
        item = request()
        parsed = json.loads(
            lease_consume_response_line(
                request_fingerprint=item.fingerprint(), ok=True, reason=None, consumed_actions=1
            )
        )
        self.assertEqual(
            set(parsed),
            {"event", "contract_version", "request", "ok", "request_fingerprint", "reason", "consumed_actions"},
        )
        self.assertEqual(parsed["consumed_actions"], 1)

    def test_a_refused_consume_may_not_carry_a_count(self) -> None:
        item = request()
        with self.assertRaises(ContractError):
            lease_consume_response_line(
                request_fingerprint=item.fingerprint(),
                ok=False,
                reason="action_budget_exhausted",
                consumed_actions=0,
            )

    def test_the_refusal_reason_maps_the_closed_vocabulary(self) -> None:
        for code in CANONICAL_LEASE_REFUSAL_CODES:

            class Dummy(Exception):
                def __init__(self) -> None:
                    super().__init__(code)
                    self.code = code

            self.assertEqual(lease_refusal_reason(Dummy()), code)
        self.assertEqual(lease_refusal_reason(RuntimeError("no closed code")), "lease_refused")


# --- the two phases end to end on the responder ---------------------------------


class ResidentLeasePhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ResidentLeaseHarness()

    def tearDown(self) -> None:
        self.harness.close()

    def test_phase_a_returns_the_bounded_lease_shape_read_only(self) -> None:
        responder = self.harness.responder()
        line = responder.respond(lease_resolve_request_line(self.harness.item))
        parsed = json.loads(line)
        self.assertIs(parsed["ok"], True)
        self.assertIsNone(parsed["reason"])
        self.assertEqual(set(parsed["lease"]), self._wire_keys())
        self.assertEqual(parsed["lease"]["requestFingerprint"], self.harness.request_fp)
        # PHASE A is read-only: no slot has been consumed.
        self.assertEqual(self.harness.store.get(self.harness.request_fp).consumed_actions, 0)

    def _issue(self, responder: ResidentDesktopMaterialResponder) -> None:
        """PHASE A first, exactly as the host flow runs: the row is lazily
        materialised on the resolve, before any PHASE B consume may land."""

        parsed = json.loads(responder.respond(lease_resolve_request_line(self.harness.item)))
        self.assertIs(parsed["ok"], True)

    def test_phase_b_consumes_exactly_one_durable_slot(self) -> None:
        responder = self.harness.responder()
        self._issue(responder)
        first = json.loads(responder.respond(lease_consume_request_line(self.harness.item)))
        self.assertIs(first["ok"], True)
        self.assertEqual(first["consumed_actions"], 1)
        second = json.loads(responder.respond(lease_consume_request_line(self.harness.item)))
        self.assertIs(second["ok"], True)
        self.assertEqual(second["consumed_actions"], 2)

    def test_phase_b_refusal_carries_the_closed_code_only(self) -> None:
        responder = self.harness.responder()
        self._issue(responder)
        raw = lease_consume_request_line(self.harness.item, runRef="run_other")
        parsed = json.loads(responder.respond(raw))
        self.assertIs(parsed["ok"], False)
        self.assertEqual(parsed["reason"], "lease_correlation_mismatch")
        self.assertIsNone(parsed["consumed_actions"])

    def test_a_cross_origin_consume_revokes_and_the_revoke_persists(self) -> None:
        responder = self.harness.responder()
        self._issue(responder)
        raw = lease_consume_request_line(self.harness.item, observedOrigin="https://other.example")
        parsed = json.loads(responder.respond(raw))
        self.assertEqual(parsed["reason"], "origin_scope_exceeded")
        # The same session's next resolve is durably refused after the revoke.
        followup = json.loads(responder.respond(lease_resolve_request_line(self.harness.item)))
        self.assertIs(followup["ok"], False)
        self.assertEqual(followup["reason"], "lease_revoked")
        self.assertEqual(
            self.harness.store.get(self.harness.request_fp).revoke_reason, "cross_origin"
        )

    def test_an_unconfigured_responder_fails_closed(self) -> None:
        responder = self.harness.responder(configured=False)
        for line in (
            lease_resolve_request_line(self.harness.item),
            lease_consume_request_line(self.harness.item),
        ):
            parsed = json.loads(responder.respond(line))
            self.assertIs(parsed["ok"], False)
            self.assertEqual(parsed["reason"], "lease_unavailable")

    def _wire_keys(self) -> set[str]:
        return {
            "leaseId",
            "requestFingerprint",
            "browserSessionRef",
            "runRef",
            "workspaceRef",
            "ownerRef",
            "allowedActionClasses",
            "originScope",
            "maxActions",
            "issuedAtIso",
            "expiresAtIso",
            "approvalRef",
            "evidenceRef",
        }


# --- the Desktop never crosses into lease authority ----------------------------


class DesktopLeaseBoundaryTests(unittest.TestCase):
    def test_the_two_kinds_were_added_and_nothing_else(self) -> None:
        self.assertEqual(BROWSER_CONTROL_LEASE_TRANSPORT_KINDS_ADDED, 2)
        self.assertFalse(LEASE_TRANSPORT_CARRIES_P01_PAYLOAD)
        self.assertFalse(LEASE_TRANSPORT_CARRIES_CREDENTIAL)
        self.assertFalse(LEASE_TRANSPORT_CARRIES_PAGE_CONTENT)
        self.assertEqual(DESKTOP_LEASE_MINTING, 0)
        self.assertEqual(DESKTOP_LEASE_CONSUMPTION, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
