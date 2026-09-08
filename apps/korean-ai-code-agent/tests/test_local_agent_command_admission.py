from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import LocalCommandRequest
from kagent.local_agent_command_admission import (
    BROKER_WIRE_PROTOCOL_INVENTED,
    CLIENT_ADMISSION_AUTHORITY,
    COMMAND_EXPIRY_NOT_WIDENED,
    COMMAND_REQUEST_INTEGRITY_BINDING,
    PRODUCTION_READY,
    RAW_ARGV_IN_ADMISSION_EVIDENCE,
    REAL_REMOTE_BROKER_CONFIGURED,
    REPLAY_MODEL_DUPLICATED,
    REQUEST_FINGERPRINT_RECOMPUTED,
    SEQUENCE_EXACT,
    SESSION_BINDING_RUN_EXACT,
    TOOL_REQUEST_REF_EXACT,
    AdmittedLocalAgentExecutionBridge,
    DeterministicTrustedDeviceCommandAdmissionClient,
    TrustedDeviceCommandAdmissionEvidence,
)
from kagent.local_agent_pairing import DeviceCommandEnvelope, DeviceSession
from kagent.local_agent_runtime_assembly import LocalAgentRuntimeAssemblyReceipt
from kagent.windows_local_executor import WindowsExecutionTermination, command_request_fingerprint


class _StaticAdmissionClient:
    def __init__(self, value: object) -> None:
        self.value = value
        self.calls: list[tuple[str, str]] = []

    def resolve(self, *, command_id: str, request_fingerprint: str):
        self.calls.append((command_id, request_fingerprint))
        return self.value


class _FakeAssembly:
    def __init__(self, receipt: LocalAgentRuntimeAssemblyReceipt | object) -> None:
        self.receipt = receipt
        self.calls: list[tuple[str, str, datetime]] = []

    def execute(self, *, session: DeviceSession, request: LocalCommandRequest, now: datetime):
        self.calls.append((session.session_id, request.request_id, now))
        return self.receipt


def _fixture() -> tuple[
    datetime,
    DeviceSession,
    DeviceCommandEnvelope,
    LocalCommandRequest,
    TrustedDeviceCommandAdmissionEvidence,
    LocalAgentRuntimeAssemblyReceipt,
]:
    base = datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)
    session = DeviceSession(
        session_id="device_session_1",
        device_id="device_win_1",
        binding_ref="device_binding_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        issued_at=base,
        expires_at=base + timedelta(minutes=15),
    )
    command = DeviceCommandEnvelope(
        command_id="device_command_1",
        run_id="run_exec_1",
        tool_request_ref="tool_request_exec_1",
        binding_ref=session.binding_ref,
        sequence=7,
        issued_at=base + timedelta(seconds=30),
        expires_at=base + timedelta(minutes=10),
    )
    request = LocalCommandRequest(
        request_id="request_exec_1",
        run_id=command.run_id,
        device_id=session.device_id,
        root_ref="root_code",
        argv=(r"C:\Python311\python.exe", "-V"),
        cwd_relative=".",
        requested_at=base + timedelta(minutes=1),
        timeout_seconds=30,
    )
    fingerprint = command_request_fingerprint(request)
    evidence = TrustedDeviceCommandAdmissionEvidence(
        admission_ref="admission_exec_1",
        authority_ref="local_agent_broker_authority",
        command_id=command.command_id,
        session_id=session.session_id,
        binding_ref=session.binding_ref,
        run_id=command.run_id,
        tool_request_ref=command.tool_request_ref,
        sequence=command.sequence,
        request_fingerprint=fingerprint,
        accepted_at=base + timedelta(minutes=1),
        expires_at=base + timedelta(minutes=5),
    )
    assembly_receipt = LocalAgentRuntimeAssemblyReceipt(
        assembly_ref="local_assembly_1",
        binding_ref=session.binding_ref,
        session_id=session.session_id,
        request_id=request.request_id,
        run_id=request.run_id,
        device_id=request.device_id,
        workspace_ref=session.workspace_ref,
        root_ref=request.root_ref,
        request_fingerprint=fingerprint,
        termination=WindowsExecutionTermination.EXITED,
        executable_profile_ref="python311_profile",
        authorization_ref="windows_grant_1",
        started_at=base + timedelta(minutes=2),
        ended_at=base + timedelta(minutes=2, seconds=1),
        exit_code=0,
        dirty_worktree_before=False,
        dirty_worktree_after=False,
        stdout_chars=13,
        stderr_chars=0,
    )
    return base, session, command, request, evidence, assembly_receipt


class TrustedDeviceCommandAdmissionEvidenceTests(unittest.TestCase):
    def test_safe_projection_contains_no_raw_execution_or_secret_payload(self) -> None:
        _, _, _, _, evidence, _ = _fixture()
        safe = evidence.safe_dict()
        self.assertEqual(safe["contract_version"], "claw-trusted-device-command-admission.v1")
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["raw_file_content"])
        self.assertFalse(safe["raw_device_credential"])
        self.assertFalse(safe["broker_token"])
        self.assertFalse(safe["approval_payload"])
        self.assertFalse(safe["client_admission_authority"])
        self.assertNotIn("argv", safe)
        self.assertNotIn("file_content", safe)
        self.assertNotIn("credential", safe)
        self.assertNotIn("token", safe)

    def test_admission_evidence_lifetime_is_bounded(self) -> None:
        base, session, command, request, _, _ = _fixture()
        with self.assertRaisesRegex(ContractError, "900 seconds"):
            TrustedDeviceCommandAdmissionEvidence(
                admission_ref="admission_too_long",
                authority_ref="local_agent_broker_authority",
                command_id=command.command_id,
                session_id=session.session_id,
                binding_ref=session.binding_ref,
                run_id=command.run_id,
                tool_request_ref=command.tool_request_ref,
                sequence=command.sequence,
                request_fingerprint=command_request_fingerprint(request),
                accepted_at=base,
                expires_at=base + timedelta(minutes=16),
            )


class AdmittedLocalAgentExecutionBridgeTests(unittest.TestCase):
    def test_valid_admission_binds_exact_request_and_delegates_once(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        client = DeterministicTrustedDeviceCommandAdmissionClient((evidence,))
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref="local_agent_broker_authority",
            admission_client=client,
        )
        now = base + timedelta(minutes=2)
        receipt = bridge.execute(
            session=session,
            command=command,
            request=request,
            assembly=assembly,
            now=now,
        )
        fingerprint = command_request_fingerprint(request)
        self.assertEqual(client.calls, [(command.command_id, fingerprint)])
        self.assertEqual(assembly.calls, [(session.session_id, request.request_id, now)])
        self.assertEqual(receipt.admission_ref, evidence.admission_ref)
        self.assertEqual(receipt.request_fingerprint, fingerprint)
        self.assertEqual(receipt.assembly_ref, assembly_receipt.assembly_ref)
        self.assertEqual(receipt.authorization_ref, assembly_receipt.authorization_ref)
        safe = receipt.safe_dict()
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["stdout"])
        self.assertFalse(safe["stderr"])
        self.assertFalse(safe["raw_device_credential"])
        self.assertFalse(safe["broker_payload"])

    def test_changed_argv_recomputes_fingerprint_and_fails_before_execution(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        changed = LocalCommandRequest(
            request_id=request.request_id,
            run_id=request.run_id,
            device_id=request.device_id,
            root_ref=request.root_ref,
            argv=(request.argv[0], "-c", "print('changed')"),
            cwd_relative=request.cwd_relative,
            requested_at=request.requested_at,
            timeout_seconds=request.timeout_seconds,
        )
        client = DeterministicTrustedDeviceCommandAdmissionClient((evidence,))
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref="local_agent_broker_authority",
            admission_client=client,
        )
        with self.assertRaisesRegex(ContractError, "does not exist"):
            bridge.execute(
                session=session,
                command=command,
                request=changed,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(assembly.calls, [])

    def test_wrong_admission_authority_fails_closed(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        wrong = TrustedDeviceCommandAdmissionEvidence(
            admission_ref=evidence.admission_ref,
            authority_ref="different_broker_authority",
            command_id=evidence.command_id,
            session_id=evidence.session_id,
            binding_ref=evidence.binding_ref,
            run_id=evidence.run_id,
            tool_request_ref=evidence.tool_request_ref,
            sequence=evidence.sequence,
            request_fingerprint=evidence.request_fingerprint,
            accepted_at=evidence.accepted_at,
            expires_at=evidence.expires_at,
        )
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref="local_agent_broker_authority",
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((wrong,)),
        )
        with self.assertRaisesRegex(ContractError, "authority mismatch"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(assembly.calls, [])

    def test_session_binding_run_are_checked_before_admission_lookup(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        client = DeterministicTrustedDeviceCommandAdmissionClient((evidence,))
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref="local_agent_broker_authority",
            admission_client=client,
        )
        wrong_session = DeviceSession(
            session_id="device_session_2",
            device_id=session.device_id,
            binding_ref="device_binding_2",
            account_ref=session.account_ref,
            workspace_ref=session.workspace_ref,
            issued_at=session.issued_at,
            expires_at=session.expires_at,
        )
        with self.assertRaisesRegex(ContractError, "command binding"):
            bridge.execute(
                session=wrong_session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(client.calls, [])
        self.assertEqual(assembly.calls, [])

        wrong_run = LocalCommandRequest(
            request_id=request.request_id,
            run_id="run_other",
            device_id=request.device_id,
            root_ref=request.root_ref,
            argv=request.argv,
            cwd_relative=request.cwd_relative,
            requested_at=request.requested_at,
            timeout_seconds=request.timeout_seconds,
        )
        with self.assertRaisesRegex(ContractError, "command run"):
            bridge.execute(
                session=session,
                command=command,
                request=wrong_run,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(client.calls, [])

    def test_tool_request_and_sequence_mismatch_fail_before_assembly(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        wrong_tool = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_wrong_tool",
            authority_ref=evidence.authority_ref,
            command_id=evidence.command_id,
            session_id=evidence.session_id,
            binding_ref=evidence.binding_ref,
            run_id=evidence.run_id,
            tool_request_ref="tool_request_other",
            sequence=evidence.sequence,
            request_fingerprint=evidence.request_fingerprint,
            accepted_at=evidence.accepted_at,
            expires_at=evidence.expires_at,
        )
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((wrong_tool,)),
        )
        with self.assertRaisesRegex(ContractError, "tool_request_ref"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(assembly.calls, [])

        wrong_sequence = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_wrong_sequence",
            authority_ref=evidence.authority_ref,
            command_id=evidence.command_id,
            session_id=evidence.session_id,
            binding_ref=evidence.binding_ref,
            run_id=evidence.run_id,
            tool_request_ref=evidence.tool_request_ref,
            sequence=evidence.sequence + 1,
            request_fingerprint=evidence.request_fingerprint,
            accepted_at=evidence.accepted_at,
            expires_at=evidence.expires_at,
        )
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((wrong_sequence,)),
        )
        with self.assertRaisesRegex(ContractError, "sequence mismatch"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )

    def test_admission_cannot_predate_or_outlive_command(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        before = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_before",
            authority_ref=evidence.authority_ref,
            command_id=evidence.command_id,
            session_id=evidence.session_id,
            binding_ref=evidence.binding_ref,
            run_id=evidence.run_id,
            tool_request_ref=evidence.tool_request_ref,
            sequence=evidence.sequence,
            request_fingerprint=evidence.request_fingerprint,
            accepted_at=base,
            expires_at=base + timedelta(minutes=4),
        )
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((before,)),
        )
        with self.assertRaisesRegex(ContractError, "predate"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )

        after = TrustedDeviceCommandAdmissionEvidence(
            admission_ref="admission_after",
            authority_ref=evidence.authority_ref,
            command_id=evidence.command_id,
            session_id=evidence.session_id,
            binding_ref=evidence.binding_ref,
            run_id=evidence.run_id,
            tool_request_ref=evidence.tool_request_ref,
            sequence=evidence.sequence,
            request_fingerprint=evidence.request_fingerprint,
            accepted_at=base + timedelta(minutes=1),
            expires_at=base + timedelta(minutes=11),
        )
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((after,)),
        )
        with self.assertRaisesRegex(ContractError, "outlive"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )

    def test_expired_command_or_unconfigured_client_fail_closed(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((evidence,)),
        )
        with self.assertRaisesRegex(ContractError, "command is not currently valid"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=command.expires_at,
            )
        self.assertEqual(assembly.calls, [])

        unconfigured = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
        )
        with self.assertRaisesRegex(ContractError, "not configured"):
            unconfigured.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )

    def test_assembly_receipt_must_preserve_exact_correlation(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        bad_receipt = LocalAgentRuntimeAssemblyReceipt(
            assembly_ref=assembly_receipt.assembly_ref,
            binding_ref=assembly_receipt.binding_ref,
            session_id=assembly_receipt.session_id,
            request_id=assembly_receipt.request_id,
            run_id=assembly_receipt.run_id,
            device_id=assembly_receipt.device_id,
            workspace_ref=assembly_receipt.workspace_ref,
            root_ref=assembly_receipt.root_ref,
            request_fingerprint="e" * 64,
            termination=assembly_receipt.termination,
            executable_profile_ref=assembly_receipt.executable_profile_ref,
            authorization_ref=assembly_receipt.authorization_ref,
            started_at=assembly_receipt.started_at,
            ended_at=assembly_receipt.ended_at,
            exit_code=assembly_receipt.exit_code,
            dirty_worktree_before=assembly_receipt.dirty_worktree_before,
            dirty_worktree_after=assembly_receipt.dirty_worktree_after,
            stdout_chars=assembly_receipt.stdout_chars,
            stderr_chars=assembly_receipt.stderr_chars,
        )
        assembly = _FakeAssembly(bad_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=DeterministicTrustedDeviceCommandAdmissionClient((evidence,)),
        )
        with self.assertRaisesRegex(ContractError, "assembly receipt fingerprint"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )

    def test_invalid_admission_client_return_type_fails_closed(self) -> None:
        base, session, command, request, evidence, assembly_receipt = _fixture()
        assembly = _FakeAssembly(assembly_receipt)
        bridge = AdmittedLocalAgentExecutionBridge(
            expected_admission_authority_ref=evidence.authority_ref,
            admission_client=_StaticAdmissionClient(object()),
        )
        with self.assertRaisesRegex(ContractError, "invalid evidence"):
            bridge.execute(
                session=session,
                command=command,
                request=request,
                assembly=assembly,
                now=base + timedelta(minutes=2),
            )
        self.assertEqual(assembly.calls, [])

    def test_contract_flags_preserve_authority_boundaries(self) -> None:
        self.assertTrue(COMMAND_REQUEST_INTEGRITY_BINDING)
        self.assertTrue(REQUEST_FINGERPRINT_RECOMPUTED)
        self.assertTrue(SESSION_BINDING_RUN_EXACT)
        self.assertTrue(TOOL_REQUEST_REF_EXACT)
        self.assertTrue(SEQUENCE_EXACT)
        self.assertTrue(COMMAND_EXPIRY_NOT_WIDENED)
        self.assertFalse(REPLAY_MODEL_DUPLICATED)
        self.assertFalse(BROKER_WIRE_PROTOCOL_INVENTED)
        self.assertFalse(RAW_ARGV_IN_ADMISSION_EVIDENCE)
        self.assertFalse(CLIENT_ADMISSION_AUTHORITY)
        self.assertFalse(REAL_REMOTE_BROKER_CONFIGURED)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
