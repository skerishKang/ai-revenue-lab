"""S13-5 Phase 1: additive continuation lifecycle mirror on the orchestrate route.

The AGENT-SKILL route publishes a continuation lifecycle plane (S13-4 Phase 3).
These tests prove the ORCHESTRATE route names the same facts through the same
shared projection, that the mirror is purely additive, that no lifecycle is
invented when no continuation record exists, and that no authority material or
secret crosses the new surface.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from padiem_ai_core import (
    ApprovalPause,
    ApprovalRequirement,
    B14RouteMetadata,
    ExecutionResult,
    RunMetadata,
    RunStatus,
    VerifiedApprovalDecision,
)

from app.agent_skill_continuation_projection import (
    ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION,
)
from app.orchestration_service import (
    InMemoryContinuationStore,
    OrchestrationEngineService,
    _orchestration_lifecycle_block,
)

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from agent_pause_fixture import PausedRunFixture  # noqa: E402

LIFECYCLE_EVENT_KEYS = {
    "event_id",
    "continuation_id",
    "task_id",
    "trace_id",
    "sequence",
    "kind",
    "terminal",
    "timestamp_iso",
    "derived_from",
    "source_event_id",
}
ORCHESTRATE_CONTINUATION_BLOCK_KEYS = {
    "continuation_id",
    "lifecycle_contract_version",
    "lifecycle_events",
}
FORBIDDEN_MARKERS = (
    "claim_token",
    "authority_ref",
    "evidence_ref",
    "approval_decision",
    "invocation_sha256",
    "cancel_event_fingerprint",
    "caller_id",
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _expected_event_id(*, continuation_id: str, kind: str, sequence: int) -> str:
    """Recompute the documented id rule independently of the implementation."""

    digest = hashlib.sha256(f"{continuation_id}|{kind}|{sequence}".encode("utf-8")).hexdigest()
    return f"lce_{digest[:12]}"


class _Verifier:
    def verify(self, submission: Any, *, pause: Any, app_id: str) -> VerifiedApprovalDecision:
        return VerifiedApprovalDecision(
            decision_id=submission.decision_id,
            pause_id=submission.pause_id,
            outcome=submission.outcome,
            authority_ref=submission.authority_ref,
            evidence_ref=submission.evidence_ref,
            decided_at=submission.decided_at,
        )


class _Runtime:
    async def run(self, request: Any) -> ExecutionResult:
        return ExecutionResult(
            answer="resumed answer",
            route=B14RouteMetadata(selected_provider="mock_provider", selected_model="mock_model"),
            metadata=RunMetadata(
                trace_id=request.trace_id or "tr_engine",
                app_id="b62",
                agent_id=request.agent.id,
                status=RunStatus.COMPLETED,
            ),
        )


def _service() -> OrchestrationEngineService:
    return OrchestrationEngineService(
        runtime_factory=lambda app_id: _Runtime(),
        b14_service_bound=True,
        approval_decision_verifier=_Verifier(),
        continuation_store=InMemoryContinuationStore(),
    )


def _issue_continuation(service: OrchestrationEngineService) -> str:
    now = datetime.now(timezone.utc)
    pause = ApprovalPause(
        pause_id="pause_mirror_1",
        run_id="run_mirror_1",
        agent_runtime_id="agent:padiem:orchestrator_1",
        tool_id="calc",
        invocation_sha256="0" * 64,
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        trace_id="tr_orch_mirror",
    )
    return service._continuation_store.issue(app_id="b62", pause=pause, plan_id=None)


def _orchestrate_payload(service: OrchestrationEngineService, *, decision: bool = True) -> dict:
    payload = {
        "app_id": "b62",
        "agent": {
            "id": "agent:padiem:orchestrator_1",
            "title": "Orchestrator",
            "description": "Orchestrates execution",
            "system_instruction": "Execute tasks",
            "task_type": "general",
            "optimize_for": "balanced",
            "max_tokens": 2048,
            "model_policy": {"model": "test/route"},
        },
        "messages": [{"role": "user", "content": "Hello engine"}],
        "trace_id": "tr_orch_mirror",
        "execution_context": {"trace_id": "tr_orch_mirror", "timeout_seconds": 15.0},
        "continuation_ref": _issue_continuation(service),
    }
    if decision:
        payload["decision"] = {
            "decision_id": "dec_mirror_1",
            "pause_id": "pause_mirror_1",
            "outcome": "approved",
            "authority_ref": "user:admin",
            "evidence_ref": "session:auth",
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
    return payload


def _agent_skill_resume_lifecycle() -> list[dict[str, Any]]:
    fixture = PausedRunFixture()
    pause = _run(fixture.service.run_payload(fixture.run_payload()))
    assert pause.status_code == 202, pause.body
    ref = pause.body["continuation_ref"]
    pause_id = pause.body["agent_skill"]["approval_pause"]["continuation_id"]
    fixture.pre_confirmed = True
    resumed = _run(fixture.service.resume_payload(fixture.resume_payload(ref, pause_id)))
    assert resumed.status_code == 200, resumed.body
    return resumed.body["continuation"]["lifecycle_events"]


# --- T1: the two routes speak one lifecycle contract ------------------------


def test_t1_orchestrate_resume_lifecycle_matches_the_agent_skill_contract() -> None:
    service = _service()
    response = _run(service.resume_payload(_orchestrate_payload(service)))
    assert response.status_code == 200, response.body

    block = response.body["continuation"]
    assert block["lifecycle_contract_version"] == ENGINE_AGENT_LIFECYCLE_CONTRACT_VERSION

    events = block["lifecycle_events"]
    agent_skill_events = _agent_skill_resume_lifecycle()

    # Same transition vocabulary, same ordering rule, same shape on both routes.
    assert [event["kind"] for event in events] == ["resume_requested", "resumed"]
    assert [event["kind"] for event in events] == [
        event["kind"] for event in agent_skill_events
    ]
    assert [event["sequence"] for event in events] == [event["sequence"] for event in agent_skill_events]
    assert {frozenset(event) for event in events} == {frozenset(event) for event in agent_skill_events}
    assert {frozenset(event) for event in events} == {frozenset(LIFECYCLE_EVENT_KEYS)}
    assert [event["terminal"] for event in events] == [
        event["terminal"] for event in agent_skill_events
    ]

    # The id rule is the shared one, recomputed here independently: a route that
    # re-derived ids or ordering locally would fail this assertion.
    for index, event in enumerate(events, start=1):
        assert event["continuation_id"] == block["continuation_id"]
        assert event["event_id"] == _expected_event_id(
            continuation_id=block["continuation_id"],
            kind=event["kind"],
            sequence=index,
        )
    for index, event in enumerate(agent_skill_events, start=1):
        assert event["event_id"] == _expected_event_id(
            continuation_id=event["continuation_id"],
            kind=event["kind"],
            sequence=index,
        )
    assert events[0]["derived_from"] == agent_skill_events[0]["derived_from"] == "store_transition"
    assert events[0]["source_event_id"] is None

    # The orchestrate route carries no agent-skill selection, so it deliberately
    # projects no owner identity and no resume authority summary.
    assert "owner_identity" not in block
    assert "resume_authority" not in block


# --- T2: cancel keeps exactly one terminal lifecycle event ------------------


def test_t2_orchestrate_cancel_keeps_one_terminal_lifecycle_event() -> None:
    service = _service()
    ref = _issue_continuation(service)
    response = _run(
        service.cancel_payload({"app_id": "b62", "continuation_ref": ref, "reason": "user_cancelled"})
    )
    assert response.status_code == 200, response.body

    events = response.body["continuation"]["lifecycle_events"]
    assert [event["kind"] for event in events] == ["cancel_requested", "cancelled"]
    terminals = [event for event in events if event["terminal"]]
    assert len(terminals) == 1
    assert terminals[0]["kind"] == "cancelled"
    assert [event["sequence"] for event in events] == [1, 2]
    # Resume and cancel streams stay disjoint.
    assert "resumed" not in [event["kind"] for event in events]
    assert "resume_requested" not in [event["kind"] for event in events]
    for index, event in enumerate(events, start=1):
        assert event["event_id"] == _expected_event_id(
            continuation_id=response.body["continuation"]["continuation_id"],
            kind=event["kind"],
            sequence=index,
        )


# --- T3: existing response schema is unchanged (additive only) --------------


def test_t3_existing_orchestrate_response_schema_is_unchanged() -> None:
    service = _service()
    resumed = _run(service.resume_payload(_orchestrate_payload(service)))
    assert resumed.status_code == 200, resumed.body
    # The pre-existing envelope is still exactly there; the mirror only adds a sibling.
    assert resumed.body["ok"] is True
    assert set(resumed.body) - {"continuation"} == {"ok", "orchestration"}
    assert isinstance(resumed.body["orchestration"], dict)
    assert set(resumed.body["continuation"]) == ORCHESTRATE_CONTINUATION_BLOCK_KEYS

    other = _service()
    ref = _issue_continuation(other)
    cancelled = _run(
        other.cancel_payload({"app_id": "b62", "continuation_ref": ref, "reason": "user_cancelled"})
    )
    assert cancelled.status_code == 200
    assert set(cancelled.body) - {"continuation"} == {"ok", "status", "events"}
    assert cancelled.body["status"] == "cancelled"
    assert len(cancelled.body["events"]) == 1
    assert set(cancelled.body["continuation"]) == ORCHESTRATE_CONTINUATION_BLOCK_KEYS


def _plain_run_payload() -> dict:
    payload = _orchestrate_payload(_service(), decision=False)
    payload.pop("continuation_ref", None)
    return payload


# --- T4: no record -> no lifecycle (never invented) -------------------------


def test_t4_no_continuation_record_projects_no_lifecycle() -> None:
    # Unit level: the helper refuses to invent a lifecycle for a missing record.
    assert _orchestration_lifecycle_block(record=None, transition="resume", events=[]) is None

    # Response level: a plain orchestrate run has no continuation record at all,
    # so no lifecycle key may appear.
    service = _service()
    plain = _run(service.orchestrate_payload(_plain_run_payload()))
    assert plain.status_code == 200, plain.body
    assert "continuation" not in plain.body
    assert "lifecycle_events" not in json.dumps(plain.body)


# --- T5: no authority material or secret on the new surface -----------------


def test_t5_lifecycle_mirror_exposes_no_authority_material() -> None:
    service = _service()
    resumed = _run(service.resume_payload(_orchestrate_payload(service)))
    assert resumed.status_code == 200, resumed.body

    block = resumed.body["continuation"]
    serialized = json.dumps(block).lower()
    for marker in FORBIDDEN_MARKERS:
        assert marker not in serialized, marker
    for event in block["lifecycle_events"]:
        assert set(event) <= LIFECYCLE_EVENT_KEYS
        assert "subject_id" not in event
        assert "authority" not in event

    other = _service()
    ref = _issue_continuation(other)
    cancelled = _run(
        other.cancel_payload({"app_id": "b62", "continuation_ref": ref, "reason": "user_cancelled"})
    )
    cancelled_serialized = json.dumps(cancelled.body).lower()
    for marker in FORBIDDEN_MARKERS:
        assert marker not in cancelled_serialized, marker
