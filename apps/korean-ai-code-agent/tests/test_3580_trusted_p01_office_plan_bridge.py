"""#3580 exact P01 approval evidence into the REAL selected-root file port.

Uses synthetic local XLSX in a new temporary directory and canonical P01
ApprovalPause/VerifiedApprovalDecision; NO customer files, Drive or network.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement,
    VerifiedApprovalDecision, tool_invocation_digest,
)
from kagent.approved_windows_office_pair_producer import ApprovedWindowsOfficePairProducer
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    LocalPermissionRequest, default_device_permission_profile,
)
from kagent.local_agent_runtime_host import InMemorySingleInstanceLock
from kagent.trusted_p01_office_file_plan import (
    TrustedP01OfficeFilePlan, TrustedP01OfficeFilePlanBridge,
)
from kagent.windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, WindowsFileAuthorityEvidence,
    WindowsSelectedRootFileRuntime, P01LocalPermissionWindowsFileAuthorizationPort,
    file_request_fingerprint, windows_file_tool_invocation,
)
from test_3580_resident_office_post_ack_delivery import (
    XLSX, PDF, FakeExcel, _harness, staging,
)


class SyntheticTrustedP01Authority:
    """PRE-EXISTING P01 evidence fixture; bridge cannot manufacture approval."""

    def __init__(self, *, outcome=ApprovalOutcome.APPROVED, omit=False,
                 wrong_command=False, wrong_run=False, denied_scope=False,
                 expires_early=False):
        self.outcome = outcome
        self.omit = omit
        self.wrong_command = wrong_command
        self.wrong_run = wrong_run
        self.denied_scope = denied_scope
        self.expires_early = expires_early
        self.calls = 0
        self.last_args = None

    def approved_plan(self, *, binding, command, receipt):
        self.calls += 1
        self.last_args = dict(binding=binding, command=command, receipt=receipt)
        if self.omit:
            return None
        now = receipt.acknowledged_at
        req = LocalFileRequest(
            action_id="p01_approved_read_quote_3580",
            run_id="wrong_run" if self.wrong_run else command.run_id,
            device_id=binding.device_id, root_ref="root_repo",
            operation=LocalFileOperation.READ,
            path_relative=r"reports\quote.xlsx",
            requested_at=now - timedelta(seconds=30),
        )
        fp = file_request_fingerprint(req)
        invocation = windows_file_tool_invocation(req)
        pause = ApprovalPause(
            pause_id="pause_p01_office_quote_3580",
            run_id=req.run_id, agent_runtime_id="agent_p01_office_3580",
            tool_id=invocation.tool_id,
            invocation_sha256=tool_invocation_digest(invocation),
            requirement=ApprovalRequirement.USER_CONFIRMATION,
            step_index=1, created_at=now-timedelta(minutes=2),
            expires_at=now+timedelta(minutes=5),
            approval_scope=("filesystem.write",) if self.denied_scope else
                (req.capability.value,),
        )
        decision = VerifiedApprovalDecision(
            decision_id="decision_p01_office_3580",
            pause_id=pause.pause_id,
            outcome=self.outcome,
            authority_ref="trusted_p01_office_3580",
            evidence_ref="evidence_p01_office_3580",
            decided_at=now - timedelta(seconds=25),
        )
        evidence = WindowsFileAuthorityEvidence(
            evidence_ref="office_file_evidence_3580",
            request_fingerprint=fp,
            permission_request=LocalPermissionRequest(
                action_id="office_permission_3580",
                run_id=req.run_id,
                device_id=req.device_id,
                capability=req.capability,
                target_ref=fp,
                root_ref=req.root_ref,
            ),
            approval_pause=pause,
            approval_decision=decision,
            local_policy_ref="default_selected_root_policy_3580",
            expires_at=now - timedelta(minutes=6) if self.expires_early
                else now+timedelta(minutes=4),
        )
        return TrustedP01OfficeFilePlan(
            binding_ref=binding.binding_ref,
            command_id="other_command" if self.wrong_command else command.command_id,
            tool_request_ref=command.tool_request_ref,
            run_id=req.run_id,
            request_id=receipt.execution.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=receipt.execution.request_fingerprint,
            sequence=command.sequence,
            file_request=req,
            file_evidence=evidence,
        )


class RealP01OfficePlanBridgeTests(unittest.TestCase):
    def setUp(self):
        InMemorySingleInstanceLock.reset()
        self.temp = tempfile.TemporaryDirectory(prefix="padiem_p01_office_plan_test_")
        root = Path(self.temp.name)
        (root / "reports").mkdir(parents=True)
        (root / "reports" / "quote.xlsx").write_bytes(XLSX)
        self.device = LocalAgentDeviceProfile(
            device_id="dev_host_1", workspace_ref="ws_host_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(
                root_ref="root_repo",
                windows_path=str(root) if os.name == "nt" else r"C:\padiem\synthetic-office-root",
            ),),
        )

    def tearDown(self):
        self.temp.cleanup()
        InMemorySingleInstanceLock.reset()

    def wire(self, authority):
        host, runtime, port, clock = _harness()
        bridge = TrustedP01OfficeFilePlanBridge(source=authority)
        file_auth = P01LocalPermissionWindowsFileAuthorizationPort(
            permission_profile=default_device_permission_profile(device=self.device),
            evidence_port=bridge,
        )
        files = WindowsSelectedRootFileRuntime(
            device=self.device, authorization_port=file_auth,
        )
        renderer = FakeExcel()
        producer = ApprovedWindowsOfficePairProducer(
            files=files, requests=bridge, renderer=renderer, clock=clock,
        )
        stage, _, tls = staging(broker=port.broker_authority, pair=None)
        stage._approved_pairs = producer
        host._office_staging = stage
        host.start()
        clock.advance(5)
        try:
            executed = host.run_once(now=clock.now)
        finally:
            host.stop()
        return executed, bridge, authority, renderer, tls, port

    @unittest.skipUnless(__import__("os").name == "nt", "Windows selected-root real IO only")
    def test_preexisting_p01_decision_real_file_read_and_broker_after_ack(self):
        executed, bridge, authority, renderer, tls, port = self.wire(
            SyntheticTrustedP01Authority()
        )
        self.assertEqual(executed, 1)
        self.assertEqual(authority.calls, 1)
        self.assertEqual([part["kind"] for part in tls.calls], ["xlsx", "pdf"])
        self.assertEqual(tls.calls[0]["integrity_ref"], sha256(XLSX).hexdigest())
        self.assertEqual(tls.calls[1]["integrity_ref"], sha256(PDF).hexdigest())
        self.assertEqual(
            port.broker_authority._commands["cmd_host_1"].state.value, "acknowledged"
        )
        self.assertEqual(bridge.safe_dict()["pending_evidence_count"], 0)
        self.assertEqual(bridge.safe_dict()["approval_authority_created"], False)
        # Neither file evidence nor command approval can be replayed later.
        with self.assertRaises(ContractError):
            bridge.resolve("a"*64)
        with self.assertRaises(ContractError):
            bridge.request_for_completed_command(**authority.last_args)

    @unittest.skipUnless(__import__("os").name == "nt", "Windows selected-root real IO only")
    def test_denied_absent_or_foreign_p01_decisions_block_file_and_transfer(self):
        for options in (
            {"omit": True}, {"outcome": ApprovalOutcome.DENIED},
            {"wrong_command": True}, {"wrong_run": True},
            {"denied_scope": True}, {"expires_early": True},
        ):
            with self.subTest(options=options):
                executed, bridge, _, _, tls, port = self.wire(
                    SyntheticTrustedP01Authority(**options)
                )
                self.assertEqual(executed, 1)
                self.assertEqual(tls.calls, [])
                self.assertEqual(port.broker_authority._commands["cmd_host_1"].state.value,
                                 "acknowledged")
                InMemorySingleInstanceLock.reset()

    def test_actual_resident_builder_wires_existing_file_authority_not_new_approval(self):
        from kagent.local_agent_resident_process import (
            BrokerEntry, build_resident_host, redeem_handoff,
        )
        from test_local_agent_resident_process_3140 import (
            _SharedBroker, _ProtectedDataPort, _handoff,
            DEVICE_ID, AUTHORITY_REF, BASE,
        )
        broker = _SharedBroker()
        with tempfile.TemporaryDirectory(prefix="padiem_p01_host_3580_") as root:
            challenge_id, pairing_code = broker.web_issues()
            entry = BrokerEntry(
                device_id=DEVICE_ID, authority_ref=AUTHORITY_REF,
                request_port=broker, credential_dir=str(Path(root) / "credentials"),
            )
            redeemed = redeem_handoff(
                _handoff(challenge_id, pairing_code), entry=entry,
                base_dir=root, now=BASE+timedelta(seconds=1),
                protected_data=_ProtectedDataPort(),
            )
            source = SyntheticTrustedP01Authority(omit=True)
            host = build_resident_host(
                redeemed, entry=entry, office_p01_plan_source=source,
            )
            self.assertIsNotNone(host._office_staging)
            producer = host._office_staging._approved_pairs
            self.assertIsInstance(producer, ApprovedWindowsOfficePairProducer)
            self.assertIsInstance(
                producer._files._authorization,
                P01LocalPermissionWindowsFileAuthorizationPort,
            )
            self.assertIs(
                producer._requests,
                producer._files._authorization._evidence_port,
            )
            self.assertEqual(source.calls, 0)
            host.stop()
            host._durable_store.close()

    def test_bridge_rejects_unauthorized_query_and_missing_evidence(self):
        bridge = TrustedP01OfficeFilePlanBridge(source=SyntheticTrustedP01Authority())
        with self.assertRaises(ContractError):
            bridge.resolve("a"*64)
        self.assertEqual(bridge.safe_dict()["pending_evidence_count"], 0)


if __name__ == "__main__":
    unittest.main()
