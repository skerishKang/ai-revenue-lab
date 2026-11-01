"""Browser routing intent and Claw's bounded, server-correlated display stream."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from padiem_ai_core.orchestration_events import OrchestrationEventKind as K

from app.claw_live_events import live_claw_sse
from app.pc_browser_intent import requested_pc_browser
from test_3930_b54_live_sse_relay import _event
from test_b54_claw_general_p01_routing import _make_outcome


RUN_ID = "run_" + "c" * 24
DISPATCH_ID = "dsp_" + "d" * 32
CONFIRMATION = "https://example.com 페이지에서 이 동작을 실행할까요?"


@pytest.mark.parametrize("text", [
    "example.com 열어서 제목 알려 줘", "https://example.com 열어서 읽어 줘",
    "Open https://example.com and read the title", "브라우저 페이지 캡처해 줘",
])
def test_explicit_user_browser_request_routes_to_browser(text):
    assert requested_pc_browser(text)


@pytest.mark.parametrize("text", [
    "example.com", "파일을 열어서 읽어 줘", "내 PC 파일 목록 보여 줘", "네", "결제", None,
])
def test_unrelated_or_unconfirmed_request_does_not_select_browser(text):
    assert not requested_pc_browser(text)


@pytest.mark.parametrize("answer", ["네", "예.", "진행해", "yes", "go ahead"])
def test_saved_assistant_confirmation_supports_followup_user_answer(answer):
    assert requested_pc_browser(answer, records=[
        {"role": "user", "content": "사이트에서 클릭해 줘"},
        {"role": "assistant", "content": CONFIRMATION},
    ])


@pytest.mark.parametrize("role", ["tool_result", "tool", "user", "system"])
def test_untrusted_page_or_user_text_cannot_supply_assistant_confirmation(role):
    assert not requested_pc_browser("네", records=[{"role": role, "content": CONFIRMATION}])


def test_only_latest_saved_assistant_question_can_confirm_browser_action():
    assert not requested_pc_browser("네", records=[
        {"role": "assistant", "content": CONFIRMATION},
        {"role": "user", "content": "브라우저 작업은 취소하고 파일을 찾아 줘"},
        {"role": "assistant", "content": "어느 폴더에서 파일을 찾을까요?"},
    ])


def progress_record(**changes):
    return {"pc_progress": {"pc_run_id": RUN_ID, "dispatch_id": DISPATCH_ID,
        "kind": "command", "stage": "executing", "sequence": 1, "elapsed_ms": 1250,
        **changes}}


class BrowserAdapter:
    def __init__(self, records=()):
        self.records, self.options = records, None

    async def execute(self, run, *, on_event, **options):
        self.options = options
        await on_event(_event(1, K.RUN_STARTED))
        callback = options.get("on_pc_progress")
        if callback:
            for record in self.records:
                await callback(record)
        await on_event(_event(2, K.RUN_COMPLETED))
        return _make_outcome(status="completed", answer="Example Domain")


def stream(adapter, *, browser=True, run=None):
    response = live_claw_sse(adapter, run if run is not None else SimpleNamespace(run_id=RUN_ID),
                             {"pc_browser_query": browser})

    async def read():
        return b"".join([chunk async for chunk in response.body_iterator]).decode("utf-8")

    text = asyncio.run(read())
    frames = [(part.splitlines()[0][7:], json.loads(part.splitlines()[1][6:]))
              for part in text.split("\n\n") if part]
    return response, frames, text


def test_browser_progress_is_projected_and_run_id_is_pinned_in_response_header():
    heartbeat = {"heartbeat": {"run_id": "orch_verified_1", "trace_id": "trace_verified_1",
                               "elapsed_ms": 1500}}
    adapter = BrowserAdapter([progress_record(), heartbeat])
    response, frames, text = stream(adapter)
    assert response.headers["X-Padiem-Claw-Run-Id"] == RUN_ID
    assert response.headers["Cache-Control"] == "no-cache, no-store"
    assert [kind for kind, _ in frames] == ["p01_event", "pc_progress", "heartbeat",
                                          "p01_event", "delta", "done"]
    assert frames[1][1] == progress_record()["pc_progress"]
    assert frames[2][1] == heartbeat["heartbeat"]
    assert frames[-2][1] == {"delta": "Example Domain"}
    assert "must-never-leak" not in text and "internal_note" not in text
    assert callable(adapter.options["on_pc_progress"])


def test_default_claw_stream_does_not_subscribe_to_browser_progress():
    adapter = BrowserAdapter([progress_record()])
    _, frames, _ = stream(adapter, browser=False)
    assert "on_pc_progress" not in adapter.options
    assert not any(kind in {"pc_progress", "heartbeat"} for kind, _ in frames)
    assert frames[-1] == ("done", {"done": True})


@pytest.mark.parametrize("changes", [
    {"pc_run_id": "run_" + "e" * 24}, {"sequence": True},
    {"stage": "password=private"}, {"output": "private-page-text"},
])
def test_invalid_progress_never_reaches_display_or_success(changes):
    _, frames, text = stream(BrowserAdapter([progress_record(**changes)]))
    assert [kind for kind, _ in frames] == ["p01_event", "error"]
    assert "private-page-text" not in text and "password=private" not in text
    assert '"done":true' not in text


@pytest.mark.parametrize("run", [object(), SimpleNamespace(run_id="run_attacker\r\nInjected: yes"),
                                  SimpleNamespace(run_id="run_not_canonical")])
def test_uncanonical_or_absent_run_id_is_not_promoted_to_response_header(run):
    response, frames, _ = stream(BrowserAdapter(), browser=False, run=run)
    assert "X-Padiem-Claw-Run-Id" not in response.headers
    assert frames[-1] == ("done", {"done": True})
