from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_admission import (
    REQUEST_MATERIAL_TIMING_AUTHORITY_DUPLICATED,
    AdmittedLocalAgentExecutionBridge,
    DeterministicTrustedDeviceCommandAdmissionClient,
    TrustedDeviceCommandAdmissionEvidence,
)
from kagent.local_agent_command_material import (
    OutboundCommandMaterialRequest,
    build_command_material_wire_projection,
    parse_command_material_wire_projection,
)
from kagent.local_agent_pairing import DeviceCommandEnvelope, DeviceSession
from kagent.local_agent_runtime_assembly import LocalAgentRuntimeAssemblyReceipt
from kagent.windows_local_executor import WindowsExecutionTermination, command_request_fingerprint


class _Assembly:
    def __init__(self, receipt: LocalAgentRuntimeAssemblyReceipt) -> None:
        self.receipt = receipt
        self.calls = 0

    def execute(self, *, session: DeviceSession, request: LocalCommandRequest, now: datetime):
        self.calls += 1
        return self.receipt


class MaterialAdmissionTimeOrderTests(unittest.TestCase):
    def _fixture(self):
        base = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        session = DeviceSession(
            session_id="session_time_1",
            device_id="device_time_1",
            binding_ref="binding_time_1",
            account_ref="account_time_1",
            workspace_ref="workspace_time_1",
            issued_at=base,
            expires_at=base + timedelta(minutes=15),
        )
        command = DeviceCommandEnvelope(
            command_id="command_time_1",
            run_id="run_time_1",
            tool_request_ref="tool_time_1",
            binding_ref=session.binding_ref,
            sequence=1,
            issued_at=base + timedelta(seconds=30),
            expires_at=base + timedelta(minutes=10),
        )
        request = LocalCommandRequest(
            request_id="request_time_1",
            run_id=command.run_id,
            device_id=session.device_id,
            root_ref="root_time_1",
            argv=(r"C:\\Python311\\python.exe", "-V"),
            cwd_relative=".",
            requested_at=base + timedelta(seconds=10),
            timeout_seconds=30,
        )
        return base, session, command, request

    def test_m2d_parser_owns_request_before_command_issuance_rule(self) -> None:
        base, session, command, request = self._fixture()
        fingerprint = command_request_fingerprint(request)
        wire = build_command_material_wire_projection(
            command=command,
            request=request,
            request_fingerprint=fingerprint,
        )
        outbound = OutboundCommandMaterialRequest(
            request_ref="material_resolution_time_1",
            session=session,
            command=command,
            request_fingerprint=fingerprint,
            requested_at=base + timedelta(seconds=40),
        )
        resolved = parse_command_material_wire_projection(wire, outbound_request=outbound)
        self.assertEqual(resolved.request, request)
        self.assertFalse(REQUEST_MATERIAL_TIMING_AUTHORITY_DUPLICATED)

        late = LocalCommandRequest(
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            root_ref=request.root_ref,
            argv=request.argv,
            cwd_relative=request.cwd_relative,
            requested_at=command.issued_at + timedelta(microseconds=1),
            timeout_seconds=request.timeout_seconds,
        )
        with self.assertRaisesRegex(ContractError, "before command issuance"):
            build_command_material_wire_projection(
                command=command,
                request=late,
                request_fingerprint=command_request_fingerprint(late),
            )

    def test_pre_issuance_material_passes_existing_admission_execution_bridge(self) -> None:
        base, session, command, request = self._fixture()
        fingerprint = command_request_fingerprint(request)
        evidence = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_time_1",
            authority_ref="broker_time_authority",
            command_id=command.command_id,
            session_id=session.session_id,
            binding_ref=session.binding_ref,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            sequence=command.sequence,
            request_fingerprint=fingerprint,
            accepted_at=base + timedelta(seconds=40),
            expires_at=base + timedelta(minutes=5),
        )
        assembly_receipt = LocalAgentRuntimeAssemblyReceipt(
            assembly_ref="assembly_time_1",
            binding_ref=session.binding_ref,
            session_id=session.session_id,
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            workspace_ref=session.workspace_ref,
            root_ref=request.root_ref,
            request_fingerprint=fingerprint,
            termination=WindowsExecutionTermination.EXITED,
            executable_profile_ref="python_time_profile",
            authorization_ref="authorization_time_1",
            started_at=base + timedelta(minutes=1),
            ended_at=base + timedelta(minutes=1, seconds=1),
            exit_code=0,
            dirty_worktree_before=False,
            dirty_worktree_after=False,
            stdout_chars=0,
            stderr_chars=0,
        )
        assembly = _Assembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((evidence,)),
        )
        receipt = bridge.execute(
            session=session,
            command=command,
            request=request,
            assembly=assembly,
            now=base + timedelta(minutes=1),
        )
        self.assertEqual(receipt.request_fingerprint, fingerprint)
        self.assertEqual(assembly.calls, 1)


if __name__ == "__main__":
    unittest.main()
