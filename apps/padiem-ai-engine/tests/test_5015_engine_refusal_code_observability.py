"""#5015: the Engine's own refusal code survives the response and the exporter.

The 2026-10-21 production PC request ended as ``POST /internal/* -> 400
client_error, 8145 ms`` with no PC dispatch. The Engine body already carried a
machine-readable ``error.code`` for that refusal, but the only retained
artefact was the exported ``http_request`` event, and that event had no code
field. The failing branch therefore could not be named afterwards, and the
handoff had to keep ``CAUSE_CONFIDENCE=UNKNOWN``.

This test proves the whole observable chain without a provider, PC or network
call:

* the real production composition (AdmissionBound -> CanonicalIdempotency ->
  IdentityBound) maps an orchestration refusal to the bounded 400 envelope,
  carrying the exact Core code;
* the real request exporter retains that one identifier on the
  ``http_request`` event under the same ``request_id``;
* the real Python Engine client surfaces the same code back to the caller.

The code asserted here is a *representative* Core refusal, not the confirmed
production branch: the production cause stays undetermined until a request runs
against this instrumentation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest

import app.orchestration_identity_service as identity_mod
from app.execution_admission_service import AdmissionBoundOrchestrationEngineService
from app.stack_telemetry import make_events, record_refusal, reset_trace, start_trace
from padiem_ai_core.orchestration import OrchestrationError
from tests.test_5015_chat_pc_wire_admission import (
    AllowingAdapter,
    CHAT_APP_ID,
    DRIVES_PAYLOAD,
    _binding,
)

CLIENT_ROOT = Path(__file__).resolve().parents[1] / "clients" / "python"
sys.path.insert(0, str(CLIENT_ROOT))

from padiem_ai_engine_client import (  # noqa: E402
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)

CREDENTIAL = "c" * 48
# Real Core refusal codes from the orchestration boundary the PC lane runs
# inside. The PC failure could only be narrowed to "somewhere after the model
# lane", so the instrumentation must preserve *whichever* code fired verbatim.
REFUSAL_CODES = (
    "p01_result_correlation_mismatch",
    "unsupported_result_plan",
    "invalid_result_tool_event",
)


class _RefusingRunner:
    """Replaces Core's runner: it refuses exactly like the real boundary does."""

    code = REFUSAL_CODES[0]

    def __init__(self, *, runtime, idempotency=None) -> None:
        self._runtime = runtime
        self._idempotency = idempotency

    async def run(self, request):
        raise OrchestrationError(self.code, "Agent execution terminated with reason: error")


def _service() -> AdmissionBoundOrchestrationEngineService:
    return AdmissionBoundOrchestrationEngineService(
        runtime_factory=lambda app_id: object(),
        b14_service_bound=True,
        admission_adapter=AllowingAdapter(),
        tool_binding_resolver=lambda app_id: _binding() if app_id == CHAT_APP_ID else None,
        pc_query_step_driver_factory=lambda *args, **kwargs: "owner_pc_step_driver",
    )


def _refused(monkeypatch, code: str):
    _RefusingRunner.code = code
    monkeypatch.setattr(identity_mod, "OrchestrationRunner", _RefusingRunner)
    return asyncio.run(_service().orchestrate_payload(dict(DRIVES_PAYLOAD)))


@pytest.mark.parametrize("code", REFUSAL_CODES)
def test_the_real_composition_answers_with_the_exact_core_refusal_code(monkeypatch, code):
    response = _refused(monkeypatch, code)

    assert response.status_code == 400
    assert response.body["ok"] is False
    assert response.body["error"]["code"] == code


@pytest.mark.parametrize("code", REFUSAL_CODES)
def test_the_exported_request_event_keeps_that_code_and_nothing_else(monkeypatch, code):
    response = _refused(monkeypatch, code)
    request = type(
        "Request", (), {"headers": {"x-request-id": "req_5015refusal01"}, "method": "POST"}
    )()

    state, token = start_trace(request, "padiem-ai-engine", "/internal/*")
    try:
        record_refusal(response.status_code, response.body)
        events = make_events(state, response.status_code)
    finally:
        reset_trace(token)

    # One request event plus the failure itself: no stage events were recorded
    # here because this harness replaces the runner.
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "http_request"
    assert event["request_id"] == "req_5015refusal01"
    assert event["status"] == 400
    assert event["outcome"] == "client_error"
    assert event["error_code"] == code
    # Content-blind: the safe message, the plan, the target and the run are not
    # exported. Only the bounded identifier is retained.
    rendered = json.dumps(event, ensure_ascii=False)
    assert "Agent execution terminated" not in rendered
    assert DRIVES_PAYLOAD["subject_id"] not in rendered
    assert DRIVES_PAYLOAD["session_id"] not in rendered


def test_a_successful_response_never_carries_a_refusal_code():
    state, token = start_trace(
        type("Request", (), {"headers": {}, "method": "POST"})(),
        "padiem-ai-engine",
        "/internal/*",
    )
    try:
        record_refusal(
            200,
            {"ok": False, "error": {"code": "invalid_plan", "message": "ignored"}},
        )
        events = make_events(state, 200)
    finally:
        reset_trace(token)

    assert "error_code" not in events[0]


@pytest.mark.parametrize(
    "code",
    (
        "invalid_plan\n",
        "invalid plan",
        "x" * 65,
        "@invalid",  # '@' is inside the grammar; a leading '@' is not.
        "",
    ),
)
def test_an_unbounded_code_is_dropped_instead_of_truncated(code):
    state, token = start_trace(
        type("Request", (), {"headers": {}, "method": "POST"})(),
        "padiem-ai-engine",
        "/internal/*",
    )
    try:
        record_refusal(400, {"ok": False, "error": {"code": code}})
        events = make_events(state, 400)
    finally:
        reset_trace(token)

    assert events[0]["outcome"] == "client_error"
    assert "error_code" not in events[0]


def test_recording_outside_a_traced_request_is_a_no_op():
    record_refusal(400, {"ok": False, "error": {"code": "invalid_plan"}})


@pytest.mark.parametrize("code", REFUSAL_CODES)
def test_the_real_engine_client_returns_that_code_to_the_caller(monkeypatch, code):
    response = _refused(monkeypatch, code)

    class _Transport:
        def __init__(self) -> None:
            self.calls = []

        async def request(self, *, method, url, headers, body):
            self.calls.append({"method": method, "url": url})
            return EngineTransportResponse(
                status=response.status_code,
                body=json.dumps(dict(response.body), ensure_ascii=False).encode("utf-8"),
            )

    transport = _Transport()
    client = PadiemAiEngineClient(
        transport=transport,
        app_id="b62",
        caller_id="padiem-chat-b62",
        credential=CREDENTIAL,
    )
    # ``app_id`` is client-owned on this contract; the recorded fixture is the
    # emitted wire body, so the caller-side input is the same body without it.
    caller_input = {k: v for k, v in DRIVES_PAYLOAD.items() if k != "app_id"}

    with pytest.raises(PadiemAiEngineClientError) as raised:
        asyncio.run(client.orchestrate(caller_input))

    # The client is not the loss point: the Engine code arrives intact, so a
    # future failure is attributable from the caller side too.
    assert raised.value.code == code
    assert raised.value.status == 400
    assert len(transport.calls) == 1
