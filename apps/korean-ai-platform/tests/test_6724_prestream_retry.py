"""#6724: one same-route retry when the upstream failed before answering.

CTO decision 2026-11-10: a B14 upstream call that produced no answer byte may
be dispatched once more on the SAME model and route after 0.5 s. The retried
classes are: connection failure / upstream 5xx, a timeout that expired while
connecting, and a first frame whose whole payload is an error envelope. A 4xx
(auth, quota, rejected request) is never retried, and a failure after the first
visible byte stays terminal.

Pinned here:

* streamed: pre-answer 502 → retry → the answer is served, both attempts in the
  ledger, the retry on the same route;
* streamed: two pre-answer 502s → one error to the caller, two attempts kept;
* streamed: failure after the first visible byte → no retry, one provider call;
* streamed: 4xx before the answer → no retry;
* streamed: an error envelope as the first frame → retried; a malformed body
  that is not an envelope → not retried;
* completed: the same rules, with one retry by default and ``max_retries=0``
  still opting out;
* usage: the failed attempt stores no tokens, the answered one carries them.

No provider is contacted: the adapter is replaced by a fake and the SSE frames
are built locally.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot import stream_gateway as sg
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.call_ledger import token_evidence
from app.pilot.deferred_writes import bind as bind_deferred, drain, reset as reset_deferred
from app.pilot.errors import (
    MalformedUpstreamResponse,
    UpstreamAuthFailed,
    UpstreamClientError,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.prestream_retry import (
    PRESTREAM_RETRY_DELAY_SECONDS,
    PRESTREAM_RETRY_LIMIT,
    is_prestream_retryable,
)
from app.pilot.stream_types import StreamEvent, StreamUsage, _parse_sse_frame

from _pilot_lane_paths import chat_surface
from _registry_values import a_dispatchable_row, model_row, model_rows, provider_of, provider_row

URL = chat_surface()
PREVIEW_URL = URL + "/stream-preview"

_ROW = a_dispatchable_row()
assert _ROW is not None
MODEL_ID = _ROW["id"]
BINDING = provider_row(provider_of(MODEL_ID))["credential_binding_name"]

#: The completed lane's own row: an enabled registry identity, never a retired one.
MODEL_ID_COMPLETED = next(row["id"] for row in model_rows() if row["enabled"])
_ROW_COMPLETED = model_row(MODEL_ID_COMPLETED)
BINDING_COMPLETED = provider_row(provider_of(MODEL_ID_COMPLETED))["credential_binding_name"]


@pytest.fixture(autouse=True)
def _live_lane(monkeypatch):
    """Live mode with a synthetic binding: no provider is reachable anyway."""
    saved_mode = rcfg.provider_mode
    monkeypatch.setattr(rcfg, "provider_mode", "live")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setenv(BINDING, "synthetic-credential-not-a-secret")
    monkeypatch.setenv(BINDING_COMPLETED, "synthetic-credential-not-a-secret")
    yield
    rcfg.provider_mode = saved_mode


@pytest.fixture(autouse=True)
def _deferred_scope():
    token = bind_deferred()
    try:
        yield
    finally:
        reset_deferred(token)


@pytest.fixture()
def sleeps(monkeypatch):
    """Record the retry pause without waiting for it."""
    seen: list[float] = []
    real_sleep = asyncio.sleep

    async def fake(seconds, *args, **kwargs):
        seen.append(seconds)
        return await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake)
    return seen


@pytest.fixture()
def records(monkeypatch):
    written: list = []

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setattr(sg, "record_call", capture)
    monkeypatch.setattr(gw, "record_call", capture)
    return written


# --------------------------------------------------------------- stream lane
def _fake_stream(behaviours, calls):
    """One fake adapter: each behaviour is an event list or an exception."""

    def fake(**kwargs):
        calls.append(kwargs)
        behaviour = behaviours[min(len(calls) - 1, len(behaviours) - 1)]

        async def gen():
            if isinstance(behaviour, BaseException):
                raise behaviour
            for event in behaviour:
                yield event

        return gen()

    return fake


def _stream(monkeypatch, behaviours, calls):
    monkeypatch.setattr(sg, "stream_platform_chat_completions", _fake_stream(behaviours, calls))
    body = {
        "model": MODEL_ID,
        "messages": [{"role": "user", "content": "synthetic offline fixture"}],
        "stream": True,
    }
    with TestClient(create_app()) as client:
        return client.post(PREVIEW_URL, json=body)


_OK_EVENTS = [
    StreamEvent(delta_content="답"),
    StreamEvent(finish_reason="stop", usage=StreamUsage(4, 6, 10)),
    StreamEvent(done=True),
]


def test_a_pre_answer_502_is_retried_once_on_the_same_route(
    monkeypatch, sleeps, records,
):
    calls: list = []
    response = _stream(monkeypatch, [UpstreamServerError(), _OK_EVENTS], calls)

    assert response.status_code == 200, response.text
    assert "답" in response.text
    assert len(calls) == 2
    # Same route, same model: the retry is not a substitution.
    assert {call["model_id"] for call in calls} == {MODEL_ID}
    assert sleeps == [PRESTREAM_RETRY_DELAY_SECONDS]
    assert PRESTREAM_RETRY_LIMIT == 1


@pytest.mark.asyncio
async def test_the_retried_stream_keeps_both_attempts_and_only_the_answer_usage(
    monkeypatch, sleeps, records,
):
    calls: list = []
    response = _stream(monkeypatch, [UpstreamServerError(), _OK_EVENTS], calls)
    assert response.status_code == 200
    await drain()

    record = records[0]
    assert record.attempt_count == 2 == len(record.attempts)
    failed, answered = record.attempts
    assert failed.outcome == "error" and failed.error_code == "upstream_server_error"
    assert failed.retry_index == 0
    # A failed attempt is not consumption: no token count and no cost basis.
    assert (failed.prompt_tokens, failed.completion_tokens, failed.total_tokens) == (None, None, None)
    assert failed.token_source == "missing"
    assert answered.outcome == "success" and answered.retry_index == 1
    assert (record.prompt_tokens, record.total_tokens) == (4, 10)
    assert record.token_source == "measured"
    assert record.outcome == "success"


def test_two_pre_answer_502s_surface_one_error_with_two_attempts(
    monkeypatch, sleeps, records,
):
    calls: list = []
    response = _stream(monkeypatch, [UpstreamServerError()], calls)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_server_error"
    assert len(calls) == 2
    assert len(sleeps) == 1


@pytest.mark.asyncio
async def test_a_second_failure_leaves_the_attempts_in_the_ledger(
    monkeypatch, sleeps, records,
):
    calls: list = []
    _stream(monkeypatch, [UpstreamServerError()], calls)
    await drain()

    record = records[0]
    assert record.outcome == "error"
    assert [attempt.outcome for attempt in record.attempts] == ["error", "error"]
    assert [attempt.retry_index for attempt in record.attempts] == [0, 1]
    assert record.token_source == "missing"


def test_a_failure_after_the_first_visible_byte_is_not_retried(monkeypatch, sleeps, records):
    calls: list = []
    behaviours = [[StreamEvent(delta_content="답"), UpstreamServerError()]]
    response = _stream(monkeypatch, behaviours, calls)

    assert response.status_code == 200
    assert "event: error" in response.text
    assert len(calls) == 1
    assert sleeps == []


def test_a_4xx_before_the_answer_is_not_retried(monkeypatch, sleeps, records):
    calls: list = []
    response = _stream(monkeypatch, [UpstreamAuthFailed()], calls)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "upstream_auth_failed"
    assert len(calls) == 1
    assert sleeps == []


def test_an_error_envelope_first_frame_is_retried(monkeypatch, sleeps, records):
    calls: list = []
    envelope = MalformedUpstreamResponse("error_envelope")
    response = _stream(monkeypatch, [envelope, _OK_EVENTS], calls)

    assert response.status_code == 200
    assert len(calls) == 2


def test_a_malformed_body_that_is_not_an_envelope_is_not_retried(monkeypatch, sleeps, records):
    calls: list = []
    response = _stream(monkeypatch, [MalformedUpstreamResponse("choices_not_list")], calls)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "malformed_upstream_response"
    assert len(calls) == 1


# ------------------------------------------------------------ frame parsing
def test_the_parser_names_an_error_envelope_and_keeps_other_reasons() -> None:
    with pytest.raises(MalformedUpstreamResponse) as raised:
        _parse_sse_frame('data: {"error": {"message": "denied"}}\n\n'.encode())

    assert raised.value.reason == "error_envelope"
    with pytest.raises(MalformedUpstreamResponse) as other:
        _parse_sse_frame(b'data: {"choices": {}}\n\n')
    assert other.value.reason == "choices_not_list"


# ------------------------------------------------------------- retry policy
def test_the_policy_names_exactly_the_pre_answer_classes() -> None:
    assert is_prestream_retryable(UpstreamServerError())
    assert is_prestream_retryable(
        UpstreamTimeout(timeout_reason="first_byte", timeout_phase="connect")
    )
    assert is_prestream_retryable(MalformedUpstreamResponse("error_envelope"))
    # A provider that had the request and was slow is a different class.
    assert not is_prestream_retryable(
        UpstreamTimeout(timeout_reason="first_byte", timeout_phase="read")
    )
    assert not is_prestream_retryable(UpstreamTimeout(timeout_reason="attempt_total"))
    assert not is_prestream_retryable(UpstreamAuthFailed())
    assert not is_prestream_retryable(UpstreamClientError(422))
    assert not is_prestream_retryable(MalformedUpstreamResponse("json_decode"))


# ----------------------------------------------------------- completed lane
def _ok_response(upstream_model: str) -> dict:
    return {
        "id": "cmpl-6724",
        "object": "chat.completion",
        "model": upstream_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "OK"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        "_live": True,
        "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


def _install(monkeypatch, behaviours):
    calls: list[dict] = []

    async def fake(*, model_id, upstream_model, provider, platform_provider_id,
                   messages, temperature=0.2, max_tokens=300, transport=None, **_kwargs):
        calls.append({"model_id": model_id})
        behaviour = behaviours[min(len(calls) - 1, len(behaviours) - 1)]
        if isinstance(behaviour, BaseException):
            raise behaviour
        return behaviour(upstream_model)

    monkeypatch.setattr(plat, "call_platform_chat_completions", fake)
    return calls


def _post(business14=None):
    body = {
        "model": MODEL_ID_COMPLETED,
        "messages": [{"role": "user", "content": "hi"}],
    }
    if business14 is not None:
        body["business14"] = business14
    with TestClient(create_app()) as client:
        return client.post(URL, json=body)


def test_a_completed_pre_answer_502_is_retried_once_by_default(monkeypatch, sleeps):
    calls = _install(monkeypatch, [UpstreamServerError(), _ok_response])

    response = _post()

    assert response.status_code == 200, response.text
    assert len(calls) == 2
    biz14 = response.json()["business14"]
    assert biz14["attempt_count"] == 2
    assert biz14["fallback_used"] is False
    evidence = biz14["attempt_evidence"]
    assert evidence[0]["outcome"] == "error"
    assert evidence[0]["error_code"] == "upstream_server_error"
    assert evidence[0]["retry_index"] == 0
    assert evidence[1]["outcome"] == "success" and evidence[1]["retry_index"] == 1
    assert sleeps == [PRESTREAM_RETRY_DELAY_SECONDS]


def test_two_completed_pre_answer_502s_surface_one_error(monkeypatch, sleeps):
    calls = _install(monkeypatch, [UpstreamServerError()])

    response = _post()

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_server_error"
    assert len(calls) == 2
    assert len(sleeps) == 1


def test_a_completed_4xx_is_not_retried(monkeypatch, sleeps):
    calls = _install(monkeypatch, [UpstreamAuthFailed()])

    response = _post()

    assert response.status_code == 401
    assert len(calls) == 1
    assert sleeps == []


def test_an_explicit_max_retries_zero_still_opts_out(monkeypatch, sleeps):
    calls = _install(monkeypatch, [UpstreamServerError(), _ok_response])

    response = _post({"max_retries": 0})

    assert response.status_code == 502
    assert len(calls) == 1
    assert sleeps == []


def test_a_connect_phase_timeout_is_retried_and_a_read_timeout_is_not(monkeypatch, sleeps):
    calls = _install(
        monkeypatch,
        [UpstreamTimeout(timeout_reason="first_byte", timeout_phase="connect"), _ok_response],
    )
    response = _post()
    assert response.status_code == 200
    assert len(calls) == 2

    calls = _install(
        monkeypatch,
        [UpstreamTimeout(timeout_reason="first_byte", timeout_phase="read"), _ok_response],
    )
    response = _post()
    assert response.status_code == 504
    assert len(calls) == 1


def test_the_ledger_rule_is_unchanged_for_a_failed_first_attempt() -> None:
    """The failed attempt's usage stays missing, never a stored zero."""
    prompt, completion, total, reasoning, source = token_evidence(None)
    assert (prompt, completion, total, reasoning) == (None, None, None, None)
    assert source == "missing"
