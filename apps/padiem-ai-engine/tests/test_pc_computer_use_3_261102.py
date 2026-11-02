"""#6460 step 3 — the model-driven PC loop, its stop reasons and its end.

The provider, the Chat transport and the PC are all fakes. What runs for real
is the Core runtime composition: the driver chooses one action, the registered
tool signs one Chat dispatch, the result returns, and the loop ends on the
model's completion, on the owner's 그만, or when the same action produced no
visible change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from padiem_ai_core.agent_runtime import AgentStepContext
from padiem_ai_core.contracts import RunStatus, ToolEvent
from padiem_ai_core.tool_runtime import ToolExecutionResult, ToolInvocation

from app.claw_desktop_step_driver import (
    DESKTOP_AGENT_ID,
    DESKTOP_CAPTURE_ID,
    DESKTOP_NO_PROGRESS_ANSWER,
    DESKTOP_STOP_ANSWER,
    _ENGINE_DESKTOP_OWNER,
    build_claw_desktop_tool_binding,
    build_live_desktop_driver,
)

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
DIGEST = hashlib.sha256(JPEG).hexdigest()
SUBJECT = "sub_loop_owner"
RUN = "run_loop_0001"
TASK = "메모장 열어서 오늘 날짜 적고 저장해 줘"


@pytest.fixture(autouse=True)
def _no_poll_wait(monkeypatch):
    from app import claw_desktop_step_driver as driver_module
    monkeypatch.setattr(driver_module, "DESKTOP_RESULT_POLL_SECONDS", 0)


class Request:
    def __init__(self, url, *, method, headers, body):
        self.url, self.method, self.headers, self.body = url, method, headers, body
        self.js_object = self


class Response:
    def __init__(self, data, *, image=False):
        self.status = 200
        self._data = data
        self._image = image

    async def text(self):
        return json.dumps(self._data)

    async def arrayBuffer(self):
        return type("Buffer", (), {"to_py": lambda self: JPEG})()


class Chat:
    """The signed Chat transport, including the run's own stop state."""

    def __init__(self, *, stop_after=None, cancel_dispatch=None,
                 capture_digests=None):
        self.dispatches = []
        self.stop_after = stop_after
        self.cancel_dispatch = cancel_dispatch
        self.capture_digests = list(capture_digests or [])
        self.capture_count = 0

    def _digest_for(self, op):
        if op == "desktop:capture":
            index = self.capture_count
            self.capture_count += 1
            if self.capture_digests:
                return self.capture_digests[min(index, len(self.capture_digests) - 1)]
            return DIGEST
        return "b" * 64

    async def fetch(self, request):
        payload = json.loads(request.body)
        mode = payload.get("mode")
        if mode == "run_status":
            stopped = (
                self.stop_after is not None
                and len(self.dispatches) >= self.stop_after
            )
            return Response({
                "ok": True,
                "run": {"run_id": payload["run_id"], "state": "cancelled" if stopped else "running",
                        "updated_at": "2026-11-02T00:00:00Z"},
            })
        if mode == "image":
            return Response({}, image=True)
        if mode == "status":
            item = next(
                row for row in self.dispatches
                if row["dispatch_id"] == payload["dispatch_id"]
            )
            cancelled = payload["dispatch_id"] == self.cancel_dispatch
            return Response({
                "ok": True, "dispatch": {
                    "dispatch_id": payload["dispatch_id"],
                    "run_id": payload["run_id"], "kind": "desktop",
                    "state": "pending" if cancelled else "done",
                    "result_sha256": item["digest"],
                    "termination": "cancelled" if cancelled else None,
                },
            })
        op = payload["desktop_op"].split("\n")[0]
        dispatch_id = "dispatch_" + str(len(self.dispatches) + 1)
        self.dispatches.append({
            "dispatch_id": dispatch_id,
            "op": op,
            "desktop_op": payload["desktop_op"],
            "desktop_text": payload.get("desktop_text"),
            "call_ref": payload.get("call_ref"),
            "digest": self._digest_for(op),
            "run_id": payload["run_id"],
        })
        return Response({
            "ok": True, "dispatch": {
                "dispatch_id": dispatch_id, "run_id": payload["run_id"],
                "kind": "desktop", "state": "pending",
            },
        })


class Model:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def execute(self, request):
        assert "max_tokens" not in request.to_payload()
        self.calls += 1
        answer = self.answers.pop(0)
        return type("Answer", (), {"answer": json.dumps(answer)})()


def _compose(chat, model):
    binding = build_claw_desktop_tool_binding(
        service=chat, request_factory=Request, secret="s" * 32,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    driver = build_live_desktop_driver(
        b14_client=model, chat_service=chat, request_factory=Request,
        secret="s" * 32, model_id="existing/model",
    )
    return binding, authority, driver


def _run_loop(chat, model, *, max_steps=12):
    binding, authority, driver = _compose(chat, model)
    token = _ENGINE_DESKTOP_OWNER.set((SUBJECT, RUN))
    try:
        async def loop():
            results = []
            for _ in range(max_steps):
                context = AgentStepContext.with_results(
                    run_id=RUN, step_index=len(results) + 1,
                    input_text=TASK, results=tuple(results),
                )
                decision = await driver.next_step(context, None)
                if decision.answer is not None:
                    return decision.answer
                outcome = await binding.tool_runtime.execute(
                    decision.invocation,
                    authority.compiled.runtime_profile,
                    authority.authorization,
                )
                results.append(outcome)
            return None
        return asyncio.run(loop())
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)


def test_the_loop_captures_acts_and_captures_again_until_the_model_finishes():
    chat = Chat()
    model = Model([
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
        {"action": "tool", "tool_id": "claw.desktop.type",
         "arguments": {"text": "2026-11-02"}},
        {"action": "complete", "answer": "날짜를 적고 저장했습니다."},
    ])
    answer = _run_loop(chat, model)
    assert answer == "날짜를 적고 저장했습니다."
    assert [item["op"] for item in chat.dispatches] == [
        "desktop:capture", "desktop:click", "desktop:capture",
        "desktop:type", "desktop:capture",
    ]
    # Each step is its own dispatch, so one run is not one dispatch.
    assert [item["call_ref"] for item in chat.dispatches] == [
        "desktop-step-1", "desktop-step-2", "desktop-step-3",
        "desktop-step-4", "desktop-step-5",
    ]
    typed = next(item for item in chat.dispatches if item["op"] == "desktop:type")
    # The value travels beside the op; the dispatch body Chat records has only
    # the op, and Chat turns it into a length+digest+reference marker.
    assert typed["desktop_op"] == "desktop:type"
    assert typed["desktop_text"] == "2026-11-02"


def test_the_owner_stop_ends_the_loop_before_the_next_action():
    chat = Chat(stop_after=2)
    model = Model([
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
        # Chosen after the owner already pressed 그만; it is never dispatched.
        {"action": "tool", "tool_id": "claw.desktop.keys",
         "arguments": {"combo": "ctrl+s"}},
    ])
    answer = _run_loop(chat, model)
    assert answer == DESKTOP_STOP_ANSWER
    assert [item["op"] for item in chat.dispatches] == [
        "desktop:capture", "desktop:click",
    ]


def test_a_cancelled_dispatch_ends_the_loop_as_a_stop():
    chat = Chat(cancel_dispatch="dispatch_2")
    model = Model([
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
    ])
    answer = _run_loop(chat, model)
    assert answer == DESKTOP_STOP_ANSWER
    # The click was sent once; nothing after it was sent.
    assert [item["op"] for item in chat.dispatches] == [
        "desktop:capture", "desktop:click",
    ]


def test_the_same_action_on_the_same_screen_stops_with_its_reason():
    # The click changed nothing: the capture after it is byte-identical.
    chat = Chat(capture_digests=[DIGEST, DIGEST])
    model = Model([
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
    ])
    answer = _run_loop(chat, model)
    assert answer == DESKTOP_NO_PROGRESS_ANSWER
    # capture → click → the unchanged capture → the repeated click is refused
    # instead of being sent again.
    assert [item["op"] for item in chat.dispatches] == [
        "desktop:capture", "desktop:click", "desktop:capture",
    ]
    assert model.calls == 2


def test_a_different_action_on_an_unchanged_screen_is_still_allowed():
    chat = Chat(capture_digests=[DIGEST, DIGEST])
    model = Model([
        {"action": "tool", "tool_id": "claw.desktop.click",
         "arguments": {"x": 120, "y": 64}},
        {"action": "tool", "tool_id": "claw.desktop.keys",
         "arguments": {"combo": "tab"}},
        {"action": "complete", "answer": "다음을 눌렀습니다."},
    ])
    answer = _run_loop(chat, model)
    assert answer == "다음을 눌렀습니다."
    assert [item["op"] for item in chat.dispatches] == [
        "desktop:capture", "desktop:click", "desktop:capture",
        "desktop:keys", "desktop:capture",
    ]


def test_the_owner_selected_pc_is_the_first_capture_target():
    # Chat verified the selection before dispatch; the loop must actually use
    # it, otherwise a multi-PC account could never run a task on one of them.
    chat = Chat()
    model = Model([])
    driver = build_live_desktop_driver(
        b14_client=model, chat_service=chat, request_factory=Request,
        secret="s" * 32, model_id="existing/model",
        capture_device_id="device_selected",
    )
    decision = asyncio.run(driver.next_step(
        AgentStepContext.with_results(
            run_id=RUN, step_index=1, input_text=TASK, results=(),
        ),
        None,
    ))
    assert decision.invocation.tool_id == DESKTOP_CAPTURE_ID
    assert decision.invocation.arguments_copy() == {
        "device_id": "device_selected", "call_ref": "desktop-step-1",
    }


def test_the_capture_returns_a_real_jpeg_before_any_model_choice():
    """A failed JPEG read never becomes a model guess."""
    from app.claw_desktop_step_driver import DesktopStepContractError, _ENGINE_DESKTOP_OWNER as owner_var

    class BadImageChat(Chat):
        async def fetch(self, request):
            payload = json.loads(request.body)
            if payload.get("mode") == "image":
                return type("R", (), {
                    "status": 200,
                    "arrayBuffer": lambda self: asyncio.sleep(
                        0, result=type("B", (), {"to_py": lambda self: b"notajpeg"})()
                    ),
                })()
            return await super().fetch(request)

    chat = BadImageChat()
    binding, authority, driver = _compose(chat, Model([]))
    result = ToolExecutionResult(
        tool_id=DESKTOP_CAPTURE_ID,
        output={
            "capture_receipt": "dispatch_1", "dispatch_id": "dispatch_1",
            "result_sha256": hashlib.sha256(b"notajpeg").hexdigest(),
            "run_id": RUN, "execution_confirmed": True,
        },
        event=ToolEvent(tool_id=DESKTOP_CAPTURE_ID, status=RunStatus.COMPLETED),
    )
    token = owner_var.set((SUBJECT, RUN))
    try:
        with pytest.raises(DesktopStepContractError):
            asyncio.run(driver.next_step(
                AgentStepContext.with_results(
                    run_id=RUN, step_index=1, input_text=TASK, results=(result,),
                ),
                None,
            ))
    finally:
        owner_var.reset(token)
