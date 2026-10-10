"""Focused real Windows candidate-only local discovery, never reads workbook bytes."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement,
    VerifiedApprovalDecision, tool_invocation_digest,
)
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule, DevicePermissionProfile, LocalCapability, LocalPermissionRequest,
    LocalPolicyMode, RootPermissionPolicy, default_device_permission_profile,
)
from kagent.windows_local_filesystem import (
    DeterministicWindowsFileAuthorityEvidencePort, LocalFileOperation,
    WindowsFileAuthorityEvidence, DIRECTORY_ENUMERATION_SUPPORTED,
)
from kagent.windows_selected_root_quote_discovery import (
    MAX_DISCOVERY_SCANNED_ENTRIES, QuoteDiscoveryRequest,
    P01ApprovedSelectedRootQuoteDiscovery, quote_discovery_fingerprint,
    quote_discovery_tool_invocation,
)

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def request(*, root_ref="quotes", max_candidates=40, name_contains=""):
    return QuoteDiscoveryRequest(
        action_id="list_action_3580", run_id="run_quote_3580",
        device_id="dev_quote_3580", root_ref=root_ref,
        requested_at=NOW - timedelta(minutes=1),
        max_candidates=max_candidates, name_contains=name_contains,
    )


def approved_evidence(req, *, outcome=ApprovalOutcome.APPROVED, wrong_scope=False,
                      wrong_fingerprint=False, expired=False, wrong_tool=False):
    digest = quote_discovery_fingerprint(req)
    invocation = quote_discovery_tool_invocation(req)
    pause = ApprovalPause(
        pause_id="pause_list_quote_3580", run_id=req.run_id,
        agent_runtime_id="agent_list_quote_3580",
        tool_id="local.filesystem.read" if wrong_tool else invocation.tool_id,
        invocation_sha256=tool_invocation_digest(invocation),
        requirement=ApprovalRequirement.USER_CONFIRMATION, step_index=1,
        created_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=10),
        approval_scope=("process.execute",) if wrong_scope
                       else (LocalCapability.FILESYSTEM_READ.value,),
    )
    decision = VerifiedApprovalDecision(
        decision_id="decision_list_quote_3580", pause_id=pause.pause_id,
        outcome=outcome, authority_ref="trusted_engine_p01_test",
        evidence_ref="evidence_list_quote_3580",
        decided_at=NOW - timedelta(seconds=40),
    )
    return WindowsFileAuthorityEvidence(
        evidence_ref="evidence_list_quote_3580",
        request_fingerprint="a"*64 if wrong_fingerprint else digest,
        permission_request=LocalPermissionRequest(
            action_id="permission_list_quote_3580", run_id=req.run_id,
            device_id=req.device_id, capability=LocalCapability.FILESYSTEM_READ,
            target_ref=digest, root_ref=req.root_ref,
        ),
        approval_pause=pause, approval_decision=decision,
        local_policy_ref="local_quote_read_policy_3580",
        expires_at=NOW - timedelta(minutes=1) if expired else NOW + timedelta(minutes=5),
    )


class SelectedRootQuoteDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="padiem_quote_candidate_test_")
        self.root = Path(self.temp.name)
        # On Linux test the non-I/O contract with a valid synthetic Windows path.
        root_path = str(self.root) if os.name == "nt" else r"C:\synthetic\quote_root"
        self.device = LocalAgentDeviceProfile(
            device_id="dev_quote_3580", workspace_ref="ws_quote_3580",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="quotes", windows_path=root_path),),
        )
        self.policy = default_device_permission_profile(device=self.device)

    def tearDown(self):
        self.temp.cleanup()

    def runtime(self, req, evidence=None, *, profile=None):
        return P01ApprovedSelectedRootQuoteDiscovery(
            device=self.device, permission_profile=profile or self.policy,
            evidence_port=DeterministicWindowsFileAuthorityEvidencePort(
                (evidence or approved_evidence(req),),
            ),
        )

    def test_request_exact_fingerprint_includes_boundaries_and_limits(self):
        req = request()
        self.assertNotEqual(
            quote_discovery_fingerprint(req),
            quote_discovery_fingerprint(request(max_candidates=1)),
        )
        self.assertNotEqual(
            quote_discovery_fingerprint(req),
            quote_discovery_fingerprint(request(root_ref="other")),
        )
        self.assertNotEqual(
            quote_discovery_fingerprint(req),
            quote_discovery_fingerprint(replace(req, run_id="foreign")),
        )
        self.assertEqual(quote_discovery_tool_invocation(req).tool_id,
                         "local.filesystem.list.quote-candidates")
        self.assertNotEqual(quote_discovery_fingerprint(req),
                            quote_discovery_fingerprint(request(name_contains="견적서")))
        self.assertFalse(DIRECTORY_ENUMERATION_SUPPORTED)  # no change to standard READ

    def test_wrong_or_unbounded_requests_refused(self):
        for limit in (0, -1, 41, True, "40"):
            with self.subTest(limit=limit):
                with self.assertRaises(ContractError):
                    request(max_candidates=limit)
        with self.assertRaises(ContractError):
            request(root_ref="../secrets")
        with self.assertRaises(ContractError):
            request(name_contains="../private")
        with self.assertRaises(ContractError):
            self.runtime(request()).discover(request(), now=NOW.replace(tzinfo=None))

    @unittest.skipUnless(os.name == "nt", "Windows selected-root-only metadata")
    def test_metadata_candidates_are_nonrecursive_and_never_read_file_content(self):
        (self.root / "quote.xlsx").write_bytes(b"PK\x03\x04xyz")
        (self.root / "legacy.xls").write_bytes(b"OLE2-METADATA")
        (self.root / "plain.txt").write_bytes(b"NO")
        (self.root / "~$temporary.xlsx").write_bytes(b"tmp")
        (self.root / "oversize.xlsx").write_bytes(b"Z" * (1024 * 1024 + 1))
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "invisible.xlsx").write_bytes(b"hidden")
        req = request()
        result = self.runtime(req).discover(req, now=NOW)
        self.assertEqual([c.filename for c in result.candidates],
                         ["legacy.xls", "quote.xlsx"])
        self.assertEqual([c.kind for c in result.candidates], ["xls", "xlsx"])
        self.assertEqual(result.matching_count, 2)
        self.assertFalse(result.limited)
        public = result.public_projection()
        self.assertFalse(public["content_read"])
        self.assertFalse(public["read_authorized"])
        self.assertTrue(public["requires_separate_p01_read"])
        self.assertEqual(public["root_ref"], "quotes")
        self.assertEqual([x["size_bytes"] for x in public["candidates"]], [13, 7])

        filtered = self.runtime(request(name_contains="legacy")).discover(
            request(name_contains="legacy"), now=NOW,
        )
        self.assertEqual([c.filename for c in filtered.candidates], ["legacy.xls"])
        selected = result.candidates[-1]
        read = result.create_read_intent(
            candidate_ref=selected.candidate_ref, action_id="new_p01_read_3580",
            requested_at=NOW,
        )
        self.assertEqual(read.operation, LocalFileOperation.READ)
        self.assertEqual(read.path_relative, "quote.xlsx")
        self.assertEqual(read.content, None)
        self.assertEqual(read.run_id, req.run_id)
        with self.assertRaises(ContractError):
            result.create_read_intent(
                candidate_ref="a"*64, action_id="unlisted", requested_at=NOW,
            )

    @unittest.skipUnless(os.name == "nt", "Windows selected-root-only metadata")
    def test_independent_p01_approval_required_and_one_shot(self):
        (self.root / "quote.xlsx").write_bytes(b"test")
        req = request()
        runtime = self.runtime(req)
        self.assertEqual(len(runtime.discover(req, now=NOW).candidates), 1)
        with self.assertRaisesRegex(ContractError, "consumed"):
            runtime.discover(req, now=NOW)
        for options in (
            {"outcome": ApprovalOutcome.DENIED},
            {"expired": True},
            {"wrong_scope": True},
            {"wrong_fingerprint": True},
            {"wrong_tool": True},
        ):
            with self.subTest(options=options):
                rejected = self.runtime(req, approved_evidence(req, **options))
                with self.assertRaises(ContractError):
                    rejected.discover(req, now=NOW)

    @unittest.skipUnless(os.name == "nt", "Windows selected-root-only metadata")
    def test_policy_denial_does_not_list_and_outside_root_ref_refused(self):
        (self.root / "quote.xlsx").write_bytes(b"test")
        req = request()
        global_rules = self.policy.global_rules
        roots = (
            RootPermissionPolicy("quotes", (
                CapabilityRule(LocalCapability.FILESYSTEM_READ, LocalPolicyMode.DENY),
            )),
        )
        profile = DevicePermissionProfile(
            device_id=self.device.device_id,
            workspace_ref=self.device.workspace_ref,
            roots=roots, global_rules=global_rules,
        )
        with self.assertRaisesRegex(ContractError, "policy denied"):
            self.runtime(req, profile=profile).discover(req, now=NOW)
        with self.assertRaises(ContractError):
            self.runtime(req).discover(request(root_ref="other"), now=NOW)

    @unittest.skipUnless(os.name == "nt", "Windows selected-root-only metadata")
    def test_symlink_and_reparse_candidates_are_not_listed(self):
        (self.root / "real.xlsx").write_bytes(b"x")
        outside = Path(self.temp.name).parent / ("padiem_quote_outside_" + self.root.name + ".xlsx")
        outside.write_bytes(b"SECRET-METADATA")
        try:
            try:
                (self.root / "fake.xlsx").symlink_to(outside)
            except OSError:
                self.skipTest("Windows developer mode does not permit symlinks")
            req = request()
            found = self.runtime(req).discover(req, now=NOW)
            self.assertEqual([c.filename for c in found.candidates], ["real.xlsx"])
        finally:
            outside.unlink(missing_ok=True)

    def test_missing_evidence_never_reads_selected_root(self):
        req = request()
        runtime = P01ApprovedSelectedRootQuoteDiscovery(
            device=self.device, permission_profile=self.policy,
        )
        with self.assertRaises(ContractError):
            runtime.discover(req, now=NOW)


if __name__ == "__main__":
    unittest.main()
