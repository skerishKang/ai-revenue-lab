"""#2961 owner approve/deny consumed through the canonical Engine continuation.

NETWORK_FREE / SOURCE_ONLY: one fake Engine client stands in for
``PadiemAiEngineClient.resume_orchestration``. No provider call, no Production
Engine, no live pause producer, no workflow dispatch.

Contract proven here:
  * the trusted P01 request reconstructs exactly from the #2956 closed snapshot,
    and every authority deviation (unknown key, agent shape, trace, app, session,
    model/tool authority, fingerprint-bearing expiry handled by the owner store)
    fails closed *before* any Engine transport is touched;
  * only ``approve``/``deny`` map onto an outcome, and the submission carries the
    stored pause identity plus server-derived authority references only;
  * B54 never constructs ``VerifiedApprovalDecision`` or
    ``ToolAuthorizationContext`` and never sends ``pause``/tool authority;
  * lifecycle is projected by the existing ``ClawResumeProjector``: RUNNING only
    after canonical RUN_RESUMED, WAITING_APPROVAL again on a new Engine pause,
    CANCELLED on canonical denial;
  * a transport or Engine rejection keeps the handoff retry-safe.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import unittest
from typing import Any

from padiem_ai_core import (
    ApprovalPause,
    ApprovalRequirement,
    ExecutionContext,
    OrchestrationResult,
)
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_engine_client import PadiemAiEngineClientError

import kagent.p01_approval_continuation as continuation
from kagent.contracts import ClawRunStatus
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    P01AdapterError,
    P01DispatchClass,
)
from kagent.p01_orchestration_client import PADIEM_EXECUTABLE_MODEL_IDS
from kagent.p01_resume import (
    APPROVAL_FROM_CHAT_SENTIMENT_SUPPORTED,
    B54_MINTS_VERIFIED_APPROVAL_DECISION,
)

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
RUN_ID = "run_2961_decision"
TRACE_ID = "claw_2961_trace"
P01_RUN_ID = "orch_2961_run"
CONTINUATION_REF = "cont_EngineOpaqueRef_01"
NEXT_CONTINUATION_REF = "cont_EngineOpaqueRef_02"
PAUSE_ID = "pause_engine_001"
NEXT_PAUSE_ID = "pause_engine_002"
MODEL_ID = sorted(PADIEM_EXECUTABLE_MODEL_IDS)[0]

# Exactly the fields the canonical Engine resume wire accepts for the agent.
_TRUSTED_AGENT_KEYS = frozenset(
    {
        "id",
        "title",
        "description",
        "system_instruction",
        "task_type",
        "optimize_for",
        "max_tokens",
        "allowed_tools",
        "required_capabilities",
        "context_policy",
        "model_policy",
        "max_steps",
        "output_contract",
    }
)


def trusted_snapshot(**overrides: Any) -> dict[str, Any]:
    """One closed #2956 trusted P01 request snapshot, overridable per case."""
    payload: dict[str, Any] = {
        "app_id": P01_APP_ID,
        "agent": {
            "id": P01_AGENT_ID,
            "title": "Padiem Claw",
            "description": "B54 repository task execution consumer",
            "system_instruction": None,
            "task_type": "coding",
            "optimize_for": "balanced",
            "max_tokens": None,
            "allowed_tools": [],
            "required_capabilities": [],
            "context_policy": {},
            "model_policy": {"model": MODEL_ID},
            "max_steps": 1,
            "output_contract": {},
        },
        "messages": [{"role": "user", "content": "견적을 정리해줘"}],
        "session_id": RUN_ID,
        "additional_system_context": None,
        "trace_id": TRACE_ID,
        "execution_context": {
            "trace_id": TRACE_ID,
            "idempotency_key": None,
            "timeout_seconds": 20.0,
        },
    }
    payload.update(overrides)
    return payload


def _reconstruct(**overrides: Any) -> continuation.TrustedResumeRequest:
    kwargs: dict[str, Any] = {
        "trusted_request": overrides.pop("trusted_request", trusted_snapshot()),
        "run_id": overrides.pop("run_id", RUN_ID),
        "p01_run_id": overrides.pop("p01_run_id", P01_RUN_ID),
    }
    kwargs.update(overrides)
    return continuation.reconstruct_trusted_resume_request(**kwargs)


def _submission(decision: str = continuation.APPROVAL_DECISION_APPROVE) -> dict[str, Any]:
    return continuation.build_first_party_decision_submission(
        pause_id=PAUSE_ID, decision=decision, owner_id="usr_" + "7" * 32, now=lambda: NOW
    )


def _pause(pause_id: str, continuation_run_id: str = P01_RUN_ID) -> ApprovalPause:
    return ApprovalPause(
        pause_id=pause_id,
        run_id=continuation_run_id,
        agent_runtime_id=P01_AGENT_ID,
        tool_id="tool_write_file",
        invocation_sha256="a" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        trace_id=TRACE_ID,
        plan_id="plan_2961",
        approval_scope=("workspace_write",),
    )


def _result(
    kinds: list[OrchestrationEventKind],
    *,
    next_pause: ApprovalPause | None = None,
    answer: str | None = "재개 완료",
    event_run_id: str = P01_RUN_ID,
) -> OrchestrationResult:
    status = RunStatus.PAUSED if next_pause is not None else RunStatus.COMPLETED
    return OrchestrationResult(
        execution_result=ExecutionResult(
            answer=answer,
            route=B14RouteMetadata(),
            metadata=RunMetadata(
                trace_id=TRACE_ID,
                app_id=P01_APP_ID,
                agent_id=P01_AGENT_ID,
                session_id=RUN_ID,
                status=status,
            ),
        ),
        context=ExecutionContext(trace_id=TRACE_ID, timeout_seconds=20.0),
        app_id=P01_APP_ID,
        subject_id=None,
        plan=None,
        activated_skill=None,
        resolved_tool_ids=(),
        evidence_graph=None,
        claim_assessments=(),
        grounded_citations=(),
        events=tuple(
            public_orchestration_event(
                event_id=f"evt_{index}",
                run_id=event_run_id,
                trace_id=TRACE_ID,
                app_id=P01_APP_ID,
                kind=kind,
                sequence=index,
                message=None,
                timestamp_iso="2026-09-23T12:10:00+00:00",
            )
            for index, kind in enumerate(kinds, start=1)
        ),
        approval_pause=next_pause,
    )


def _wire(result: OrchestrationResult, continuation_ref: str | None = None) -> dict[str, Any]:
    """Engine-shaped resume response for the existing pause wire splitter."""
    payload = result.to_public_dict()
    if continuation_ref is not None:
        payload["continuation_ref"] = continuation_ref
    return payload


class _FakeEngineResumeClient:
    """Stands in for ``PadiemAiEngineClient`` on the canonical resume route."""

    app_id = P01_APP_ID

    def __init__(
        self,
        *,
        result: OrchestrationResult | None = None,
        continuation_ref: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.payloads: list[dict[str, Any]] = []
        self._result = result
        self._continuation_ref = continuation_ref
        self._error = error

    async def resume_orchestration(self, request: Any) -> dict[str, Any]:
        self.payloads.append(dict(request))
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return _wire(self._result, self._continuation_ref)


class ReconstructTrustedResumeRequestTests(unittest.TestCase):
    def test_reconstructs_exactly_from_the_persisted_snapshot(self) -> None:
        request = _reconstruct()

        self.assertEqual(request.trace_id, TRACE_ID)
        self.assertEqual(request.p01_run_id, P01_RUN_ID)
        self.assertEqual(request.payload["session_id"], RUN_ID)
        self.assertEqual(request.payload["trace_id"], TRACE_ID)
        self.assertEqual(
            request.payload["execution_context"],
            {"trace_id": TRACE_ID, "timeout_seconds": 20.0},
        )
        self.assertEqual(
            request.payload["messages"], [{"role": "user", "content": "견적을 정리해줘"}]
        )
        # The persisted identity payload is reduced to the wire agent shape by
        # dropping only provably-inert fields, never by inventing a value.
        self.assertEqual(
            set(request.payload["agent"]),
            set(_TRUSTED_AGENT_KEYS)
            - {"allowed_tools", "context_policy", "max_steps", "output_contract"},
        )
        self.assertEqual(request.payload["agent"]["id"], P01_AGENT_ID)
        self.assertEqual(request.payload["agent"]["model_policy"], {"model": MODEL_ID})
        self.assertNotIn("app_id", request.payload)
        self.assertNotIn("additional_system_context", request.payload)
        # The snapshot is preserved unchanged for a possible next pause.
        self.assertEqual(request.snapshot, trusted_snapshot())

    def test_additional_system_context_is_replayed_when_present(self) -> None:
        snapshot = trusted_snapshot(additional_system_context="workspace 규칙")
        request = _reconstruct(trusted_request=snapshot)
        self.assertEqual(request.payload["additional_system_context"], "workspace 규칙")

    def test_unknown_snapshot_key_fails_closed(self) -> None:
        snapshot = trusted_snapshot(tool_arguments={"cmd": "rm"})
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=snapshot)
        self.assertEqual(raised.exception.code, "handoff_snapshot_unknown_key")

    def test_incomplete_snapshot_fails_closed(self) -> None:
        snapshot = trusted_snapshot()
        snapshot.pop("execution_context")
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=snapshot)
        self.assertEqual(raised.exception.code, "handoff_snapshot_incomplete")

    def test_agent_shape_deviation_fails_closed(self) -> None:
        for name, agent in {
            "extra": {**trusted_snapshot()["agent"], "tool_registry": "x"},
            "missing": {
                key: value
                for key, value in trusted_snapshot()["agent"].items()
                if key != "model_policy"
            },
            "wrong_id": {**trusted_snapshot()["agent"], "id": "attacker-agent"},
        }.items():
            with self.subTest(agent=agent and name):
                with self.assertRaises(P01AdapterError) as raised:
                    _reconstruct(trusted_request=trusted_snapshot(agent=agent))
                self.assertIn(
                    raised.exception.code,
                    {"handoff_agent_shape_invalid", "handoff_agent_shape_incomplete", "handoff_agent_mismatch"},
                )

    def test_context_trace_mismatch_fails_closed(self) -> None:
        snapshot = trusted_snapshot(
            execution_context={
                "trace_id": "claw_other_trace",
                "idempotency_key": None,
                "timeout_seconds": 20.0,
            }
        )
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=snapshot)
        self.assertEqual(raised.exception.code, "handoff_context_trace_mismatch")

    def test_wrong_app_identity_fails_closed(self) -> None:
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=trusted_snapshot(app_id="b62-padiem-chat"))
        self.assertEqual(raised.exception.code, "handoff_app_mismatch")

    def test_session_run_correlation_mismatch_fails_closed(self) -> None:
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=trusted_snapshot(session_id="run_someone_else"))
        self.assertEqual(raised.exception.code, "handoff_session_mismatch")

    def test_unsupported_model_or_tool_authority_fails_closed(self) -> None:
        cases = {
            "foreign_model": trusted_snapshot(
                agent={
                    **trusted_snapshot()["agent"],
                    "model_policy": {"model": "evil/provider-model"},
                }
            ),
            "tool_authority": trusted_snapshot(
                agent={**trusted_snapshot()["agent"], "allowed_tools": ["tool_send_email"]}
            ),
            "extra_route": trusted_snapshot(
                agent={
                    **trusted_snapshot()["agent"],
                    "model_policy": {"model": MODEL_ID, "fallback": "other"},
                }
            ),
            "idempotency": trusted_snapshot(
                execution_context={
                    "trace_id": TRACE_ID,
                    "idempotency_key": "attack-key",
                    "timeout_seconds": 20.0,
                }
            ),
            "max_steps": trusted_snapshot(
                agent={**trusted_snapshot()["agent"], "max_steps": 9}
            ),
        }
        for name, snapshot in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(P01AdapterError) as raised:
                    _reconstruct(trusted_request=snapshot)
                self.assertEqual(raised.exception.code, "handoff_authority_pinning")

    def test_reconstruction_is_dispatch_class_not_dispatched(self) -> None:
        # A malformed snapshot must never be counted as an executed attempt.
        with self.assertRaises(P01AdapterError) as raised:
            _reconstruct(trusted_request=trusted_snapshot(app_id="other"))
        self.assertEqual(raised.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)


class FirstPartyDecisionSubmissionTests(unittest.TestCase):
    def test_only_approve_and_deny_map_to_an_outcome(self) -> None:
        self.assertEqual(
            continuation.decision_outcome(continuation.APPROVAL_DECISION_APPROVE), "approved"
        )
        self.assertEqual(
            continuation.decision_outcome(continuation.APPROVAL_DECISION_DENY), "denied"
        )
        for value in ("maybe", "APPROVE", True, None, "", "skip", 1):
            with self.subTest(value=value):
                with self.assertRaises(P01AdapterError) as raised:
                    continuation.decision_outcome(value)
                self.assertEqual(raised.exception.code, "invalid_approval_decision")

    def test_submission_uses_stored_pause_and_server_derived_authority(self) -> None:
        submission = _submission()
        self.assertEqual(
            submission,
            {
                "decision_id": submission["decision_id"],
                "pause_id": PAUSE_ID,
                "outcome": "approved",
                "authority_ref": "b54_session:" + "usr_" + "7" * 32,
                "evidence_ref": f"b54_decision:{submission['decision_id']}",
                "decided_at": "2026-09-23T12:00:00.000Z",
            },
        )
        self.assertTrue(submission["decision_id"].startswith("decision_b54_"))
        self.assertEqual(
            set(submission),
            {"decision_id", "pause_id", "outcome", "authority_ref", "evidence_ref", "decided_at"},
        )

    def test_submission_is_deterministic_per_owner_pause_and_outcome(self) -> None:
        self.assertEqual(_submission()["decision_id"], _submission()["decision_id"])
        self.assertNotEqual(
            _submission(continuation.APPROVAL_DECISION_DENY)["decision_id"],
            _submission()["decision_id"],
        )

    def test_missing_or_malformed_stored_pause_id_fails_closed(self) -> None:
        for value in (None, "", "   ", "pause with space", 7):
            with self.subTest(value=value):
                with self.assertRaises(P01AdapterError) as raised:
                    continuation.build_first_party_decision_submission(
                        pause_id=value,
                        decision=continuation.APPROVAL_DECISION_APPROVE,
                        owner_id="usr_" + "7" * 32,
                    )
                self.assertEqual(raised.exception.code, "handoff_pause_id_invalid")

    def test_unauthenticated_owner_fails_closed(self) -> None:
        for value in (None, "", "owner with space"):
            with self.subTest(value=value):
                with self.assertRaises(P01AdapterError) as raised:
                    continuation.build_first_party_decision_submission(
                        pause_id=PAUSE_ID,
                        decision=continuation.APPROVAL_DECISION_APPROVE,
                        owner_id=value,
                    )
                self.assertEqual(raised.exception.code, "approval_owner_unavailable")


class ContinuationClientTests(unittest.TestCase):
    def test_b54_never_mints_a_verified_decision_or_tool_authorization(self) -> None:
        # Inherited product policy stays asserted, not restated as a literal.
        self.assertIs(B54_MINTS_VERIFIED_APPROVAL_DECISION, False)
        self.assertIs(APPROVAL_FROM_CHAT_SENTIMENT_SUPPORTED, False)
        self.assertIs(continuation.B54_CONSTRUCTS_VERIFIED_APPROVAL_DECISION, False)
        self.assertIs(continuation.B54_CONSTRUCTS_TOOL_AUTHORIZATION_CONTEXT, False)

    def test_resume_transport_is_the_only_engine_surface_consumed(self) -> None:
        # A client exposing exactly the canonical resume route is sufficient:
        # the lane needs no second resume protocol and no verifier of its own.
        client = _FakeEngineResumeClient(result=_result([OrchestrationEventKind.RUN_STARTED]))
        bound = continuation.P01EngineApprovalContinuationClient(client)
        self.assertEqual(
            sorted(
                name
                for name in vars(type(bound))
                if not name.startswith("_")
            ),
            ["resume"],
        )
        self.assertFalse(hasattr(type(client), "resume_orchestration_v2"))
        for forbidden in ("VerifiedApprovalDecision", "ApprovalDecisionSubmission"):
            with self.subTest(symbol=forbidden):
                self.assertFalse(hasattr(continuation, forbidden))


class ApprovalContinuationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def _decide(
        self,
        client: _FakeEngineResumeClient,
        *,
        decision: str = continuation.APPROVAL_DECISION_APPROVE,
        request: continuation.TrustedResumeRequest | None = None,
        continuation_ref: str = CONTINUATION_REF,
    ):
        service = continuation.P01ApprovalContinuationService(
            continuation.P01EngineApprovalContinuationClient(client)
        )
        return await service.decide(
            run_id=RUN_ID,
            continuation_ref=continuation_ref,
            request=request or _reconstruct(),
            submission=_submission(decision),
        )

    async def test_approve_projects_running_then_completed_on_resume_evidence(self) -> None:
        client = _FakeEngineResumeClient(
            result=_result(
                [
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.RUN_RESUMED,
                    OrchestrationEventKind.RUN_COMPLETED,
                ]
            )
        )
        outcome = await self._decide(client)

        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(outcome.decision, "approved")
        self.assertEqual(outcome.answer, "재개 완료")
        self.assertEqual(outcome.p01_event_count, 3)
        self.assertIsNone(outcome.next_continuation_ref)

        payload = client.payloads[0]
        self.assertEqual(payload["continuation_ref"], CONTINUATION_REF)
        self.assertEqual(payload["decision"]["outcome"], "approved")
        self.assertEqual(payload["decision"]["pause_id"], PAUSE_ID)
        self.assertEqual(payload["session_id"], RUN_ID)
        # The caller never supplies Engine or tool authority on this lane.
        self.assertEqual(
            set(payload), {"agent", "messages", "trace_id", "execution_context", "session_id", "continuation_ref", "decision"}
        )
        for forbidden in ("pause", "tool_authorization", "tool_arguments", "tool_runtime", "workspace_id"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, payload)

    async def test_completion_without_run_resumed_evidence_is_refused(self) -> None:
        client = _FakeEngineResumeClient(
            result=_result(
                [OrchestrationEventKind.RUN_STARTED, OrchestrationEventKind.RUN_COMPLETED]
            )
        )
        with self.assertRaises(P01AdapterError) as raised:
            await self._decide(client)
        # Reused projector policy: completion needs canonical RUN_RESUMED first.
        self.assertEqual(raised.exception.code, "completion_before_resume")

    def test_run_started_alone_never_projects_running(self) -> None:
        # The resume correlation envelope proves nothing on its own: B54 returns
        # to RUNNING only on RUN_RESUMED evidence.
        run = continuation._rehydrate_waiting_run(run_id=RUN_ID, request=_reconstruct())
        projector = continuation.ClawResumeProjector(
            run, trace_id=TRACE_ID, p01_run_id=P01_RUN_ID, app_id=P01_APP_ID
        )
        projector.consume(
            public_orchestration_event(
                event_id="evt_started_only",
                run_id=P01_RUN_ID,
                trace_id=TRACE_ID,
                app_id=P01_APP_ID,
                kind=OrchestrationEventKind.RUN_STARTED,
                sequence=1,
                message=None,
                timestamp_iso="2026-09-23T12:10:00+00:00",
            )
        )
        self.assertEqual(run.status, ClawRunStatus.WAITING_APPROVAL)
        self.assertFalse(projector.resume_seen)
        projector.consume(
            public_orchestration_event(
                event_id="evt_resumed",
                run_id=P01_RUN_ID,
                trace_id=TRACE_ID,
                app_id=P01_APP_ID,
                kind=OrchestrationEventKind.RUN_RESUMED,
                sequence=2,
                message=None,
                timestamp_iso="2026-09-23T12:10:01+00:00",
            )
        )
        self.assertEqual(run.status, ClawRunStatus.RUNNING)
        self.assertTrue(projector.resume_seen)

    async def test_second_engine_pause_returns_waiting_approval_with_new_identity(self) -> None:
        next_pause = _pause(NEXT_PAUSE_ID)
        client = _FakeEngineResumeClient(
            result=_result(
                [
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.RUN_RESUMED,
                    OrchestrationEventKind.APPROVAL_PAUSED,
                ],
                next_pause=next_pause,
            ),
            continuation_ref=NEXT_CONTINUATION_REF,
        )
        outcome = await self._decide(client)

        self.assertEqual(outcome.projection.status, ClawRunStatus.WAITING_APPROVAL)
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.next_continuation_ref, NEXT_CONTINUATION_REF)
        self.assertEqual(outcome.next_pause_id, NEXT_PAUSE_ID)
        self.assertEqual(outcome.next_p01_run_id, P01_RUN_ID)
        # The next generation preserves the Engine pause identity and the same
        # trusted request; the decided ref is never reused.
        self.assertNotEqual(outcome.next_continuation_ref, CONTINUATION_REF)
        self.assertEqual(dict(outcome.next_trusted_request or {}), trusted_snapshot())
        # Expiry stays the Engine-issued aware timestamp; the store rejects a
        # naive one, so it must round-trip parseable.
        parsed_expiry = datetime.fromisoformat(str(outcome.next_pause_expires_at))
        self.assertIsNotNone(parsed_expiry.tzinfo)
        self.assertGreater(parsed_expiry, NOW)

    async def test_canonical_denial_is_projected_cancelled(self) -> None:
        client = _FakeEngineResumeClient(
            error=PadiemAiEngineClientError("approval_denied", "Engine denied")
        )
        outcome = await self._decide(client, decision=continuation.APPROVAL_DECISION_DENY)

        self.assertEqual(outcome.projection.status, ClawRunStatus.CANCELLED)
        self.assertEqual(outcome.decision, "denied")
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.p01_event_count, 0)
        self.assertIsNone(outcome.next_continuation_ref)
        # Denial travels the same canonical resume route: no second protocol.
        self.assertEqual(len(client.payloads), 1)
        self.assertEqual(client.payloads[0]["decision"]["outcome"], "denied")

    async def test_transport_failure_keeps_the_handoff_retry_safe(self) -> None:
        client = _FakeEngineResumeClient(
            error=PadiemAiEngineClientError("engine_http_error", "transport down")
        )
        with self.assertRaises(P01AdapterError) as raised:
            await self._decide(client)
        error = raised.exception
        self.assertEqual(error.code, "p01_continuation_request_failed")
        self.assertEqual(error.dispatch_class, P01DispatchClass.UNKNOWN)

    async def test_engine_rejection_keeps_the_run_waiting_and_is_not_dispatched(self) -> None:
        client = _FakeEngineResumeClient(
            error=PadiemAiEngineClientError("continuation_identity_mismatch", "mismatch")
        )
        with self.assertRaises(P01AdapterError) as raised:
            await self._decide(client)
        self.assertEqual(raised.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
        self.assertEqual(raised.exception.code, "continuation_identity_mismatch")

    async def test_malformed_stored_continuation_ref_never_reaches_the_engine(self) -> None:
        client = _FakeEngineResumeClient(result=_result([OrchestrationEventKind.RUN_STARTED]))
        for value in ("", "cont_short", "attacker_ref_0000", None):
            with self.subTest(value=value):
                with self.assertRaises(P01AdapterError) as raised:
                    await self._decide(client, continuation_ref=value)
                self.assertEqual(raised.exception.code, "handoff_continuation_ref_invalid")
        self.assertEqual(client.payloads, [])

    async def test_handoff_without_p01_run_identity_never_reaches_the_engine(self) -> None:
        client = _FakeEngineResumeClient(result=_result([OrchestrationEventKind.RUN_STARTED]))
        with self.assertRaises(P01AdapterError) as raised:
            await self._decide(client, request=_reconstruct(p01_run_id=None))
        self.assertEqual(raised.exception.code, "handoff_p01_run_id_missing")
        self.assertEqual(client.payloads, [])

    async def test_pause_without_engine_continuation_identity_fails_closed(self) -> None:
        # A re-pause whose wire carries no fresh continuation_ref cannot be
        # preserved, so it must not be reported as a new WAITING_APPROVAL.
        client = _FakeEngineResumeClient(
            result=_result(
                [
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.RUN_RESUMED,
                    OrchestrationEventKind.APPROVAL_PAUSED,
                ],
                next_pause=_pause(NEXT_PAUSE_ID),
            )
        )
        with self.assertRaises(P01AdapterError):
            await self._decide(client)

    async def test_cancelled_resume_cancels_the_run_and_propagates(self) -> None:
        class _Cancelling(_FakeEngineResumeClient):
            async def resume_orchestration(self, request: Any) -> dict[str, Any]:
                self.payloads.append(dict(request))
                raise asyncio.CancelledError

        service = continuation.P01ApprovalContinuationService(
            continuation.P01EngineApprovalContinuationClient(_Cancelling())
        )
        with self.assertRaises(asyncio.CancelledError):
            await service.decide(
                run_id=RUN_ID,
                continuation_ref=CONTINUATION_REF,
                request=_reconstruct(),
                submission=_submission(),
            )

    async def test_engine_client_without_resume_transport_is_refused(self) -> None:
        class _NoResume:
            app_id = P01_APP_ID

        with self.assertRaises(P01AdapterError) as raised:
            continuation.P01EngineApprovalContinuationClient(_NoResume())
        self.assertEqual(raised.exception.code, "invalid_engine_client")

    async def test_engine_client_app_identity_must_match_the_b54_lane(self) -> None:
        class _WrongApp(_FakeEngineResumeClient):
            app_id = "b62-padiem-chat"

        with self.assertRaises(P01AdapterError) as raised:
            continuation.P01EngineApprovalContinuationClient(_WrongApp())
        self.assertEqual(raised.exception.code, "continuation_app_id_mismatch")

    async def test_response_for_a_different_p01_run_is_refused(self) -> None:
        # A resume response cannot be re-pointed at another orchestration run:
        # the stored Engine run identity gates every projected event.
        client = _FakeEngineResumeClient(
            result=_result(
                [
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.RUN_RESUMED,
                    OrchestrationEventKind.RUN_COMPLETED,
                ],
                event_run_id="orch_someone_else",
            )
        )
        with self.assertRaises(P01AdapterError) as raised:
            await self._decide(client)
        self.assertEqual(raised.exception.code, "p01_run_mismatch")


if __name__ == "__main__":
    unittest.main()
