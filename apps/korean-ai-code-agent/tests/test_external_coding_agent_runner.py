from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from kagent.contracts import (
    ClawRunStatus,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
)
from kagent.external_coding_agent import (
    EXTERNAL_CODING_AGENT_RUNNER_LIVE_ADAPTERS,
    EXTERNAL_CODING_AGENT_RUNNER_SECOND_APPROVAL_AUTHORITY,
    EXTERNAL_CODING_AGENT_RUNNER_SECOND_CREDENTIAL_AUTHORITY,
    EXTERNAL_CODING_AGENT_RUNNER_SECOND_HISTORY_AUTHORITY,
    EXTERNAL_CODING_AGENT_RUNNER_SECOND_ORCHESTRATOR,
    EXTERNAL_CODING_AGENT_RUNNER_SECOND_SANDBOX_AUTHORITY,
    DeterministicFakeExternalCodingAgentRunner,
    ExternalCodingAgentApprovalBinding,
    ExternalCodingAgentBinding,
    ExternalCodingAgentConformanceHarness,
    ExternalCodingAgentError,
    ExternalCodingAgentEvent,
    ExternalCodingAgentEventKind,
    ExternalCodingAgentEventStream,
    ExternalCodingAgentPermissionHandoff,
    ExternalCodingAgentStartRequest,
    ExternalCodingAgentStatus,
    ExternalCodingAgentTerminalReason,
    normalize_external_status,
)
from padiem_ai_core import (
    AgentContinuationState,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    ContinuationStatus,
    VerifiedApprovalDecision,
)

BASE = datetime(2026, 9, 24, 0, 0, tzinfo=timezone.utc)
REV = "a" * 40
OTHER_REV = "b" * 40
RUNNER_REV = "c" * 40


def lease(*, run_id: str = "claw-run-1", lease_id: str = "lease-1") -> SandboxLease:
    return SandboxLease(
        lease_id=lease_id,
        run_id=run_id,
        execution_mode=ExecutionMode.CLOUD,
        resource_class=ResourceClass.STANDARD,
        network_policy=NetworkPolicy.OFF,
        writable_workspace=True,
        created_at=BASE,
        expires_at=BASE + timedelta(minutes=15),
    )


def request(**overrides) -> ExternalCodingAgentStartRequest:
    values = {
        "external_run_id": "external-run-1",
        "runner_kind": "fake-runner",
        "runner_revision": RUNNER_REV,
        "claw_run_id": "claw-run-1",
        "claw_task_id": "claw-task-1",
        "correlation_id": "turn-1",
        "task_ref": "task-ref-1",
        "repository_ref": "skerishKang/example",
        "source_revision": REV,
        "worktree_ref": "worktree-1",
        "worktree_base_revision": REV,
        "sandbox_lease": lease(),
        "credential_refs": ("credential-ref-1",),
        "capability_grant_refs": ("grant-ref-1",),
        "required_capabilities": ("read",),
        "idempotency_key": "external-idem-1",
    }
    values.update(overrides)
    return ExternalCodingAgentStartRequest(**values)


def pause(run_id: str = "claw-run-1", *, pause_id: str = "pause-1") -> ApprovalPause:
    return ApprovalPause(
        pause_id=pause_id,
        run_id=run_id,
        agent_runtime_id="agent:external@1",
        tool_id="tool:external:permission@1",
        invocation_sha256="d" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=BASE,
        expires_at=BASE + timedelta(minutes=10),
        approval_scope=("external:permission",),
    )


def approval_binding(handoff: ExternalCodingAgentPermissionHandoff) -> ExternalCodingAgentApprovalBinding:
    decision = VerifiedApprovalDecision(
        decision_id="decision-1",
        pause_id=handoff.approval_pause.pause_id,
        outcome=ApprovalOutcome.APPROVED,
        authority_ref="p01-authority",
        evidence_ref="approval-evidence-1",
        decided_at=BASE + timedelta(seconds=1),
    )
    continuation = AgentContinuationState(
        pause=handoff.approval_pause,
        status=ContinuationStatus.RESUMABLE,
        decision_id=decision.decision_id,
    )
    return ExternalCodingAgentApprovalBinding(
        pause=handoff.approval_pause,
        decision=decision,
        continuation=continuation,
    )


def event(sequence: int = 1, *, status: ExternalCodingAgentStatus | None = None, event_id: str | None = None) -> ExternalCodingAgentEvent:
    return ExternalCodingAgentEvent(
        event_id=event_id or f"event-{sequence}",
        external_run_id="external-run-1",
        sequence=sequence,
        kind=ExternalCodingAgentEventKind.STATUS_CHANGED,
        status=status or ExternalCodingAgentStatus(status=ClawRunStatus.QUEUED, binding=request().binding),
        occurred_at=BASE + timedelta(seconds=sequence),
        message="bounded status",
        provider_event_ref=f"provider-event-{sequence}",
    )


class ExternalCodingAgentRunnerTests(unittest.TestCase):
    def assert_error_code(self, code: str, operation, *args, **kwargs) -> None:
        with self.assertRaises(ExternalCodingAgentError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_request_reuses_canonical_contracts_and_has_no_authority(self) -> None:
        value = request()
        self.assertTrue(value.binding.matches(value))
        self.assertEqual(value.fingerprint, request().fingerprint)
        rendered = value.safe_dict()
        self.assertFalse(rendered["raw_credentials"])
        self.assertFalse(rendered["raw_provider_response"])
        self.assertFalse(rendered["implicit_write_send"])
        self.assertEqual(EXTERNAL_CODING_AGENT_RUNNER_LIVE_ADAPTERS, 0)
        self.assertFalse(EXTERNAL_CODING_AGENT_RUNNER_SECOND_ORCHESTRATOR)
        self.assertFalse(EXTERNAL_CODING_AGENT_RUNNER_SECOND_APPROVAL_AUTHORITY)
        self.assertFalse(EXTERNAL_CODING_AGENT_RUNNER_SECOND_HISTORY_AUTHORITY)
        self.assertFalse(EXTERNAL_CODING_AGENT_RUNNER_SECOND_SANDBOX_AUTHORITY)
        self.assertFalse(EXTERNAL_CODING_AGENT_RUNNER_SECOND_CREDENTIAL_AUTHORITY)

    def test_status_normalization_reuses_claw_status_and_represents_lost(self) -> None:
        value = request()
        self.assertIs(normalize_external_status("starting", binding=value.binding).status, ClawRunStatus.PREPARING)
        self.assertIs(normalize_external_status("waiting_approval", binding=value.binding).status, ClawRunStatus.WAITING_APPROVAL)
        lost = normalize_external_status("lost", binding=value.binding)
        self.assertIs(lost.status, ClawRunStatus.FAILED)
        self.assertEqual(lost.normalized_label, "lost")
        self.assertIs(lost.terminal_reason, ExternalCodingAgentTerminalReason.LOST_PROCESS)
        self.assert_error_code("unsupported_external_status", normalize_external_status, "provider_invented_state", binding=value.binding)

    def test_happy_path_normalizes_events_and_terminal_replay(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner()
        handle = runner.start(request())
        self.assertIs(handle.status.status, ClawRunStatus.QUEUED)
        self.assertEqual(runner.poll("external-run-1")[0].sequence, 1)
        self.assertIs(runner.observe("external-run-1").status, ClawRunStatus.PREPARING)
        self.assertIs(runner.observe("external-run-1").status, ClawRunStatus.RUNNING)
        terminal = runner.observe("external-run-1")
        self.assertIs(terminal.status, ClawRunStatus.COMPLETED)
        result = runner.result("external-run-1")
        self.assertEqual(runner.result("external-run-1"), result)
        self.assertTrue(result.output_digest)
        self.assertEqual([item.sequence for item in runner.poll("external-run-1")], [1, 2, 3, 4])
        runner.close("external-run-1")
        runner.close("external-run-1")

    def test_stream_alias_and_message_resume_are_bounded(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner()
        runner.start(request())
        runner.observe("external-run-1")
        runner.observe("external-run-1")
        self.assertEqual(runner.stream("external-run-1"), runner.poll("external-run-1"))
        status = runner.resume_or_message("external-run-1", message_ref="message-ref-1")
        self.assertIs(status.status, ClawRunStatus.RUNNING)

    def test_conformance_harness_accepts_fake_adapter_boundary(self) -> None:
        report = ExternalCodingAgentConformanceHarness().run(DeterministicFakeExternalCodingAgentRunner(), request())
        self.assertTrue(report.overall_conforming)
        self.assertEqual(
            {result.case_id for result in report.results},
            {
                "start_identity_and_binding",
                "observe_status_and_event_projection",
                "terminal_replay_is_idempotent",
                "close_is_idempotent",
            },
        )
        self.assertEqual(report.to_public_dict()["live_provider_calls"], 0)

    def test_start_failure_and_runtime_failure_are_normalized(self) -> None:
        start_failure = DeterministicFakeExternalCodingAgentRunner(start_failure=True)
        handle = start_failure.start(
            request(
                external_run_id="external-start-failure",
                correlation_id="turn-start-failure",
                idempotency_key="idem-start-failure",
            )
        )
        self.assertIs(handle.status.status, ClawRunStatus.FAILED)
        self.assertIs(start_failure.result("external-start-failure").terminal_reason, ExternalCodingAgentTerminalReason.START_FAILED)

        runtime_failure = DeterministicFakeExternalCodingAgentRunner(runtime_failure=True)
        runtime_failure.start(
            request(
                external_run_id="external-runtime-failure",
                correlation_id="turn-runtime-failure",
                idempotency_key="idem-runtime-failure",
            )
        )
        self.assertIs(runtime_failure.observe("external-runtime-failure").status, ClawRunStatus.FAILED)
        self.assertIs(runtime_failure.result("external-runtime-failure").terminal_reason, ExternalCodingAgentTerminalReason.RUNTIME_FAILED)

    def test_duplicate_start_and_correlation_are_rejected(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner()
        value = request()
        runner.start(value)
        self.assert_error_code("duplicate_start", runner.start, value)
        self.assert_error_code(
            "duplicate_correlation",
            runner.start,
            request(external_run_id="external-run-2", sandbox_lease=lease(lease_id="lease-2"), idempotency_key="idem-2"),
        )

    def test_cancel_race_is_bounded_and_terminal_replay_is_idempotent(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner()
        runner.start(request())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(runner.cancel, "external-run-1", reason_ref="user-cancel") for _ in range(2)]
            statuses = [future.result() for future in futures]
        self.assertEqual(statuses[0], statuses[1])
        self.assertIs(statuses[0].status, ClawRunStatus.CANCELLED)
        self.assertEqual(runner.result("external-run-1"), runner.result("external-run-1"))
        self.assertIs(runner.poll("external-run-1")[-1].kind, ExternalCodingAgentEventKind.TERMINAL_RESULT)

    def test_lost_process_is_canonical_failed_with_lost_reason(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner(lost_process=True)
        runner.start(request())
        status = runner.observe("external-run-1")
        self.assertIs(status.status, ClawRunStatus.FAILED)
        self.assertEqual(status.normalized_label, "lost")
        self.assertIs(status.terminal_reason, ExternalCodingAgentTerminalReason.LOST_PROCESS)
        self.assertIs(runner.result("external-run-1").terminal_reason, ExternalCodingAgentTerminalReason.LOST_PROCESS)
        self.assertIs(runner.poll("external-run-1")[-1].kind, ExternalCodingAgentEventKind.PROCESS_LOST)

    def test_lost_process_reconciliation_is_explicit_and_idempotent(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner()
        runner.start(request())
        first = runner.reconcile_lost_process("external-run-1")
        second = runner.reconcile_lost_process("external-run-1")
        self.assertEqual(first, second)
        self.assertEqual(first.normalized_label, "lost")

    def test_approval_required_reuses_canonical_pause_and_rejects_unauthorized_resume(self) -> None:
        runner = DeterministicFakeExternalCodingAgentRunner(approval_required=True)
        runner.start(request())
        status = runner.observe("external-run-1")
        self.assertIs(status.status, ClawRunStatus.WAITING_APPROVAL)
        permission = runner.poll("external-run-1")[-1].permission
        self.assertIsNotNone(permission)
        assert permission is not None
        permission.assert_matches(request())
        self.assert_error_code("unauthorized_permission", runner.resume_or_message, "external-run-1", approval=None)
        other_permission = ExternalCodingAgentPermissionHandoff(
            permission_id="permission-other",
            external_run_id="external-run-1",
            capability_ref="capability:external:permission@1",
            approval_pause=pause("other-run"),
        )
        self.assert_error_code(
            "permission_mismatch",
            runner.resume_or_message,
            "external-run-1",
            approval=approval_binding(other_permission),
        )
        self.assertIs(runner.resume_or_message("external-run-1", approval=approval_binding(permission)).status, ClawRunStatus.RUNNING)
        self.assertIs(runner.observe("external-run-1").status, ClawRunStatus.COMPLETED)

    def test_permission_handoff_rejects_wrong_canonical_run(self) -> None:
        value = request()
        handoff = ExternalCodingAgentPermissionHandoff(
            permission_id="permission-1",
            external_run_id="external-run-1",
            capability_ref="capability:write@1",
            approval_pause=pause("other-run"),
        )
        with self.assertRaises(ExternalCodingAgentError) as caught:
            handoff.assert_matches(value)
        self.assertEqual(caught.exception.code, "permission_mismatch")

    def test_revision_worktree_and_sandbox_mismatches_fail_closed(self) -> None:
        self.assert_error_code("invalid_revision", request, source_revision="main")
        self.assert_error_code("worktree_mismatch", request, worktree_base_revision=OTHER_REV)
        self.assert_error_code("sandbox_mismatch", request, sandbox_lease=lease(run_id="other-run", lease_id="lease-other"))
        value = request()
        wrong_binding = ExternalCodingAgentBinding(
            source_revision=OTHER_REV,
            worktree_ref=value.worktree_ref,
            worktree_base_revision=OTHER_REV,
            sandbox_lease_id=value.sandbox_lease.lease_id,
        )
        with self.assertRaises(ExternalCodingAgentError) as caught:
            ExternalCodingAgentStatus(status=ClawRunStatus.RUNNING, binding=wrong_binding).assert_binding_matches(value)
        self.assertEqual(caught.exception.code, "revision_mismatch")

    def test_raw_credentials_and_unauthorized_write_send_are_rejected(self) -> None:
        self.assert_error_code("raw_credential_rejected", request, credential_refs=("sk-" + "a" * 24,))
        self.assert_error_code("unauthorized_permission", request, required_capabilities=("write",), capability_grant_refs=())
        with self.assertRaises(ExternalCodingAgentError) as caught:
            ExternalCodingAgentEvent(
                event_id="event-secret",
                external_run_id="external-run-1",
                sequence=1,
                kind=ExternalCodingAgentEventKind.STATUS_CHANGED,
                status=ExternalCodingAgentStatus(status=ClawRunStatus.RUNNING),
                occurred_at=BASE,
                message="api_key=should-not-be-accepted",
            )
        self.assertEqual(caught.exception.code, "raw_credential_rejected")

    def test_event_stream_handles_duplicate_conflict_and_reorder(self) -> None:
        stream = ExternalCodingAgentEventStream()
        first = event()
        stream.append(first)
        stream.append(first)
        self.assertEqual(len(stream.events("external-run-1")), 1)
        self.assert_error_code("event_id_reuse_conflict", stream.append, replace(first, message="conflicting duplicate"))
        self.assert_error_code("event_sequence_gap", stream.append, event(3, event_id="event-3"))
        reordered = ExternalCodingAgentEventStream()
        self.assert_error_code("event_sequence_gap", reordered.append, event(3, event_id="event-3"))

    def test_harness_rejects_mutated_binding_projection(self) -> None:
        inner = DeterministicFakeExternalCodingAgentRunner()

        class MutatedRunner:
            def start(self, value):
                return inner.start(value)

            def status(self, external_run_id):
                status = inner.status(external_run_id)
                return replace(
                    status,
                    binding=ExternalCodingAgentBinding(
                        source_revision=OTHER_REV,
                        worktree_ref="worktree-other",
                        worktree_base_revision=OTHER_REV,
                        sandbox_lease_id="lease-other",
                    ),
                )

            def observe(self, external_run_id):
                return inner.observe(external_run_id)

            def reconcile_lost_process(self, external_run_id, *, reason_ref="process_lost"):
                return inner.reconcile_lost_process(external_run_id, reason_ref=reason_ref)

            def poll(self, external_run_id, *, after_sequence=0):
                return inner.poll(external_run_id, after_sequence=after_sequence)

            def cancel(self, external_run_id, *, reason_ref="cancelled"):
                return inner.cancel(external_run_id, reason_ref=reason_ref)

            def resume_or_message(self, external_run_id, *, approval=None, message_ref=None):
                return inner.resume_or_message(external_run_id, approval=approval, message_ref=message_ref)

            def result(self, external_run_id):
                return inner.result(external_run_id)

            def close(self, external_run_id):
                inner.close(external_run_id)

        report = ExternalCodingAgentConformanceHarness().run(MutatedRunner(), request())
        self.assertFalse(report.overall_conforming)
        self.assertTrue(any(result.error_code == "revision_mismatch" for result in report.results))


if __name__ == "__main__":
    unittest.main()
