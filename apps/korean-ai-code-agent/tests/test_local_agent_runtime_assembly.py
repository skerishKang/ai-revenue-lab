from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
import unittest

from kagent.contracts import ContractError
from kagent.local_agent import (
    LocalAgentDeviceProfile,
    LocalAgentPlatform,
    LocalCommandRequest,
    LocalCommandResult,
    LocalRoot,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_permissions import default_device_permission_profile, revoke_root
from kagent.local_agent_runtime_assembly import (
    BROKER_WIRE_PROTOCOL_INVENTED,
    ONE_LOCAL_AGENT_RUNTIME_ASSEMBLY,
    PRODUCTION_READY,
    RAW_ARGV_IN_ASSEMBLY_RECEIPT,
    RAW_CREDENTIAL_IN_ASSEMBLY_RECEIPT,
    RAW_STDOUT_STDERR_IN_ASSEMBLY_RECEIPT,
    REAL_REMOTE_BROKER_CONFIGURED,
    REAL_REMOTE_CONTROL_CONFIGURED,
    REPLAY_MODEL_DUPLICATED,
    BoundLocalAgentRuntimeAssembly,
)
from kagent.local_agent_secure_channel import PinnedOutboundBrokerBinding
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.windows_local_executor import WindowsExecutionReceipt, WindowsExecutionTermination

NOW = datetime(2026, 9, 3, 8, 45, tzinfo=timezone.utc)


def device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_1",
        workspace_ref="workspace_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(
            LocalRoot(root_ref="root_code", windows_path=r"E:\padiem-claw"),
            LocalRoot(root_ref="root_work", windows_path=r"G:\Ddrive\BatangD\task"),
        ),
    )


def binding(*, state: DeviceLifecycle = DeviceLifecycle.ONLINE, generation: int = 1) -> DeviceBinding:
    return DeviceBinding(
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential_ref=f"device-credential:generation-{generation}",
        credential_generation=generation,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=state,
    )


def session(*, account_ref: str = "account_1", session_id: str = "session_1") -> DeviceSession:
    return DeviceSession(
        session_id=session_id,
        device_id="device_1",
        binding_ref="device-binding:one",
        account_ref=account_ref,
        workspace_ref="workspace_1",
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def request(*, request_id: str = "request_1", device_id: str = "device_1", root_ref: str = "root_code") -> LocalCommandRequest:
    return LocalCommandRequest(
        request_id=request_id,
        run_id="run_1",
        device_id=device_id,
        root_ref=root_ref,
        argv=(r"C:\Python313\python.exe", "-V"),
        cwd_relative=".",
        requested_at=NOW - timedelta(seconds=1),
        timeout_seconds=30,
    )


def pinned(current: DeviceBinding) -> PinnedOutboundBrokerBinding:
    config = OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_primary",
            url="https://broker.padiem.example/v1/local-agent",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        )
    )
    return PinnedOutboundBrokerBinding.from_binding(binding=current, config=config)


class DeterministicReceiptRuntime:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.cancelled: list[str] = []

    def execute_with_receipt(self, item: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.executed.append(item.request_id)
        return WindowsExecutionReceipt(
            result=LocalCommandResult(
                request_id=item.request_id,
                run_id=item.run_id,
                device_id=item.device_id,
                root_ref=item.root_ref,
                started_at=now,
                ended_at=now + timedelta(milliseconds=1),
                exit_code=0,
                stdout="Python 3.13.0",
                stderr="",
                cancelled=False,
                dirty_worktree_before=True,
                dirty_worktree_after=True,
            ),
            termination=WindowsExecutionTermination.EXITED,
            executable_profile_ref="python_profile",
            authorization_ref="windows_grant_1",
        )

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)


class BlockingReceiptRuntime:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.was_cancelled = False
        self.cancelled: list[str] = []

    def execute_with_receipt(self, item: LocalCommandRequest, *, now: datetime) -> WindowsExecutionReceipt:
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test runtime was not released")
        cancelled = self.was_cancelled
        return WindowsExecutionReceipt(
            result=LocalCommandResult(
                request_id=item.request_id,
                run_id=item.run_id,
                device_id=item.device_id,
                root_ref=item.root_ref,
                started_at=now,
                ended_at=now + timedelta(milliseconds=1),
                exit_code=None if cancelled else 0,
                stdout="",
                stderr="cancelled" if cancelled else "",
                cancelled=cancelled,
                dirty_worktree_before=False,
                dirty_worktree_after=False,
            ),
            termination=WindowsExecutionTermination.CANCELLED if cancelled else WindowsExecutionTermination.EXITED,
            executable_profile_ref="python_profile",
            authorization_ref="windows_grant_1",
        )

    def cancel(self, request_id: str) -> None:
        self.cancelled.append(request_id)
        self.was_cancelled = True
        self.release.set()


class RuntimeAssemblyFixture(unittest.TestCase):
    def assembly(self, *, current_binding: DeviceBinding | None = None, runtime=None):
        current_binding = current_binding or binding()
        current_device = device()
        permissions = default_device_permission_profile(device=current_device)
        runtime = runtime or DeterministicReceiptRuntime()
        return BoundLocalAgentRuntimeAssembly(
            device=current_device,
            binding=current_binding,
            permissions=permissions,
            broker_authority=pinned(current_binding),
            runtime=runtime,
        ), runtime


class RuntimeAssemblyTests(RuntimeAssemblyFixture):
    def test_execute_reuses_runtime_and_returns_bounded_correlation_receipt(self):
        assembly, runtime = self.assembly()
        receipt = assembly.execute(session=session(), request=request(), now=NOW)
        self.assertEqual(runtime.executed, ["request_1"])
        rendered = receipt.safe_dict()
        self.assertEqual(rendered["binding_ref"], "device-binding:one")
        self.assertEqual(rendered["session_id"], "session_1")
        self.assertEqual(rendered["request_id"], "request_1")
        self.assertEqual(rendered["run_id"], "run_1")
        self.assertEqual(rendered["termination"], "exited")
        self.assertEqual(rendered["authorization_ref"], "windows_grant_1")
        self.assertEqual(rendered["stdout_chars"], len("Python 3.13.0"))
        self.assertFalse(rendered["raw_argv"])
        self.assertFalse(rendered["stdout"])
        self.assertFalse(rendered["stderr"])
        self.assertFalse(rendered["raw_device_credential"])
        self.assertFalse(rendered["broker_payload"])
        self.assertFalse(rendered["client_execution_authority"])

    def test_wrong_session_and_wrong_request_device_fail_before_runtime(self):
        assembly, runtime = self.assembly()
        with self.assertRaises(ContractError):
            assembly.execute(session=session(account_ref="account_other"), request=request(), now=NOW)
        with self.assertRaises(ContractError):
            assembly.execute(session=session(), request=request(device_id="device_other"), now=NOW)
        self.assertEqual(runtime.executed, [])

    def test_revoked_expired_and_update_required_binding_fail_closed(self):
        for state in (
            DeviceLifecycle.REVOKED,
            DeviceLifecycle.CREDENTIAL_EXPIRED,
            DeviceLifecycle.UPDATE_REQUIRED,
            DeviceLifecycle.UNPAIRED,
        ):
            with self.subTest(state=state):
                assembly, runtime = self.assembly(current_binding=binding(state=state))
                with self.assertRaises(ContractError):
                    assembly.execute(session=session(), request=request(), now=NOW)
                self.assertEqual(runtime.executed, [])

    def test_stale_pinned_generation_is_rejected_at_assembly_construction(self):
        current = binding(generation=2)
        with self.assertRaises(ContractError):
            BoundLocalAgentRuntimeAssembly(
                device=device(),
                binding=current,
                permissions=default_device_permission_profile(device=device()),
                broker_authority=pinned(binding(generation=1)),
                runtime=DeterministicReceiptRuntime(),
            )

    def test_permission_roots_must_exactly_match_selected_device_roots(self):
        current_device = device()
        permissions = default_device_permission_profile(device=current_device)
        narrowed = revoke_root(permissions, root_ref="root_work")
        with self.assertRaises(ContractError):
            BoundLocalAgentRuntimeAssembly(
                device=current_device,
                binding=binding(),
                permissions=narrowed,
                broker_authority=pinned(binding()),
                runtime=DeterministicReceiptRuntime(),
            )

    def test_future_request_is_refused_before_runtime(self):
        assembly, runtime = self.assembly()
        future = replace(request(), requested_at=NOW + timedelta(seconds=1))
        with self.assertRaises(ContractError):
            assembly.execute(session=session(), request=future, now=NOW)
        self.assertEqual(runtime.executed, [])

    def test_safe_projection_preserves_nonclaims(self):
        assembly, _ = self.assembly()
        rendered = assembly.safe_dict(now=NOW)
        self.assertTrue(rendered["current"])
        self.assertTrue(rendered["p01_authorization_reused"])
        self.assertTrue(rendered["windows_executor_reused"])
        self.assertFalse(rendered["broker_wire_protocol_defined"])
        self.assertFalse(rendered["replay_model_duplicated"])
        self.assertFalse(rendered["raw_device_credential"])
        self.assertFalse(rendered["client_execution_authority"])
        self.assertFalse(rendered["real_remote_broker"])
        self.assertFalse(rendered["production_ready"])

    def test_cancel_delegates_only_for_request_owned_by_exact_session(self):
        runtime = BlockingReceiptRuntime()
        assembly, _ = self.assembly(runtime=runtime)
        result: list[object] = []
        failure: list[BaseException] = []

        def run() -> None:
            try:
                result.append(assembly.execute(session=session(), request=request(), now=NOW))
            except BaseException as exc:  # test thread must surface failures
                failure.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(runtime.started.wait(timeout=3))
        with self.assertRaises(ContractError):
            assembly.cancel(session=session(session_id="session_other"), request_id="request_1", now=NOW)
        self.assertEqual(runtime.cancelled, [])
        assembly.cancel(session=session(), request_id="request_1", now=NOW)
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failure, [])
        self.assertEqual(runtime.cancelled, ["request_1"])
        self.assertEqual(result[0].termination, WindowsExecutionTermination.CANCELLED)
        with self.assertRaises(ContractError):
            assembly.cancel(session=session(), request_id="request_1", now=NOW)


class RepositoryTruthTests(unittest.TestCase):
    def test_nonclaims_are_explicit(self):
        self.assertTrue(ONE_LOCAL_AGENT_RUNTIME_ASSEMBLY)
        self.assertFalse(BROKER_WIRE_PROTOCOL_INVENTED)
        self.assertFalse(REPLAY_MODEL_DUPLICATED)
        self.assertFalse(RAW_CREDENTIAL_IN_ASSEMBLY_RECEIPT)
        self.assertFalse(RAW_ARGV_IN_ASSEMBLY_RECEIPT)
        self.assertFalse(RAW_STDOUT_STDERR_IN_ASSEMBLY_RECEIPT)
        self.assertFalse(REAL_REMOTE_BROKER_CONFIGURED)
        self.assertFalse(REAL_REMOTE_CONTROL_CONFIGURED)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
