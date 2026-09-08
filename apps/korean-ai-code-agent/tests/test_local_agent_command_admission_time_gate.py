from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_admission import (
    AdmittedLocalAgentExecutionBridge,
    DeterministicTrustedDeviceCommandAdmissionClient,
    TrustedDeviceCommandAdmissionEvidence,
)
from kagent.local_agent_pairing import DeviceCommandEnvelope, DeviceSession
from kagent.local_agent_runtime_assembly import LocalAgentRuntimeAssemblyReceipt
from kagent.windows_local_executor import WindowsExecutionTermination, command_request_fingerprint


class _FakeAssembly:
    def __init__(self, receipt: LocalAgentRuntimeAssemblyReceipt) -> None:
        self.receipt = receipt
        self.calls: list[str] = []

    def execute(self, *, session: DeviceSession, request: LocalCommandRequest, now: datetime):
        self.calls.append(request.request_id)
        return self.receipt


def _session(base: datetime) -> DeviceSession:
    return DeviceSession(
        session_id="device_session_time_1",
        device_id="device_win_time_1",
        binding_ref="device_binding_time_1",
        account_ref="account_time_1",
        workspace_ref="workspace_time_1",
        issued_at=base,
        expires_at=base + timedelta(minutes=15),
    )


def _command(base: datetime, session: DeviceSession) -> DeviceCommandEnvelope:
    return DeviceCommandEnvelope(
        command_id="device_command_time_1",
        run_id="run_time_1",
        tool_request_ref="tool_request_time_1",
        binding_ref=session.binding_ref,
        sequence=3,
        issued_at=base + timedelta(minutes=1),
        expires_at=base + timedelta(minutes=10),
    )


def _request(command: DeviceCommandEnvelope, session: DeviceSession, requested_at: datetime) -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id="request_time_1",
        run_id=command.run_id,
        device_id=session.device_id,
        root_ref="root_code",
        argv=(r"C:\Python311\python.exe", "-V"),
        cwd_relative=".",
        requested_at=requested_at,
        timeout_seconds=30,
    )


def _receipt(request: LocalCommandRequest, session: DeviceSession, base: datetime) -> LocalAgentRuntimeAssemblyReceipt:
    return LocalAgentRuntimeAssemblyReceipt(
        assembly_ref="local_assembly_time_1",
        binding_ref=session.binding_ref,
        session_id=session.session_id,
        request_id=request.request_id,
        run_id=request.run_id,
        device_id=request.device_id,
        workspace_ref=session.workspace_ref,
        root_ref=request.root_ref,
        request_fingerprint=command_request_fingerprint(request),
        termination=WindowsExecutionTermination.EXITED,
        executable_profile_ref="python311_profile",
        authorization_ref="windows_grant_time_1",
        started_at=base + timedelta(minutes=3),
        ended_at=base + timedelta(minutes=3, seconds=1),
        exit_code=0,
        dirty_worktree_before=False,
        dirty_worktree_after=False,
        stdout_chars=0,
        stderr_chars=0,
    )


class CommandMaterializationTimeGateTests(unittest.TestCase):
    def test_request_command_issuance_order_is_not_duplicated_in_execution_bridge(self) -> None:
        base = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        session = _session(base)
        command = _command(base, session)
        request = _request(command, session, base + timedelta(seconds=30))
        fingerprint = command_request_fingerprint(request)
        evidence = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_time_preissued_1",
            authority_ref="broker_authority_time",
            command_id=command.command_id,
            session_id=session.session_id,
            binding_ref=session.binding_ref,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            sequence=command.sequence,
            request_fingerprint=fingerprint,
            accepted_at=base + timedelta(minutes=1, seconds=30),
            expires_at=base + timedelta(minutes=5),
        )
        assembly = _FakeAssembly(_receipt(request, session, base))
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((evidence,)),
        )
        receipt = bridge.execute(
            session=session,
            command=command,
            request=request,
            assembly=assembly,
            now=base + timedelta(minutes=3),
        )
        self.assertEqual(receipt.request_fingerprint, fingerprint)
        self.assertEqual(assembly.calls, [request.request_id])

    def test_request_cannot_be_future_or_at_command_expiry(self) -> None:
        base = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        session = _session(base)
        command = _command(base, session)
        for requested_at, now in (
            (base + timedelta(minutes=4), base + timedelta(minutes=3)),
            (command.expires_at, base + timedelta(minutes=3)),
        ):
            request = _request(command, session, requested_at)
            assembly = _FakeAssembly(_receipt(request, session, base))
            bridge = AdmittedLocalAgentExecutionBridge(
                expected_admission_authority_ref="broker_authority_time",
            )
            with self.assertRaisesRegex(ContractError, "outside the current command lifetime"):
                bridge.execute(
                    session=session,
                    command=command,
                    request=request,
                    assembly=assembly,
                    now=now,
                )
            self.assertEqual(assembly.calls, [])

    def test_admission_cannot_predate_request_materialization(self) -> None:
        base = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)
        session = _session(base)
        command = _command(base, session)
        request = _request(command, session, base + timedelta(minutes=2))
        fingerprint = command_request_fingerprint(request)
        evidence = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_time_1",
            authority_ref="broker_authority_time",
            command_id=command.command_id,
            session_id=session.session_id,
            binding_ref=session.binding_ref,
            run_id=command.run_id,
            tool_request_ref=command.tool_request_ref,
            sequence=command.sequence,
            request_fingerprint=fingerprint,
            accepted_at=base + timedelta(minutes=1, seconds=30),
            expires_at=base + timedelta(minutes=5),
        )
        assembly = _FakeAssembly(_receipt(request, session, base))
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((evidence,)),
        )
        with self.assertRaisesRegex(ContractError, "predate local request materialization"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=3),
            )
        self.assertEqual(assembly.calls, [])


if __name__ == "__main__":
    unittest.main()
