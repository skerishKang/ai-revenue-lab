
"""#5574: the real Chat chain ships the exact wire the Engine refuses for a wrong read.

The defect was measured twice on each side of the trust boundary:

* ``apps/padiem-ai-engine/tests/test_5574_pc_read_boundary_end_to_end.py`` runs
  the recorded Chat body through the real Engine service, the real PC step
  driver and the real tool handlers and measures that a listing-only turn whose
  model picks ``claw.pc.read_file`` produces zero read dispatches and the
  Engine's own refusal body: ``400`` with ``error.code = "agent_step_failed"``.
* This file runs the same turn from the other end — the shipped
  ``static/chat-transport.js`` in a real Node VM, the real ``/api/orchestration``
  route, the real PC lane, the real ``B62EngineOrchestrationBridge`` and the real
  ``PadiemAiEngineClient`` — and pins the body that client actually puts on the
  wire plus the refusal the user actually sees.

The two halves cannot share one Python process: ``apps/padiem-chat/app`` and
``apps/padiem-ai-engine/app`` are the same package name, which is the recorded
constraint behind ``tests/test_5015_chat_pc_engine_wire_fixture.py``. They join
on the wire: the plan/ceiling this file measures in the real client's body is
the plan/ceiling the Engine-side file executes, and the refusal body replayed
here is the byte-for-byte body measured there.

Only the Engine is substituted, and it is substituted at its own transport
seam: one recorded refusal (the measured body) or one recorded completion. The
model, the PC and every PC handler leg belong to the Engine-side file. No PC,
Mesh, provider or network call happens here.

A completion control runs the same chain so the measured refusal is attributable
to the Engine's scope decision rather than to a misbuilt request or transport:
when the Engine answers, the same real bridge, the same real client and the same
real lane render that answer and seal the run.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from padiem_ai_engine_client import (
    ENGINE_ORCHESTRATE_PATH,
    EngineTransportResponse,
    PadiemAiEngineClient,
)

from app.orchestration_bridge import B62EngineOrchestrationBridge

from test_5574_frontend_pc_route_harness import (
    CHROME_5574_TEXT,
    DEVICE_ID,
    SUBJECT_ID,
    _assert_b14_untouched,
    _has_call,
    _PcHarness,
    _run_flow,
)

CHAT_APP_ID = "padiem-chat"
PC_QUERY_AGENT_ID = "agent:padiem:chat-pc-query@1"
PC_PLAN_TOOL_IDS = ["claw.pc.list_files", "claw.pc.read_file"]

#: The Engine refusal measured on the real Engine chain in
#: test_5574_pc_read_boundary_end_to_end.py, replayed verbatim here.
ENGINE_REFUSAL_STATUS = 400
ENGINE_REFUSAL_BODY: dict[str, Any] = {
    "ok": False,
    "error": {
        "code": "agent_step_failed",
        "message": "Agent step execution failed.",
        "retryable": False,
        "metadata": None,
    },
}

ENGINE_ANSWER = "폴더에 2개 항목이 있습니다."
ENGINE_EXECUTOR_SUMMARY = "engine result payload 1"
_TRACE_RE = re.compile(r"^b62_orch_[0-9a-f]{24}$")


def _completed_body(*, run_id: str, trace_id: str) -> dict[str, Any]:
    """The Engine's completed orchestration body, in its measured event order.

    Field shape and kinds are the ones the real Engine emits (measured in the
    Engine-side file); only the ids are this turn's own.
    """
    kinds = [
        "run_started", "context_prepared", "plan_created", "tool_resolution",
        "tool_started", "tool_completed", "tool_started", "tool_completed",
        "run_completed",
    ]
    events = [
        {
            "event_id": f"evt_{index:012x}",
            "run_id": run_id,
            "trace_id": trace_id,
            "app_id": CHAT_APP_ID,
            "kind": kind,
            "sequence": sequence,
        }
        for index, (sequence, kind) in enumerate(zip(range(1, len(kinds) + 1), kinds), start=1)
    ]
    return {
        "ok": True,
        "orchestration": {
            "events": events,
            "approval_pause": None,
            "continuation_ref": None,
            "execution": {
                "answer": ENGINE_ANSWER,
                "metadata": {"status": "completed", "trace_id": trace_id},
            },
        },
    }


class _RecordedEngineTransport:
    """The Engine seam: records the real client's body, replays one Engine answer.

    ``completed`` also mirrors the executor result-summary write the lane
    requires before it may seal a run, exactly as the shared harness's
    ``_RecordingEngineBridge.start`` does. It is addressed by the ``session_id``
    this turn's own wire carries, so the row it stamps is the row the lane staged.
    """

    def __init__(self, *, outcome: str, store: Any) -> None:
        assert outcome in {"refused", "completed"}
        self._outcome = outcome
        self._store = store
        self.bodies: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.statuses: list[int] = []

    async def request(self, *, method: str, url: str, headers, body) -> EngineTransportResponse:
        payload = json.loads(body.decode("utf-8"))
        self.urls.append(url)
        self.bodies.append(payload)
        if self._outcome == "refused":
            status, response_body = ENGINE_REFUSAL_STATUS, ENGINE_REFUSAL_BODY
        else:
            run = self._store.runs.get(payload["session_id"])
            if run is not None and not run["result_summary"]:
                run["result_summary"] = ENGINE_EXECUTOR_SUMMARY
            status = 200
            response_body = _completed_body(
                run_id="orch_run_5574_frontend_control", trace_id=payload["trace_id"]
            )
        self.statuses.append(status)
        return EngineTransportResponse(
            status=status,
            headers={"content-type": "application/json"},
            body=json.dumps(response_body, ensure_ascii=False).encode("utf-8"),
        )


def _real_bridge(harness: _PcHarness, *, outcome: str) -> tuple[B62EngineOrchestrationBridge, _RecordedEngineTransport]:
    """The production composition: the real client over the recorded Engine seam."""
    transport = _RecordedEngineTransport(outcome=outcome, store=harness.store)
    client = PadiemAiEngineClient(
        transport=transport,
        app_id=CHAT_APP_ID,
        caller_id=CHAT_APP_ID,
        credential="x" * 64,
    )
    bridge = B62EngineOrchestrationBridge(client=client, store=object())
    harness.bridge = bridge
    return bridge, transport


def _flow(*, outcome: str):
    async def run():
        harness = _PcHarness()
        _, transport = _real_bridge(harness, outcome=outcome)
        steps = [{"messages": [{"role": "user", "content": CHROME_5574_TEXT}], "mint": True}]
        result = await _run_flow(harness, steps, orchestration=True)
        return harness, transport, result

    return asyncio.run(run())


def test_the_refused_wire_is_the_list_plus_read_ceiling_the_engine_executes() -> None:
    """The body the real client puts on the wire is the scope-bearing one.

    This is the join with the Engine-side file: the plan and the trusted hint
    asserted here are exactly the plan and hint that chain runs, so the
    measured zero-read-dispatch result is about this product turn.
    """
    harness, transport, result = _flow(outcome="refused")
    step = result["steps"][0]
    minted = step["pc_run_id"]

    assert transport.urls == ["https://padiem-ai-engine.internal" + ENGINE_ORCHESTRATE_PATH], transport.urls
    assert len(transport.bodies) == 1, transport.bodies
    sent = transport.bodies[0]

    assert sent["app_id"] == CHAT_APP_ID
    assert sent["subject_id"] == SUBJECT_ID
    assert sent["session_id"] == minted
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE_ID}}
    assert sent["agent_plan"]["agent_id"] == PC_QUERY_AGENT_ID
    assert [s["tool_id"] for s in sent["agent_plan"]["steps"]] == PC_PLAN_TOOL_IDS
    assert [s["step_id"] for s in sent["agent_plan"]["steps"]] == ["list_files", "read_file"]
    assert sent["max_retries"] == 3
    assert sent["require_evidence"] is False
    assert sent["require_verification"] is False
    assert sent["agent"]["id"] == "b62_auto"
    assert sent["messages"] == [{"role": "user", "content": CHROME_5574_TEXT}]
    assert _TRACE_RE.fullmatch(sent["trace_id"]), sent["trace_id"]
    assert sent["execution_context"] == {"trace_id": sent["trace_id"]}

    # The lane never reaches a model, a PC, or a second Engine attempt.
    _assert_b14_untouched(harness)
    assert transport.statuses == [ENGINE_REFUSAL_STATUS]


def test_a_refused_pc_turn_is_a_refusal_and_never_a_general_answer() -> None:
    """The user sees the Engine's refusal; the turn is not silently re-asked.

    ``chat-transport.js`` falls back to ``/api/chat/stream`` only for
    ``orchestration_not_applicable``. A scope refusal must not turn into a
    general chat answer, and the staged PC run must not read as completed.
    """
    harness, transport, result = _flow(outcome="refused")
    step = result["steps"][0]
    minted = step["pc_run_id"]

    assert step["generic_error"] is not None, step
    assert step["generic_error"]["code"] == "chat_pc_engine_unavailable", step["generic_error"]
    assert step["answer"] == "", step
    assert step["events"] == [], step

    refused = [
        call for call in step["calls"]
        if call["method"] == "POST" and call["path"] == "/api/orchestration"
    ]
    assert len(refused) == 1, step["calls"]
    assert refused[0]["status"] == ENGINE_REFUSAL_STATUS, refused

    # No fallback leg: the ordinary streaming route was never asked to answer.
    assert not _has_call(step, "POST", "/api/chat/stream"), step["calls"]
    assert len(transport.bodies) == 1, transport.bodies

    row = harness.store.runs[minted]
    assert row["status"] != "completed", row
    _assert_b14_untouched(harness)


def test_the_same_real_chain_completes_when_the_engine_answers() -> None:
    """Control: the refusal above is the Engine's decision, not a broken seam.

    Identical frontend, route, lane, bridge and client. Only the recorded Engine
    answer changes, and the run completes with that answer shown.
    """
    harness, transport, result = _flow(outcome="completed")
    step = result["steps"][0]
    minted = step["pc_run_id"]

    assert step["generic_error"] is None, step
    assert step["answer"] == ENGINE_ANSWER, step
    assert step["events"] == ["delta", "done"], step
    assert transport.statuses == [200], transport.statuses
    assert not _has_call(step, "POST", "/api/chat/stream"), step["calls"]

    sent = transport.bodies[0]
    assert sent["tool_arguments"] == {"files": {"device_id": DEVICE_ID}}
    assert [s["tool_id"] for s in sent["agent_plan"]["steps"]] == PC_PLAN_TOOL_IDS

    row = harness.store.runs[minted]
    assert row["status"] == "completed", row
    assert row["result_summary"] == ENGINE_EXECUTOR_SUMMARY, row
    assert row["conversation_id"] == step["conversation_id"], row
    _assert_b14_untouched(harness)
