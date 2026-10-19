"""#3580 Resident adapter: existing Broker ACK + canonical Engine P01 receipt.

Host evidence is synthetic in these contract tests only. The production source
must use authenticated one-shot server retrieval; no fake grant is shipped.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from kagent.contracts import ContractError
from kagent.verified_engine_office_read_plan_source import (
    VerifiedEngineOfficeReadPlanSource,
)
from kagent.windows_local_filesystem import (
    file_request_fingerprint, windows_file_tool_invocation,
)
from test_3580_trusted_p01_office_plan_bridge import (
    RealP01OfficePlanBridgeTests, SyntheticTrustedP01Authority,
)
from test_3580_resident_office_post_ack_delivery import XLSX, PDF


class _HostAuthenticatedEvidenceFixture:
    """Conformance-only lookup; deliberately NOT a production binding resolver."""

    def __init__(self, *, omit=False, tamper_file=False, foreign_binding=False,
                 stale=False, wrong_device=False):
        self.provider = SyntheticTrustedP01Authority()
        self.omit = omit
        self.tamper_file = tamper_file
        self.foreign_binding = foreign_binding
        self.stale = stale
        self.wrong_device = wrong_device
        self.calls = 0
        self.plan = None

    def trusted_binding(self, *, binding, command, receipt):
        self.plan = self.provider.approved_plan(
            binding=binding, command=command, receipt=receipt,
        )
        request = self.plan.file_request
        return SimpleNamespace(
            binding_ref=binding.binding_ref,
            command_id=command.command_id,
            tool_request_ref=command.tool_request_ref,
            run_id=command.run_id,
            request_id=receipt.execution.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=receipt.execution.request_fingerprint,
            sequence=command.sequence,
            device_id="other_device" if self.wrong_device else binding.device_id,
            root_ref=request.root_ref,
            request_fingerprint=file_request_fingerprint(request),
        )

    def redeem_for_trusted_command(self, binding):
        self.calls += 1
        if self.omit:
            return None
        assert self.plan is not None
        evidence = self.plan.file_evidence
        req = self.plan.file_request
        args = windows_file_tool_invocation(req).arguments_copy()
        if self.tamper_file:
            args["path_relative"] = "different.xlsx"
        decision = evidence.approval_decision
        if self.stale:
            decision = replace(decision, decided_at=decision.decided_at - timedelta(hours=1))
        receipt = SimpleNamespace(
            pause=evidence.approval_pause,
            verified_decision=decision,
            exact_tool_arguments=tuple(sorted(args.items())),
        )
        signed_binding = (
            SimpleNamespace(**{**vars(binding), "owner_id": "someone_else"})
            if self.foreign_binding else binding
        )
        return SimpleNamespace(binding=signed_binding, receipt=receipt)

    def source(self):
        return VerifiedEngineOfficeReadPlanSource(
            trusted_binding_resolver=self.trusted_binding,
            evidence_redeemer=self,
            local_policy_ref="selected_root_local_policy",
        )


class VerifiedReceiptResidentPlanTests(unittest.TestCase):
    """Reuses the shipping selected-root port and post-ACK Broker byte staging."""

    def setUp(self):
        self.harness = RealP01OfficePlanBridgeTests(
            methodName="test_bridge_rejects_unauthorized_query_and_missing_evidence"
        )
        self.harness.setUp()

    def tearDown(self):
        self.harness.tearDown()

    def wire(self, source):
        return self.harness.wire(source)

    @unittest.skipUnless(os.name == "nt", "real local IO requires Windows")
    def test_preexisting_engine_p01_receipt_goes_through_real_windows_port(self):
        trusted = _HostAuthenticatedEvidenceFixture()
        executed, bridge, source, renderer, tls, port = self.wire(trusted.source())
        self.assertEqual(executed, 1)
        self.assertEqual(trusted.calls, 1)
        self.assertEqual([piece["kind"] for piece in tls.calls], ["xlsx", "pdf"])
        self.assertEqual(tls.calls[0]["integrity_ref"], sha256(XLSX).hexdigest())
        self.assertEqual(tls.calls[1]["integrity_ref"], sha256(PDF).hexdigest())
        self.assertEqual(bridge.safe_dict()["pending_evidence_count"], 0)
        self.assertEqual(port.broker_authority._commands["cmd_host_1"].state.value,
                         "acknowledged")

    def test_cross_command_owner_and_tampered_invocation_emit_no_bytes(self):
        for options in (
            {"omit": True},
            {"tamper_file": True},
            {"foreign_binding": True},
            {"stale": True},
            {"wrong_device": True},
        ):
            with self.subTest(options=options):
                trusted = _HostAuthenticatedEvidenceFixture(**options)
                executed, bridge, source, renderer, tls, port = self.wire(trusted.source())
                self.assertEqual(executed, 1)
                self.assertEqual(tls.calls, [])
                if options.get("wrong_device"):
                    self.assertEqual(trusted.calls, 0)
                else:
                    self.assertEqual(trusted.calls, 1)

    def test_unconfigured_authenticated_transport_refused(self):
        with self.assertRaises(ContractError):
            VerifiedEngineOfficeReadPlanSource(
                trusted_binding_resolver=lambda **_: None,
                evidence_redeemer=None,
                local_policy_ref="selected_root_local_policy",
            )


if __name__ == "__main__":
    unittest.main()
