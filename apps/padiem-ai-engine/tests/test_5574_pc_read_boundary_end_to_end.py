"""#5574: admitted ceiling and optional narrowing intent across the real wire.

The recorded Chat request runs through the real Engine admission, Core agent
runtime, step driver, authorization and signed tool handlers. Scripted model
answers and a recording PC endpoint replace all provider and PC calls.

The full-plan record remains the shape Chat currently emits. List-only plan
admission (A1) and refusal before read dispatch (A3) are retained separately.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from padiem_ai_core.pc_device_identity import is_pc_device_id
from padiem_ai_core.tool_runtime import ToolRuntime

from app.claw_pc_query_step_driver import (
    build_chat_pc_query_tool_binding,
    build_live_pc_query_driver,
)
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from tests.test_5015_chat_pc_wire_admission import AllowingAdapter
from tests.test_canonical_idempotency_identity import ReplayAdapter

# The Engine env does not install the Python client: it is a path sibling. The
# insert is what test_5015_engine_refusal_code_observability.py does, repeated
# here so this file runs alone instead of only after that module is collected.
CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(CLIENT_ROOT))

from padiem_ai_engine_client import (  # noqa: E402
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)

FIXTURE = Path(__file__).with_name("fixtures") / "5015_chat_pc_engine_payloads.json"
FILES_RECORD = json.loads(FIXTURE.read_text(encoding="utf-8"))["files"]
CHAT_APP_ID = "padiem-chat"
DEVICE_ID = FILES_RECORD["tool_arguments"]["files"]["device_id"]

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
    {"plan": "files", "action": "tool", "tool_id": "claw.pc.list_files", "arguments": {"path": "."}},
    ensure_ascii=False,
)
LIST_STEP_WITH_READ_INTENT = json.dumps(
    {
        "plan": "files", "action": "tool", "tool_id": "claw.pc.list_files",
        "arguments": {"path": ".", "intent": "read"},
    },
    ensure_ascii=False,
)
WRONG_READ_STEP = json.dumps(
    {"action": "tool", "tool_id": "claw.pc.read_file", "arguments": {"path": READ_TARGET}},
    ensure_ascii=False,
)
READ_STEP_WITH_LIST_INTENT = json.dumps(
    {"action": "tool", "tool_id": "claw.pc.read_file",
     "arguments": {"path": READ_TARGET, "intent": "list"}},
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
        self.requests: list[_Request] = []
        self.rows: dict[str, dict] = {}
        self.claims: list[dict] = []

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
        import hashlib
        import hmac
        self.requests.append(request)
        encoded = request.headers.get("X-Claw-PC-Scope")
        if encoded is not None:
            proof = hmac.new(SIGNING_SECRET.encode(),
                request.headers["X-Claw-Engine-Time"].encode() + b"." + request.body.encode() + b"." + encoded.encode(),
                hashlib.sha256).hexdigest()
            assert request.headers["X-Claw-PC-Scope-Proof"] == proof
            self.claims.append(json.loads(encoded))
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


def _chain(*, model: _ScriptedModel, pc: _FakePcEndpoint, allow_read=True):
    """The production composition, with only the two fakes the work order allows."""
    binding = build_chat_pc_query_tool_binding(
        service=pc, request_factory=_Request, secret=SIGNING_SECRET,
    )
    if not allow_read:
        authority = binding.authorities["agent:padiem:chat-pc-query@1"]
        binding.authorities["agent:padiem:chat-pc-query@1"] = replace(
            authority, authorization=replace(authority.authorization,
                granted_auth_scopes=tuple(scope for scope in authority.authorization.granted_auth_scopes
                                          if scope != "claw.pc.read_file")),
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


def _orchestrate(transport: _InProcessEngineTransport, *, selected_device: bool = True) -> dict:
    """One turn through the real client, with the handler's PC wait bounded."""
    client = PadiemAiEngineClient(
        transport=transport, app_id=CHAT_APP_ID, caller_id=CHAT_APP_ID,
        credential="x" * 64,
    )
    request = _bridge_request()
    if not selected_device:
        request.pop("tool_arguments", None)
    with patch.object(asyncio, "sleep", _instant_sleep):
        return asyncio.run(client.orchestrate(request))


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
    transport = _transport_for(
        model=_ScriptedModel([LIST_STEP, WRONG_READ_STEP, COMPLETE_STEP]), pc=pc,
    )
    _orchestrate(transport)
    assert transport.statuses == [200]
    assert pc.ops == ["list", "read"]

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


def test_a_list_intent_read_step_selects_zero_read_dispatches() -> None:
    """A model step narrowed to listing cannot execute a read.

    Measured on the handler side rather than on the policy side: the folder
    listing runs and returns a genuinely readable ``relative_path``, the model
    then names that exact path for ``claw.pc.read_file``, and the signed PC
    endpoint still receives exactly one dispatch, for the listing.
    """
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, READ_STEP_WITH_LIST_INTENT, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)

    result = _orchestrate(transport)

    # The claim itself: the signed PC endpoint got the listing and nothing else.
    assert pc.ops == ["list"], pc.dispatches
    assert pc.modes == ["context", "context", "dispatch", "command_status", "result"], pc.modes

    # The slice-2 refusal is returned to the model in the same run, not a 400.
    assert transport.statuses == [200]
    assert result["execution"]["metadata"]["status"] == "completed"
    assert "pc_scope_denied" in model.prompts[2]

    # The wrong read was reachable, not scripted away: the second step prompt
    # carried the projected path the read step then named.
    assert len(model.prompts) == 3
    assert READ_TARGET in model.prompts[1]
    assert "relative_path" in model.prompts[1]


def _list_only_request() -> dict:
    """The existing client-admitted one-step plan and its closed scope hint."""
    request = _bridge_request()
    request["tool_arguments"] = {"files_list": {"device_id": DEVICE_ID}}
    plan = dict(request["agent_plan"])
    plan["steps"] = [
        step for step in request["agent_plan"]["steps"]
        if step["tool_id"] == "claw.pc.list_files"
    ]
    request["agent_plan"] = plan
    return request


def _orchestrate_list_only(transport, *, selected_device=True) -> dict:
    request = _list_only_request()
    if not selected_device:
        request.pop("tool_arguments")
    client = PadiemAiEngineClient(
        transport=transport, app_id=CHAT_APP_ID, caller_id=CHAT_APP_ID,
        credential="x" * 64,
    )
    with patch.object(asyncio, "sleep", _instant_sleep):
        return asyncio.run(client.orchestrate(request))


def test_a_list_only_ceiling_is_admitted_on_the_real_wire() -> None:
    """The canonical list-only plan reaches the real driver and signed handler."""
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)

    orchestration = _orchestrate_list_only(transport)

    assert transport.statuses == [200]
    assert pc.ops == ["list"], pc.dispatches
    assert pc.modes == ["context", "context", "dispatch", "command_status", "result"]
    assert len(model.prompts) == 2
    assert orchestration["execution"]["metadata"]["status"] == "completed"


@pytest.mark.parametrize("selected_device", [True, False])
def test_an_admitted_list_only_plan_refuses_read_intent_before_dispatch(
    selected_device: bool,
) -> None:
    """Even intent:read cannot widen the admitted plan, with or without a target."""
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP_WITH_READ_INTENT, WRONG_READ_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)

    result = _orchestrate_list_only(transport, selected_device=selected_device)
    assert result["execution"]["metadata"]["status"] == "completed"
    assert transport.statuses == [200]
    # Admission succeeded: the model and list handler ran before the step gate.
    assert len(model.prompts) == 3
    assert "pc_scope_denied" in model.prompts[2]
    assert all(claim["ops"] == ["list"] for claim in pc.claims)
    assert pc.claims
    assert READ_TARGET in model.prompts[1]
    assert "read_file is not available" in model.prompts[0]
    assert pc.ops == ["list"], pc.dispatches
    assert len([leg for leg in pc.dispatches if leg["op"] == "read"]) == 0
    assert pc.modes == ["context", "context", "dispatch", "command_status", "result"]
    target = DEVICE_ID if selected_device else None
    assert [leg["device_id"] for leg in pc.legs if leg["mode"] in {"context", "dispatch"}] == [
        target, target, target,
    ]


def test_an_explicit_read_intent_still_reaches_the_read_dispatch() -> None:
    """Differential proof: the gate closes on the unauthorized read only.

    Same chain and full ceiling: optional read intent has no effect. The read
    handler still runs through authorization and the signed callback.
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


@pytest.mark.parametrize(
    "list_only,intent,allowed",
    [
        pytest.param(True, "read", False, id="1-list-only-read-intent-denied"),
        pytest.param(True, None, False, id="2-list-only-missing-intent-denied"),
        pytest.param(False, None, True, id="3-full-missing-intent-authorized"),
        pytest.param(False, "list", False, id="4-full-list-intent-denied"),
        pytest.param(False, "read", True, id="5-full-read-intent-authorized"),
    ],
)
@pytest.mark.parametrize("selected_device", [True, False], ids=["target", "no-target"])
def test_admitted_ceiling_and_optional_step_intent(
    list_only, intent, allowed, selected_device, monkeypatch,
) -> None:
    """The five Owner cases traverse admission, the step gate and real auth."""
    read = json.loads(WRONG_READ_STEP)
    if intent is not None:
        read["arguments"]["intent"] = intent
    answers = [LIST_STEP, json.dumps(read), COMPLETE_STEP]
    pc = _FakePcEndpoint()
    model = _ScriptedModel(answers)
    transport = _transport_for(model=model, pc=pc)
    run = _orchestrate_list_only if list_only else _orchestrate
    original_execute = ToolRuntime.execute
    read_authorizations = []

    async def observed_execute(runtime, invocation, agent_profile, authorization):
        if invocation.tool_id == "claw.pc.read_file":
            read_authorizations.append(authorization.granted_auth_scopes)
        return await original_execute(runtime, invocation, agent_profile, authorization)

    monkeypatch.setattr(ToolRuntime, "execute", observed_execute)
    if allowed:
        result = run(transport, selected_device=selected_device)
        assert result["execution"]["metadata"]["status"] == "completed"
        assert transport.statuses == [200]
        assert pc.ops == ["list", "read"]
        assert len(read_authorizations) == 1
        assert "claw.pc.read_file" in read_authorizations[0]
    else:
        result = run(transport, selected_device=selected_device)
        assert result["execution"]["metadata"]["status"] == "completed"
        assert transport.statuses == [200]
        assert pc.ops == ["list"]
        assert read_authorizations == []
        assert len(model.prompts) == 3
        assert "pc_scope_denied" in model.prompts[2]

    # Case 3 also removes the server-granted read scope in a differential run.
    # Real ToolRuntime authorization must refuse it before a read dispatch.
    if not list_only and intent is None:
        denied_codes = []

        async def without_read_scope(runtime, invocation, agent_profile, authorization):
            if invocation.tool_id == "claw.pc.read_file":
                authorization = replace(
                    authorization,
                    granted_auth_scopes=tuple(
                        scope for scope in authorization.granted_auth_scopes
                        if scope != "claw.pc.read_file"
                    ),
                )
            try:
                return await original_execute(runtime, invocation, agent_profile, authorization)
            except Exception as exc:
                denied_codes.append(getattr(exc, "code", None))
                raise

        monkeypatch.setattr(ToolRuntime, "execute", without_read_scope)
        denied_pc = _FakePcEndpoint()
        denied_transport = _transport_for(
            model=_ScriptedModel(answers), pc=denied_pc,
        )
        with pytest.raises(PadiemAiEngineClientError):
            run(denied_transport, selected_device=selected_device)
        assert denied_codes == ["tool_auth_scope_missing"]
        assert denied_pc.ops == ["list"]


@pytest.mark.parametrize("declared", [True, False], ids=["declared", "derived-first-decision"])
def test_request_scope_list_is_fixed_across_later_read_and_plan(declared):
    first = json.loads(LIST_STEP_WITH_READ_INTENT)
    if declared:
        first["plan"] = "files_list"
    else:
        first.pop("plan")
    later = json.loads(WRONG_READ_STEP)
    later["plan"] = "files"
    later["arguments"]["intent"] = "read"
    pc = _FakePcEndpoint()
    model = _ScriptedModel([json.dumps(first), json.dumps(later), COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)
    result = _orchestrate(transport)
    assert transport.statuses == [200]
    assert result["execution"]["metadata"]["status"] == "completed"
    assert pc.ops == ["list"]
    assert len(model.prompts) == 3  # No classifier or duplicate first B14 call.
    assert "pc_scope_denied" in model.prompts[-1]
    assert pc.claims and all(c["requested"] == c["admitted"] == "files_list" for c in pc.claims)
    assert all(c["ops"] == ["list"] for c in pc.claims)
    assert all(c["source"] == ("declared" if declared else "decision") for c in pc.claims)


def test_missing_scope_and_first_decision_is_an_observation_not_user_400():
    pc = _FakePcEndpoint()
    model = _ScriptedModel([json.dumps({"action": "unknown"}), COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)
    result = _orchestrate(transport)
    assert transport.statuses == [200]
    assert result["execution"]["metadata"]["status"] == "completed"
    assert pc.ops == []
    assert len(model.prompts) == 2
    assert '"admitted": "none"' in model.prompts[1]
    assert "pc_scope_denied" in model.prompts[1]


def test_request_files_is_reduced_by_server_read_permission_before_dispatch():
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, WRONG_READ_STEP, COMPLETE_STEP])
    transport = _InProcessEngineTransport(_chain(model=model, pc=pc, allow_read=False))
    result = _orchestrate(transport)
    assert transport.statuses == [200]
    assert result["execution"]["metadata"]["status"] == "completed"
    assert pc.ops == ["list"]
    assert pc.claims and all(c["requested"] == "files" and c["admitted"] == "files_list" for c in pc.claims)
    assert all(c["ops"] == ["list"] for c in pc.claims)
    assert "pc_scope_denied" in model.prompts[-1]


def test_old_chat_wire_and_new_engine_keep_closed_body_and_optional_scope_headers():
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, WRONG_READ_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)
    _orchestrate(transport)
    assert pc.ops == ["list", "read"]
    assert set(pc.dispatches[0]) == {"subject_id", "run_id", "device_id", "mode", "op", "path", "tool_call_ref"}
    assert pc.claims and all(c["admitted"] == "files" for c in pc.claims)
    assert len(model.prompts) == 3
    # Freeze the pre-scope wire serialization, not just the decoded key set.
    # In particular, the second context request adds headers to the first
    # request's exact legacy bytes; no plan/claim enters any JSON body.
    legacy_fields = {
        "context": ("device_id", "mode", "run_id", "subject_id"),
        "dispatch": ("device_id", "mode", "op", "path", "run_id", "subject_id", "tool_call_ref"),
        "command_status": ("dispatch_id", "mode", "run_id", "subject_id"),
        "result": ("dispatch_id", "mode", "run_id", "subject_id"),
    }
    for request, leg in zip(pc.requests, pc.legs, strict=True):
        expected = json.dumps({key: leg[key] for key in legacy_fields[leg["mode"]]},
                              separators=(",", ":")).encode("utf-8")
        assert request.body.encode("utf-8") == expected
    context_requests = [request for request, leg in zip(pc.requests, pc.legs, strict=True)
                        if leg["mode"] == "context"]
    assert len(context_requests) == 2
    assert "X-Claw-PC-Scope" not in context_requests[0].headers
    assert "X-Claw-PC-Scope" in context_requests[1].headers
    assert context_requests[0].body.encode("utf-8") == context_requests[1].body.encode("utf-8")


def test_scope_decision_reuses_first_call_with_conversation_and_selected_model():
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)
    request = _bridge_request()
    request["additional_system_context"] = "Prior user: list the same approved folder only."
    client = PadiemAiEngineClient(transport=transport, app_id=CHAT_APP_ID,
        caller_id=CHAT_APP_ID, credential="x" * 64)
    with patch.object(asyncio, "sleep", _instant_sleep):
        asyncio.run(client.orchestrate(request))
    assert len(model.prompts) == 2
    assert "Prior user: list the same approved folder only." in model.prompts[0]
    assert transport.bodies[0]["agent"] == FILES_RECORD["agent"]


def test_separate_runs_do_not_reuse_the_previous_turn_ceiling():
    first = json.loads(LIST_STEP)
    first["plan"] = "files_list"
    for step, expected in ((json.dumps(first), ["list"]), (LIST_STEP, ["list", "read"])):
        pc = _FakePcEndpoint()
        model = _ScriptedModel([step, WRONG_READ_STEP, COMPLETE_STEP])
        _orchestrate(_transport_for(model=model, pc=pc))
        assert pc.ops == expected
        assert pc.claims and pc.claims[0]["ops"] == expected



def _orchestrate_declared(transport, declared_plan, *, selected_device=True):
    request = _bridge_request()
    request["declared_plan"] = declared_plan
    if not selected_device:
        request.pop("tool_arguments")
    client = PadiemAiEngineClient(
        transport=transport, app_id=CHAT_APP_ID, caller_id=CHAT_APP_ID, credential="x" * 64,
    )
    with patch.object(asyncio, "sleep", _instant_sleep):
        return asyncio.run(client.orchestrate(request))


@pytest.mark.parametrize("selected_device", [True, False])
def test_external_list_declaration_precedes_model_plan_and_blocks_read(selected_device):
    pc = _FakePcEndpoint()
    read = json.loads(WRONG_READ_STEP)
    read.update(plan="files")
    read["arguments"]["intent"] = "read"
    model = _ScriptedModel([LIST_STEP, json.dumps(read), COMPLETE_STEP])
    original_execute = model.execute

    async def observe_admitted_before_model(request):
        assert pc.claims and pc.claims[-1]["admitted"] == "files_list"
        return await original_execute(request)

    model.execute = observe_admitted_before_model
    transport = _transport_for(model=model, pc=pc)
    result = _orchestrate_declared(transport, "files_list", selected_device=selected_device)
    assert result["execution"]["metadata"]["status"] == "completed"
    assert transport.statuses == [200]
    assert transport.bodies[0]["declared_plan"] == "files_list"
    assert pc.ops == ["list"]  # read dispatch 0, despite intent:read and later plan:files.
    assert all(c["requested"] == c["admitted"] == "files_list" for c in pc.claims)
    assert all(c["ops"] == ["list"] and c["source"] == "declared" for c in pc.claims)
    assert len(model.prompts) == 3
    assert "In your FIRST step declare" not in model.prompts[0]
    assert "server admitted files_list" in model.prompts[0]
    assert "pc_scope_denied" in model.prompts[-1]


def test_external_files_declaration_is_capped_by_server_read_grant():
    pc = _FakePcEndpoint()
    first = json.loads(LIST_STEP)
    first["plan"] = "files_list"  # The external declaration still supplies requested.
    model = _ScriptedModel([json.dumps(first), WRONG_READ_STEP, COMPLETE_STEP])
    transport = _InProcessEngineTransport(_chain(model=model, pc=pc, allow_read=False))
    result = _orchestrate_declared(transport, "files")
    assert result["execution"]["metadata"]["status"] == "completed"
    assert transport.statuses == [200]
    assert pc.ops == ["list"]
    assert all(c["requested"] == "files" and c["admitted"] == "files_list" for c in pc.claims)
    assert all(c["ops"] == ["list"] for c in pc.claims)
    assert len(model.prompts) == 3 and "pc_scope_denied" in model.prompts[-1]


def test_external_scope_needs_no_model_redeclaration_or_extra_call():
    pc = _FakePcEndpoint()
    first = json.loads(LIST_STEP)
    first.pop("plan")
    model = _ScriptedModel([json.dumps(first), WRONG_READ_STEP, COMPLETE_STEP])
    transport = _transport_for(model=model, pc=pc)
    _orchestrate_declared(transport, "files")
    assert pc.ops == ["list", "read"]  # Without the external scope, first list derives list-only.
    assert len(model.prompts) == 3
    assert all(c["requested"] == c["admitted"] == "files" for c in pc.claims)
    assert all("In your FIRST step declare" not in prompt for prompt in model.prompts)


@pytest.mark.parametrize("invalid", [None, "", "none", "FILES", " files", "read", [], {}])
@pytest.mark.parametrize("stream", [False, True])
def test_invalid_external_plan_is_422_before_any_model_or_pc_call(invalid, stream):
    from app.orchestration_service import ORCHESTRATION_STREAM_PATH
    pc = _FakePcEndpoint()
    model = _ScriptedModel([])
    service = _chain(model=model, pc=pc)
    payload = {**FILES_RECORD, "declared_plan": invalid}

    async def exercise():
        if stream:
            return await service.prepare_stream(
                method="POST", path=ORCHESTRATION_STREAM_PATH,
                content_type="application/json", body=json.dumps(payload).encode(),
            )
        return await service.orchestrate_payload(payload)

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.body["error"]["code"] == "invalid_plan"
    assert model.prompts == [] and pc.requests == []


def test_external_declaration_cannot_make_a_non_pc_request_pc_eligible():
    pc = _FakePcEndpoint()
    model = _ScriptedModel([])
    payload = {**FILES_RECORD, "declared_plan": "files_list"}
    payload.pop("agent_plan")
    payload.pop("tool_arguments")
    response = asyncio.run(_chain(model=model, pc=pc).orchestrate_payload(payload))
    assert response.status_code == 422 and response.body["error"]["code"] == "invalid_plan"
    assert model.prompts == [] and pc.requests == []


def test_streaming_wire_admits_external_list_scope_before_dispatch():
    from app.orchestration_service import ORCHESTRATION_STREAM_PATH
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, WRONG_READ_STEP, COMPLETE_STEP])
    service = _chain(model=model, pc=pc)
    payload = {**FILES_RECORD, "declared_plan": "files_list"}

    async def exercise():
        prepared = await service.prepare_stream(
            method="POST", path=ORCHESTRATION_STREAM_PATH,
            content_type="application/json", body=json.dumps(payload).encode(),
        )
        assert prepared.__class__.__name__ == "PreparedOrchestrationStream"
        return [line async for line in service.iter_ndjson(prepared)]

    with patch.object(asyncio, "sleep", _instant_sleep):
        lines = asyncio.run(exercise())
    assert lines and pc.ops == ["list"]
    assert pc.claims and all(c["admitted"] == "files_list" for c in pc.claims)
    assert len(model.prompts) == 3


def test_external_declaration_is_part_of_replay_identity():
    from app.orchestration_idempotency_service import _initial_execution_fingerprint
    legacy = _initial_execution_fingerprint(FILES_RECORD)
    variants = [
        _initial_execution_fingerprint({**FILES_RECORD, "declared_plan": name})
        for name in ("files_list", "files", "query_drives")
    ]
    assert legacy is not None and all(value is not None for value in variants)
    assert len({legacy, *variants}) == 4
    assert _initial_execution_fingerprint({**FILES_RECORD, "declared_plan": None}) is None



@pytest.mark.parametrize("stream", [False, True])
def test_changed_external_scope_cannot_replay_under_the_same_key(stream):
    from app.orchestration_service import ORCHESTRATION_STREAM_PATH
    pc = _FakePcEndpoint()
    model = _ScriptedModel([LIST_STEP, COMPLETE_STEP])
    service = _chain(model=model, pc=pc)
    payload = {
        **FILES_RECORD, "declared_plan": "files_list",
        "execution_context": {**FILES_RECORD["execution_context"], "idempotency_key": "idem_declared"},
    }

    async def invoke(body):
        if not stream:
            return await service.orchestrate_payload(body)
        prepared = await service.prepare_stream(
            method="POST", path=ORCHESTRATION_STREAM_PATH,
            content_type="application/json", body=json.dumps(body).encode(),
        )
        if hasattr(prepared, "status_code"):
            return prepared
        return "".join([line async for line in service.iter_ndjson(prepared)])

    async def exercise():
        first = await invoke(payload)
        if isinstance(first, str):
            assert '"type":"error"' not in first
        else:
            assert first.status_code == 200
        assert len(model.prompts) == 2 and pc.ops == ["list"]
        second = await invoke({**payload, "declared_plan": "files"})
        if isinstance(second, str):
            assert "idempotency_conflict" in second
        else:
            assert second.status_code == 409
            assert second.body["error"]["code"] == "idempotency_conflict"
        assert len(model.prompts) == 2 and pc.ops == ["list"]

    with patch.object(asyncio, "sleep", _instant_sleep):
        asyncio.run(exercise())
