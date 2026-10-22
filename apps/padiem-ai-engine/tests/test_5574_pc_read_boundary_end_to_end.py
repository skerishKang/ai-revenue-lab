"""#5574: a listing-only Chat turn cannot reach a read dispatch, end to end.

The defect was measured at the step policy (test_5574_pc_read_scope_leak.py).
This file proves the same refusal across every leg the product actually runs,
so a fix that only satisfies the policy unit test cannot pass here:

    real PadiemAiEngineClient.orchestrate      (the client Chat itself uses)
    -> real AdmissionBoundOrchestrationEngineService.orchestrate_payload
       (trusted admission, the owner/run/device binding, the real runner)
    -> real Core plan bridge and BoundedAgentRuntime
    -> real build_live_pc_query_driver / StructuredPCQueryStepDriver
    -> real ToolRuntime PC handlers over the real signed dispatch legs
    -> a recording fake PC endpoint

Exactly two things are fake, as the work order requires: the model step (a
scripted B14 that answers a listing without intent and then a wrong read) and
the PC endpoint behind the signed callback. No PC, Mesh, provider or network
call happens.

The request is not hand-written either. It is the recorded Chat wire that
``apps/padiem-chat/tests/test_5015_chat_pc_engine_wire_fixture.py`` keeps
byte-identical to what the production builders and this same client emit, with
only the user text (the listing-only sentence the frontend harness sends) and
the run handle swapped. The first test pins every remaining field against that
record, so the list+read ceiling and the two-step plan this chain executes are
the ones the Chat lane really ships.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from padiem_ai_engine_client import (
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)
from padiem_ai_core.pc_device_identity import is_pc_device_id

from app.claw_pc_query_step_driver import (
    build_chat_pc_query_tool_binding,
    build_live_pc_query_driver,
)
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from tests.test_5015_chat_pc_wire_admission import AllowingAdapter
from tests.test_canonical_idempotency_identity import ReplayAdapter

FIXTURE = Path(__file__).with_name("fixtures") / "5015_chat_pc_engine_payloads.json"
FILES_RECORD = json.loads(FIXTURE.read_text(encoding="utf-8"))["files"]
CHAT_APP_ID = "padiem-chat"

# The listing-only sentence the real frontend sends on this lane, and the run
# handle shape ``createChatPcRunId`` mints. The device target stays the one the
# record carries; #5172 owns the identity grammar across every boundary.
LISTING_ONLY_TEXT = "내PC office-pc 폴더에서 파일 목록 보여줘"
LISTING_ONLY_RUN = "chat_pcq_" + "5" * 32

# The shape the listing command really returns (Select-Object rows with no
# relative_path), so the handler's projection hands the model a readable path.
LIST_WIRE_ROWS = (
    "["
    "{\"Name\":\"meshcentral-padiem-trial.txt\",\"Length\":113,"
    "\"LastWriteTimeUtc\":\"2026-10-19T09:00:00Z\",\"PSIsContainer\":false},"
    "{\"Name\":\"notes\",\"Length\":null,"
    "\"LastWriteTimeUtc\":\"2026-10-19T09:00:00Z\",\"PSIsContainer\":true}"
    "]"
)
READ_OUTPUT = "meshcentral trial content"
READ_TARGET = "meshcentral-padiem-trial.txt"
# A local signing value for a fake endpoint. It is not a credential.
SIGNING_SECRET = "5574-issue-local-signing-secret-not-a-real-credential"

LIST_STEP = json.dumps(
    {"action": "tool", "tool_id": "claw.pc.list_files", "arguments": {"path": "."}},
    ensure_ascii=False,
)
LIST_STEP_WITH_READ_INTENT = json.dumps(
    {
        "action": "tool", "tool_id": "claw.pc.list_files",
        "arguments": {"path": ".", "intent": "read"},
    },
    ensure_ascii=False,
)
WRONG_READ_STEP = json.dumps(
    {"action": "tool", "tool_id": "claw.pc.read_file", "arguments": {"path": READ_TARGET}},
    ensure_ascii=False,
)
COMPLETE_STEP = json.dumps(
    {"action": "complete", "answer": "폴더에 2개 항목이 있습니다."},
    ensure_ascii=False,
)


class _Request:
    """The Worker ``Request`` shape the signed callback builds through."""

    def __init__(self, url, *, method, headers, body):
        self.url = url
        self.method = method
        self.headers = headers
        self.body = body
        self.js_object = self


class _Response:
    def __init__(self, payload: dict) -> None:
        self._text = json.dumps(payload, ensure_ascii=False)
        self.status = 200

    async def text(self) -> str:
        return self._text


class _FakePcEndpoint:
    """The owner's PC behind the signed Chat callback, with every leg recorded.

    Each dispatch is a row this fake mints, and the status/result legs are
    addressed by that dispatch id only, so the handler's own correlation checks
    run for real. Nothing here can reach a PC, and an op this endpoint never
    received is a dispatch that never happened.
    """

    def __init__(self) -> None:
        self.legs: list[dict] = []
        self.rows: dict[str, dict] = {}

    @property
    def dispatches(self) -> list[dict]:
        return [leg for leg in self.legs if leg["mode"] == "dispatch"]

    @property
    def ops(self) -> list[str]:
        return [leg["op"] for leg in self.dispatches]

    @property
    def modes(self) -> list[str]:
        return [leg["mode"] for leg in self.legs]

    async def fetch(self, request: _Request) -> _Response:
        body = json.loads(request.body)
        self.legs.append(body)
        mode = body["mode"]
        if mode == "context":
            return _Response({
                "ok": True,
                "device": {"device_id": body["device_id"], "state": "CONNECTED"},
                "tools": ["list_files", "read_file"],
            })
        if mode == "dispatch":
            op = body["op"]
            if op not in {"list", "read"}:
                raise AssertionError("unexpected PC op " + str(op))
            kind = "read" if op == "read" else "command"
            dispatch_id = f"dsp_5574_{len(self.rows) + 1}"
            output = LIST_WIRE_ROWS if op == "list" else READ_OUTPUT
            self.rows[dispatch_id] = {
                "run_id": body["run_id"], "kind": kind, "op": op, "output": output,
                "content_bytes": len(output.encode("utf-8")),
            }
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": dispatch_id, "run_id": body["run_id"],
                "kind": kind, "device_id": body["device_id"],
            }})
        row = self.rows.get(body["dispatch_id"])
        if row is None:
            raise AssertionError("unknown dispatch id " + str(body["dispatch_id"]))
        if mode == "command_status":
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": body["dispatch_id"], "run_id": row["run_id"],
                "kind": row["kind"], "state": "done",
            }})
        if mode == "result":
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": body["dispatch_id"], "run_id": row["run_id"],
                "kind": row["kind"], "output": row["output"],
                "result_sha256": "a" * 64, "content_sha256": "a" * 64,
                "content_bytes": row["content_bytes"],
                "termination": "exited" if row["kind"] == "read" else "no_exit_code",
                "exit_code": 0 if row["kind"] == "read" else None,
            }})
        raise AssertionError("unexpected PC mode " + str(mode))


class _ScriptedModel:
    """Fake B14 for the step prompt: answers from a script, never a provider."""

    def __init__(self, answers: list[str]) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []

    async def execute(self, request):
        self.prompts.append(request.messages[0]["content"])
        if not self._answers:
            raise AssertionError("the model step ran past its script")
        return SimpleNamespace(answer=self._answers.pop(0))


class _NoModelLaneRuntime:
    """The PC plan lane must be taken; the single-shot model lane never runs."""

    async def run(self, request):
        raise AssertionError("the non-plan model lane must not run for a PC plan")


async def _instant_sleep(_seconds: float, *args, **kwargs) -> None:
    return None


def _bridge_request() -> dict:
    """The recorded Chat wire, with only the turn text and the run handle swapped."""
    request = {key: value for key, value in FILES_RECORD.items() if key != "app_id"}
    request["messages"] = [{"role": "user", "content": LISTING_ONLY_TEXT}]
    request["session_id"] = LISTING_ONLY_RUN
    return request


def _chain(*, model: _ScriptedModel, pc: _FakePcEndpoint):
    """The production composition, with only the two fakes the work order allows."""
    binding = build_chat_pc_query_tool_binding(
        service=pc, request_factory=_Request, secret=SIGNING_SECRET,
    )

    # Mirrors worker_identity's pc_query_step_driver_factory wiring, including
    # the positional argument shape the service calls it with.
    def factory(model_id, model_policy, task_type, optimize_for, tool_arguments=None):
        return build_live_pc_query_driver(
            b14_client=model, model_id=model_id, model_policy=model_policy,
            task_type=task_type, optimize_for=optimize_for,
            service=pc, request_factory=_Request, secret=SIGNING_SECRET,
            tool_arguments=tool_arguments,
        )

    return AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: _NoModelLaneRuntime(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        idempotency_adapter=ReplayAdapter(),
        tool_binding_resolver=lambda app_id: binding if app_id == CHAT_APP_ID else None,
        pc_query_step_driver_factory=factory,
    )


class _InProcessEngineTransport:
    """Carries the real client body to the real Engine service and back."""

    def __init__(self, service) -> None:
        self._service = service
        self.bodies: list[dict] = []
        self.statuses: list[int] = []
        self.urls: list[str] = []
        self.response_bodies: list[dict] = []

    async def request(self, *, method, url, headers, body):
        assert method == "POST"
        self.urls.append(url)
        payload = json.loads(body.decode("utf-8"))
        self.bodies.append(payload)
        response = await self._service.orchestrate_payload(payload)
        self.statuses.append(response.status_code)
        encoded = json.dumps(response.body, ensure_ascii=False).encode("utf-8")
        self.response_bodies.append(json.loads(encoded))
        return EngineTransportResponse(
            status=response.status_code,
            headers={"content-type": "application/json"},
            body=encoded,
        )


def _transport_for(*, model: _ScriptedModel, pc: _FakePcEndpoint) -> _InProcessEngineTransport:
    return _InProcessEngineTransport(_chain(model=model, pc=pc))


def _orchestrate(transport: _InProcessEngineTransport) -> dict:
    """One turn through the real client, with the handler's PC wait bounded."""
    client = PadiemAiEngineClient(
        transport=transport, app_id=CHAT_APP_ID, caller_id=CHAT_APP_ID,
        credential="x" * 64,
    )
    with patch.object(asyncio, "sleep", _instant_sleep):
        return asyncio.run(client.orchestrate(_bridge_request()))


def _without_turn(payload: dict) -> dict:
    rest = dict(payload)
    rest.pop("messages")
    rest.pop("session_id")
    return rest


def test_the_engine_executes_the_ceiling_and_plan_the_chat_lane_ships() -> None:
    """The wire this chain runs on is the live Chat body, not a hand-made dict."""
    assert is_pc_device_id(FILES_RECORD["tool_arguments"]["files"]["device_id"])
    assert [step["tool_id"] for step in FILES_RECORD["agent_plan"]["steps"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ]

    pc = _FakePcEndpoint()
    transport = _transport_for(model=_ScriptedModel([LIST_STEP, WRONG_READ_STEP]), pc=pc)
    with pytest.raises(PadiemAiEngineClientError):
        _orchestrate(transport)

    assert len(transport.bodies) == 1
    assert transport.urls[0].endswith("/internal/v1/orchestrate"), transport.urls
    sent = transport.bodies[0]
    assert sent["app_id"] == CHAT_APP_ID
    assert sent["agent_plan"] == FILES_RECORD["agent_plan"]
    assert sent["tool_arguments"] == FILES_RECORD["tool_arguments"]
    assert _without_turn(sent) == _without_turn(FILES_RECORD)
    assert sent["messages"] == [{"role": "user", "content": LISTING_ONLY_TEXT}]
    assert sent["session_id"] == LISTING_ONLY_RUN
    assert sent["execution_context"] == {"trace_id": sent["trace_id"]}


def test_a_listing_only_turn_with_a_wrong_read_selects_zero_read_dispatches() -> None:
    """The user asked for a listing; the model's wrong read must not execute.

    Measured on the handler side rather than on the policy side: the folder
    listing runs and returns a genuinely readable ``relative_path``, the model
    then names that exact path for ``claw.pc.read_file``, and the signed PC
    endpoint still receives exactly one dispatch, for the listing.
    """
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, WRONG_READ_STEP])
    transport = _transport_for(model=model, pc=pc)

    with pytest.raises(PadiemAiEngineClientError) as refusal:
        _orchestrate(transport)

    # The claim itself: the signed PC endpoint got the listing and nothing else.
    assert pc.ops == ["list"], pc.dispatches
    assert pc.modes == ["context", "dispatch", "command_status", "result"], pc.modes

    # The refusal crosses the real client as the Engine's own bounded code.
    assert refusal.value.code == "agent_step_failed"
    assert refusal.value.status == 400
    assert refusal.value.retryable is False
    assert transport.statuses == [400]
    # Measured Engine body. The Chat-side boundary regression replays these
    # exact bytes: apps/padiem-chat/tests/test_5574_frontend_pc_engine_wire_boundary.py
    assert transport.response_bodies == [{
        "ok": False,
        "error": {
            "code": "agent_step_failed",
            "message": "Agent step execution failed.",
            "retryable": False,
            "metadata": None,
        },
    }], transport.response_bodies

    # The wrong read was reachable, not scripted away: the second step prompt
    # carried the projected path the read step then named.
    assert len(model.prompts) == 2
    assert READ_TARGET in model.prompts[1]
    assert "relative_path" in model.prompts[1]


def test_an_explicit_read_intent_still_reaches_the_read_dispatch() -> None:
    """Differential proof: the gate closes on the unauthorized read only.

    Same chain, same ceiling, same plan. When the model declares the read the
    user actually asked for, the read handler runs and the dispatch happens, so
    the refusal above is a scope decision and not a broken lane.
    """
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP_WITH_READ_INTENT, WRONG_READ_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)

    orchestration = _orchestrate(transport)

    assert transport.statuses == [200], transport.statuses
    assert pc.ops == ["list", "read"], pc.dispatches
    execution = orchestration["execution"]
    assert execution["metadata"]["status"] == "completed", execution["metadata"]
    assert execution["answer"] == "폴더에 2개 항목이 있습니다.", execution
    assert [event["tool_id"] for event in execution["metadata"]["tool_events"]] == [
        "claw.pc.list_files", "claw.pc.read_file",
    ], execution["metadata"]["tool_events"]
    assert [event["status"] for event in execution["metadata"]["tool_events"]] == [
        "completed", "completed",
    ], execution["metadata"]["tool_events"]
    assert len(model.prompts) == 3
    read_legs = [
        leg for leg in pc.dispatches if leg["op"] == "read"
    ]
    assert [leg["path"] for leg in read_legs] == [READ_TARGET], read_legs
