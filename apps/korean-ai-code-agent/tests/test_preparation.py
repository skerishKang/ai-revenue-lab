from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import (
    ClawRunStatus,
    ClawTaskIntent,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
)
from kagent.preparation import CloudWorkspacePreparer, WorkspacePolicy
from kagent.runs import ClawRun, RunStateError
from kagent.sandbox import (
    DeterministicFakeSandboxProvider,
    SandboxUnavailableError,
    UnconfiguredSandboxProvider,
)


class CloudWorkspacePreparationTests(unittest.TestCase):
    def cloud_run(self, run_id: str = "run_001") -> ClawRun:
        intent = ClawTaskIntent(
            task_id=f"task_{run_id}",
            task="로그인 오류를 수정해줘",
            repository_ref="skerishKang/example",
            requested_revision="abc123",
            execution_mode=ExecutionMode.CLOUD,
        )
        return ClawRun.create(run_id, intent)

    def test_successful_lease_does_not_claim_agent_is_running(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        preparer = CloudWorkspacePreparer(provider)
        run = self.cloud_run()
        lease = preparer.prepare(run)
        self.assertEqual(run.status, ClawRunStatus.PREPARING)
        self.assertEqual(lease.run_id, run.run_id)
        self.assertEqual(lease.network_policy, NetworkPolicy.OFF)
        self.assertNotEqual(run.status, ClawRunStatus.RUNNING)

    def test_unconfigured_cloud_provider_marks_run_failed_and_re_raises(self):
        run = self.cloud_run()
        preparer = CloudWorkspacePreparer(UnconfiguredSandboxProvider())
        with self.assertRaises(SandboxUnavailableError):
            preparer.prepare(run)
        self.assertEqual(run.status, ClawRunStatus.FAILED)
        self.assertTrue(run.terminal)
        self.assertIn("실행하지 않았습니다", run.summary)

    def test_local_run_cannot_enter_cloud_preparation(self):
        intent = ClawTaskIntent(
            task_id="task_local",
            task="로컬 저장소를 분석해줘",
            repository_ref=".",
            execution_mode=ExecutionMode.LOCAL,
        )
        run = ClawRun.create("run_local", intent)
        provider = DeterministicFakeSandboxProvider()
        with self.assertRaises(RunStateError):
            CloudWorkspacePreparer(provider).prepare(run)
        self.assertEqual(run.status, ClawRunStatus.QUEUED)

    def test_workspace_policy_is_server_owned_and_bounded_by_contract(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        policy = WorkspacePolicy(
            resource_class=ResourceClass.SMALL,
            ttl_seconds=120,
            network_policy=NetworkPolicy.RESTRICTED,
            writable_workspace=False,
        )
        run = self.cloud_run("run_policy")
        lease = CloudWorkspacePreparer(provider, policy=policy).prepare(run)
        self.assertEqual(lease.resource_class, ResourceClass.SMALL)
        self.assertEqual(lease.network_policy, NetworkPolicy.RESTRICTED)
        self.assertFalse(lease.writable_workspace)
        self.assertEqual((lease.expires_at - lease.created_at).total_seconds(), 120)

    def test_reprepare_after_run_advances_is_rejected(self):
        now = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        run = self.cloud_run("run_advanced")
        preparer = CloudWorkspacePreparer(provider)
        lease = preparer.prepare(run)
        provider.release(lease.lease_id, run_id=run.run_id)
        run.transition(ClawRunStatus.RUNNING, summary="P01 handoff accepted")
        with self.assertRaises(RunStateError):
            preparer.prepare(run)


if __name__ == "__main__":
    unittest.main()
