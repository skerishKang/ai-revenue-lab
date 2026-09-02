from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import (
    ClawRunStatus,
    ClawTaskIntent,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    RunProjection,
    SandboxLease,
    SandboxLeaseRequest,
)


class ClawContractTests(unittest.TestCase):
    def test_task_intent_has_no_provider_or_sandbox_endpoint_authority(self):
        intent = ClawTaskIntent(
            task_id="task_001",
            task="로그인 오류를 분석해줘",
            repository_ref="skerishKang/example",
            execution_mode=ExecutionMode.CLOUD,
            requested_revision="abc123",
            source_surface="padiem_chat",
            trace_id="trace_001",
        )
        rendered = intent.safe_dict()
        self.assertEqual(rendered["execution_mode"], "cloud")
        for forbidden in (
            "provider",
            "model",
            "credential",
            "api_key",
            "base_url",
            "sandbox_url",
            "sandbox_host",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_task_and_repository_projection_redact_accidental_secrets(self):
        intent = ClawTaskIntent(
            task_id="task_002",
            task="이 값을 노출하지 말아줘 token=supersecretvalue",
            repository_ref="OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890",
        )
        rendered = str(intent.safe_dict())
        self.assertNotIn("supersecretvalue", rendered)
        self.assertNotIn("abcdef1234567890", rendered)
        self.assertIn("REDACTED", rendered)

    def test_identifier_and_text_bounds_fail_closed(self):
        with self.assertRaises(ContractError):
            ClawTaskIntent(task_id="bad id", task="작업", repository_ref="repo")
        with self.assertRaises(ContractError):
            ClawTaskIntent(task_id="ok", task="", repository_ref="repo")
        with self.assertRaises(ContractError):
            ClawTaskIntent(task_id="ok", task="작업", repository_ref="repo\x00bad")
        with self.assertRaises(ContractError):
            ClawTaskIntent(task_id=123, task="작업", repository_ref="repo")  # type: ignore[arg-type]

    def test_enum_wire_values_are_normalized_and_unknown_values_fail_closed(self):
        intent = ClawTaskIntent(
            task_id="task_wire",
            task="클라우드 실행을 준비해줘",
            repository_ref="repo",
            execution_mode="cloud",  # type: ignore[arg-type]
        )
        self.assertIs(intent.execution_mode, ExecutionMode.CLOUD)
        request = SandboxLeaseRequest(
            run_id="run_wire",
            execution_mode="cloud",  # type: ignore[arg-type]
            repository_ref="repo",
            resource_class="small",  # type: ignore[arg-type]
            network_policy="restricted",  # type: ignore[arg-type]
        )
        self.assertIs(request.execution_mode, ExecutionMode.CLOUD)
        self.assertIs(request.resource_class, ResourceClass.SMALL)
        self.assertIs(request.network_policy, NetworkPolicy.RESTRICTED)
        with self.assertRaises(ContractError):
            ClawTaskIntent(
                task_id="task_bad_mode",
                task="작업",
                repository_ref="repo",
                execution_mode="remote-root",  # type: ignore[arg-type]
            )

    def test_sandbox_request_defaults_network_off_and_bounds_ttl(self):
        request = SandboxLeaseRequest(
            run_id="run_001",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
        )
        self.assertEqual(request.network_policy, NetworkPolicy.OFF)
        self.assertEqual(request.resource_class, ResourceClass.STANDARD)
        self.assertEqual(request.ttl_seconds, 900)
        self.assertNotIn("endpoint", request.safe_dict())
        with self.assertRaises(ContractError):
            SandboxLeaseRequest(
                run_id="run_002",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="repo",
                ttl_seconds=59,
            )
        with self.assertRaises(ContractError):
            SandboxLeaseRequest(
                run_id="run_003",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="repo",
                ttl_seconds=3601,
            )
        with self.assertRaises(ContractError):
            SandboxLeaseRequest(
                run_id="run_004",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="repo",
                ttl_seconds=True,  # type: ignore[arg-type]
            )
        with self.assertRaises(ContractError):
            SandboxLeaseRequest(
                run_id="run_005",
                execution_mode=ExecutionMode.CLOUD,
                repository_ref="repo",
                writable_workspace=1,  # type: ignore[arg-type]
            )

    def test_lease_requires_timezone_aware_ordered_times(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        lease = SandboxLease(
            lease_id="lease_001",
            run_id="run_001",
            execution_mode=ExecutionMode.CLOUD,
            resource_class=ResourceClass.SMALL,
            network_policy=NetworkPolicy.OFF,
            writable_workspace=True,
            created_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        self.assertEqual(lease.safe_dict()["state"], "reserved")
        with self.assertRaises(ContractError):
            SandboxLease(
                lease_id="lease_002",
                run_id="run_002",
                execution_mode=ExecutionMode.CLOUD,
                resource_class=ResourceClass.SMALL,
                network_policy=NetworkPolicy.OFF,
                writable_workspace=True,
                created_at=now.replace(tzinfo=None),
                expires_at=now + timedelta(minutes=5),
            )
        with self.assertRaises(ContractError):
            SandboxLease(
                lease_id="lease_003",
                run_id="run_003",
                execution_mode=ExecutionMode.CLOUD,
                resource_class=ResourceClass.SMALL,
                network_policy=NetworkPolicy.OFF,
                writable_workspace=True,
                created_at=now,
                expires_at=now,
            )

    def test_run_projection_is_safe_and_terminal_is_derived(self):
        projection = RunProjection(
            run_id="run_001",
            task_id="task_001",
            status=ClawRunStatus.COMPLETED,
            execution_mode=ExecutionMode.LOCAL,
            summary="완료 token=secretvalue123",
            changed_files=("src/a.py",),
        )
        rendered = projection.safe_dict()
        self.assertTrue(rendered["terminal"])
        self.assertNotIn("secretvalue123", str(rendered))
        for forbidden in ("provider", "model", "credential", "hidden_reasoning"):
            self.assertNotIn(forbidden, rendered)
        with self.assertRaises(ContractError):
            RunProjection(
                run_id="run_list",
                task_id="task_list",
                status="queued",  # type: ignore[arg-type]
                execution_mode="local",  # type: ignore[arg-type]
                changed_files=["src/a.py"],  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
