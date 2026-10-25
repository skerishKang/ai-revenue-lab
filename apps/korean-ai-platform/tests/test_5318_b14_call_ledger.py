"""The durable B14 call ledger (#5318): contract, store, write path, admin read.

The ledger exists because the platform's two existing surfaces cannot answer
"what actually ran": the OTLP telemetry is provider-identity-blind by contract
and the ``attempt_evidence`` block is a response payload that evaporates. These
tests pin what replaces it — including the two ways a usage dashboard lies:
recording an absent token count as zero, and letting a fallback overwrite the
attempt that failed.

No test here reaches a provider: writes go to a fake D1 binding, and the
gateway lane is driven with a stubbed adapter in live mode.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import gateway as gw
from app.pilot import platform as plat
from app.pilot.call_ledger import (
    CallLedgerError,
    CallRecord,
    AttemptRecord,
    LedgerDraft,
    cost_estimate,
    new_log_id,
    origin_from_headers,
    token_evidence,
    utc_now_iso,
)
from app.pilot.call_ledger_store import CallLedgerStore
from app.pilot.deferred_writes import bind as bind_deferred, drain, reset as reset_deferred

LIST_PATH = "/api/pilot/v1/admin/model-calls"
DETAIL_PATH = "/api/pilot/v1/admin/model-calls/{log_id}"
AGGREGATE_PATH = "/api/pilot/v1/admin/model-calls/aggregate"
MODEL_ID = "agnes-ai/agnes-3.0-flash"


# ---------------------------------------------------------------------------
# A fake D1 binding: it records SQL and bound parameters exactly as given.
# ---------------------------------------------------------------------------


class _FakeStatement:
    def __init__(self, store, sql):
        self._store = store
        self._sql = sql
        self._params = ()

    def bind(self, *params):
        self._params = params
        return self

    async def run(self):
        self._store.calls.append(("run", self._sql, self._params))
        return {"meta": {"changes": 1}}

    async def first(self):
        self._store.calls.append(("first", self._sql, self._params))
        return self._store.first_row

    async def all(self):
        self._store.calls.append(("all", self._sql, self._params))
        return {"results": list(self._store.rows)}


class FakeD1:
    def __init__(self, *, rows=(), first_row=None):
        self.calls = []
        self.rows = list(rows)
        self.first_row = first_row

    def prepare(self, sql):
        return _FakeStatement(self, sql)

    async def batch(self, statements):
        return [await statement.run() for statement in statements]


class ExplodingD1(FakeD1):
    def prepare(self, sql):
        raise RuntimeError("d1 unavailable")


def _attempt(**kwargs) -> AttemptRecord:
    base = dict(log_id=new_log_id(), attempt_index=0, provider="Agnes AI",
                model_id=MODEL_ID, upstream_model="agnes-3.0-flash")
    base.update(kwargs)
    return AttemptRecord(**base)


def _call(**kwargs) -> CallRecord:
    base = dict(log_id=new_log_id(), request_id="b14req_fixture01",
                endpoint="/api/pilot/v1/chat/completions", started_at=utc_now_iso())
    base.update(kwargs)
    return CallRecord(**base)


# ---------------------------------------------------------------------------
# The contract refuses the two ways a dashboard can lie
# ---------------------------------------------------------------------------


def test_missing_usage_is_stored_as_missing_not_as_zero() -> None:
    prompt, completion, total, reasoning, source = token_evidence(None)

    assert (prompt, completion, total, reasoning) == (None, None, None, None)
    assert source == "missing"
    row = _call().to_row()
    # A stored zero would later be summed as "this call cost nothing".
    assert row["prompt_tokens"] is None and row["total_tokens"] is None
    assert row["token_source"] == "missing"


def test_a_reported_token_cannot_be_relabeled_missing_and_vice_versa() -> None:
    with pytest.raises(CallLedgerError):
        _attempt(prompt_tokens=0, completion_tokens=0, total_tokens=0,
                 token_source="missing")
    with pytest.raises(CallLedgerError):
        _attempt(prompt_tokens=5, token_source="missing")
    with pytest.raises(CallLedgerError):
        _attempt(token_source="measured")


def test_an_unmeasured_latency_cannot_store_a_duration() -> None:
    with pytest.raises(CallLedgerError):
        _attempt(elapsed_ms=120, latency_source="unknown")


def test_a_skipped_candidate_is_visible_but_is_not_a_provider_call() -> None:
    skipped = _attempt(outcome="error", error_code="tools_not_supported",
                       dispatched=False)
    assert skipped.to_row()["dispatched"] == 0
    with pytest.raises(CallLedgerError):
        _attempt(dispatched=False, elapsed_ms=10)
    with pytest.raises(CallLedgerError):
        _attempt(dispatched=False, outcome="success")


def test_cost_stays_an_estimate_and_names_its_basis() -> None:
    # The catalog price snapshot, not an invoice: the basis is stored so a
    # reader can tell a configured price from a real bill.
    usd, krw, basis = cost_estimate("google/gemini-3.1-flash-lite", 1_000_000, 1_000_000)
    assert basis == "configured_snapshot" and usd and usd > 0 and krw > usd
    assert cost_estimate("agnes-ai/agnes-3.0-flash", 10, 10) == (None, None, "unknown")
    assert cost_estimate("google/gemini-3.1-flash-lite", None, 10) == (None, None, "unknown")


def test_identity_columns_refuse_an_email_and_accept_an_opaque_ref() -> None:
    with pytest.raises(CallLedgerError):
        _call(subject_ref="member@customer.example")
    assert _call(subject_ref="usr_9f2c1a0b").subject_ref == "usr_9f2c1a0b"


def test_a_product_named_by_a_caller_stays_a_declaration() -> None:
    # B14 observed the dispatch, not who the caller says they are.
    declared = _call(product="chat")
    assert declared.origin_source == "caller_declared"
    assert _call().origin_source == "unknown"
    assert origin_from_headers(None)["product"] == "unknown"


def test_the_parent_attempt_count_cannot_disagree_with_the_child_rows() -> None:
    first = _attempt(attempt_index=0, outcome="error", error_code="upstream_timeout",
                     elapsed_ms=30, latency_source="measured")
    second = _attempt(attempt_index=1, outcome="success", elapsed_ms=80,
                      latency_source="measured")
    with pytest.raises(CallLedgerError):
        _call(attempts=(first, second), attempt_count=1)


# ---------------------------------------------------------------------------
# Store: idempotent append, bound parameters, and aggregates that do not double
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_record_writes_one_parent_and_every_attempt() -> None:
    binding = FakeD1()
    store = CallLedgerStore(binding)
    draft = LedgerDraft(log_id=new_log_id(), request_id="b14req_x",
                        endpoint="/api/pilot/v1/chat/completions",
                        protocol="chat/completions", streaming=False,
                        requested_model_id=MODEL_ID, started_at=utc_now_iso())
    draft.record_attempt(provider="Agnes AI", model_id=MODEL_ID, outcome="error",
                         error_code="upstream_timeout", elapsed_ms=12)
    draft.record_attempt(provider="Agnes AI", model_id=MODEL_ID, outcome="success",
                         elapsed_ms=40, usage={"prompt_tokens": 5,
                         "completion_tokens": 7, "total_tokens": 12},
                         finish_reason="stop")
    record = draft.finish(outcome="success", http_status=200, elapsed_ms=60,
                          usage={"prompt_tokens": 5, "completion_tokens": 7,
                                 "total_tokens": 12},
                          selected_model_id=MODEL_ID, selected_provider="Agnes AI",
                          fallback_used=False)

    assert await store.record(record) == "written"
    parent = binding.calls[0]
    assert parent[0] == "run" and "INSERT OR IGNORE INTO b14_model_call " in parent[1]
    assert "success" in parent[2]
    # Each attempt is its own row, so the timeout that preceded the answer is
    # still readable after the fallback succeeded.
    attempts = [call for call in binding.calls if "b14_model_call_attempt" in call[1]]
    assert len(attempts) == 2
    assert "error" in attempts[0][2] and "success" in attempts[1][2]


@pytest.mark.asyncio
async def test_a_retried_write_does_not_create_a_second_record() -> None:
    binding = FakeD1()
    store = CallLedgerStore(binding)
    record = _call(attempt_count=0)

    assert await store.record(record) == "written"
    assert await store.record(record) == "written"
    parents = [sql for _kind, sql, _p in binding.calls if "b14_model_call_attempt" not in sql]
    assert parents and all("INSERT OR IGNORE" in sql for sql in parents)


@pytest.mark.asyncio
async def test_filter_values_are_bound_never_interpolated() -> None:
    binding = FakeD1()
    store = CallLedgerStore(binding)
    injection = "x' OR 1=1; DROP TABLE b14_model_call;--"

    await store.list_calls(filters={"request_id": injection}, limit=5)

    sql = binding.calls[0][1]
    params = binding.calls[0][2]
    assert injection not in sql
    assert injection in params
    assert "DROP TABLE" not in sql


@pytest.mark.asyncio
async def test_an_unknown_filter_or_dimension_is_refused() -> None:
    store = CallLedgerStore(FakeD1())
    with pytest.raises(ValueError):
        await store.list_calls(filters={"prompt_tokens": 5})
    with pytest.raises(ValueError):
        await store.aggregate("subject_ref")


@pytest.mark.asyncio
async def test_aggregates_group_the_logical_request_not_its_attempts() -> None:
    binding = FakeD1()
    store = CallLedgerStore(binding)

    await store.aggregate("selected_model_id", limit=1000)

    sql = binding.calls[0][1]
    assert "FROM b14_model_call " in sql and "b14_model_call_attempt" not in sql
    assert "GROUP BY selected_model_id" in sql
    # The bound limit is capped, so a request cannot ask for an unbounded scan.
    assert binding.calls[0][2][-1] <= 200


@pytest.mark.asyncio
async def test_a_storage_fault_never_reaches_the_model_call() -> None:
    store = CallLedgerStore(ExplodingD1())

    assert await store.record(_call()) == "storage_unavailable"


@pytest.mark.asyncio
async def test_an_unbound_deployment_reports_unconfigured_instead_of_empty() -> None:
    from app.pilot.call_ledger_store import record_call, storage_state

    assert storage_state(SimpleNamespace()) == "not_configured"
    assert await record_call(_call(), env=SimpleNamespace()) == "not_configured"


# ---------------------------------------------------------------------------
# The gateway writes what actually happened
# ---------------------------------------------------------------------------


@pytest.fixture()
def live_lane(monkeypatch):
    # runtime_config is a singleton read at import, so a test that only sets
    # the environment would still be judged as mock mode by the gateway.
    from app.pilot.b14_runtime_config import runtime_config

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", "sk-fixture-agnes-0123456789")
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(runtime_config, "provider_mode", "live")


def _ok(upstream_model="agnes-3.0-flash", tokens=(5, 7, 12)):
    return {
        "id": "cmpl_fixture", "object": "chat.completion", "model": upstream_model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1],
                  "total_tokens": tokens[2]},
        "_live": True, "_requested_upstream_model": upstream_model,
        "_actual_response_model": upstream_model,
    }


@pytest.mark.asyncio
async def test_a_real_call_appends_one_parent_with_the_answered_model(live_lane, monkeypatch):
    written = []

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setattr(gw, "record_call", capture)
    async def answered(**_kwargs):
        return _ok()

    monkeypatch.setattr(plat, "call_platform_chat_completions", answered)

    response = await gw._handle_alpha_chat(
        "b14req_ledger01",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
        origin_headers={"x-padiem-product": "engine", "x-request-id": "corr-12345678"},
    )
    await drain()

    assert response.status_code == 200
    assert len(written) == 1
    record = written[0]
    assert record.outcome == "success" and record.http_status == 200
    assert record.selected_model_id == MODEL_ID
    assert record.actual_response_model == "agnes-3.0-flash"
    assert (record.prompt_tokens, record.total_tokens) == (5, 12)
    assert record.token_source == "measured"
    # The physical attempt is a row of its own even when nothing fell back.
    assert record.attempt_count == 1 == len(record.attempts)
    assert record.attempts[0].elapsed_ms is not None
    assert record.attempts[0].latency_source == "measured"
    assert record.product == "engine" and record.origin_source == "caller_declared"
    assert record.origin_request_id == "corr-12345678"


@pytest.mark.asyncio
async def test_a_retry_keeps_the_failed_attempt_visible(live_lane, monkeypatch):
    from app.pilot.errors import UpstreamServerError

    written = []
    behaviours = [UpstreamServerError(), _ok()]

    async def fake_call(**_kwargs):
        behaviour = behaviours.pop(0)
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(plat, "call_platform_chat_completions", fake_call)

    response = await gw._handle_alpha_chat(
        "b14req_ledger02",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}],
         "business14": {"max_retries": 1}},
    )
    await drain()

    assert response.status_code == 200
    record = written[0]
    outcomes = [attempt.outcome for attempt in record.attempts]
    # The answer alone would report a clean single call; the ledger has to keep
    # the failed provider attempt in the same record.
    assert outcomes == ["error", "success"]
    assert record.attempts[0].error_code == "upstream_server_error"
    assert record.attempt_count == 2
    assert (record.prompt_tokens, record.completion_tokens) == (5, 7)


@pytest.mark.asyncio
async def test_a_failed_call_still_leaves_a_record_with_its_error(live_lane, monkeypatch):
    from app.pilot.errors import UpstreamAuthFailed

    written = []

    async def deny(**_kwargs):
        raise UpstreamAuthFailed()

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(plat, "call_platform_chat_completions", deny)

    response = await gw._handle_alpha_chat(
        "b14req_ledger03",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
    )
    await drain()

    assert response.status_code in (401, 502)
    record = written[0]
    assert record.outcome == "error" and record.error_code == "upstream_auth_failed"
    assert record.attempts[0].outcome == "error"
    assert record.token_source == "missing" and record.prompt_tokens is None


@pytest.mark.asyncio
async def test_a_mock_answer_writes_no_execution_record(live_lane, monkeypatch):
    written = []

    async def capture(record):
        written.append(record)
        return "written"

    from app.pilot.b14_runtime_config import runtime_config

    # A coherent mock state: both the singleton and the effective platform mode
    # say mock, so the only reason this call writes no row is that no provider
    # call happened.
    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(runtime_config, "provider_mode", "mock")
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")

    response = await gw._handle_alpha_chat(
        "b14req_ledger04",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
    )
    await drain()

    assert response.status_code == 200
    # A simulated answer is not consumption; recording it would teach the
    # dashboard to count calls that never reached a provider.
    assert written == []


# ---------------------------------------------------------------------------
# The admin read surface
# ---------------------------------------------------------------------------


@pytest.fixture()
def store_client():
    binding = FakeD1(rows=[{
        "log_id": "b14call_fixture0000000001", "request_id": "b14req_1",
        "product": "chat", "outcome": "success", "selected_model_id": MODEL_ID,
        "prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12,
        "token_source": "measured", "cost_basis": "unknown",
    }])
    app = create_app()
    app.state.call_ledger_store = CallLedgerStore(binding)
    with TestClient(app) as client:
        yield client, binding


@pytest.mark.no_b14_service_proof
def test_an_unproven_caller_cannot_read_the_ledger_even_in_mock_mode(
    store_client, monkeypatch
):
    from app.pilot.b14_runtime_config import runtime_config

    client, _binding = store_client
    # The completion lanes skip the proof when no provider credential is spent.
    # A ledger read has no such exemption: mock mode must not leak real rows.
    monkeypatch.setattr(runtime_config, "provider_mode", "mock")

    response = client.get(LIST_PATH)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "b14_service_proof_required"


def test_list_returns_the_stored_rows_and_names_its_gaps(store_client):
    client, _binding = store_client

    response = client.get(LIST_PATH)

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["storage_state"] == "bound"
    assert payload["calls"][0]["log_id"] == "b14call_fixture0000000001"
    assert "estimated_usd" in payload["evidence_note"]


def test_list_applies_filters_as_bound_parameters(store_client):
    client, binding = store_client

    response = client.get(
        f"{LIST_PATH}?product=chat&since=2026-10-01T00:00:00Z&limit=7"
    )

    assert response.status_code == 200
    select = binding.calls[0]
    assert "product = ?" in select[1] and "started_at >= ?" in select[1]
    assert "chat" in select[2] and "2026-10-01T00:00:00Z" in select[2]
    assert select[2][-1] == 7


def test_an_unknown_query_parameter_is_refused_before_any_scan(store_client):
    client, _binding = store_client

    response = client.get(f"{LIST_PATH}?prompt_tokens=5")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_query"


def test_an_unbound_deployment_says_so_instead_of_showing_an_empty_dashboard():
    app = create_app()
    with TestClient(app) as client:
        response = client.get(LIST_PATH)

    assert response.status_code == 503
    assert response.json()["storage_state"] == "not_configured"


def test_detail_returns_the_attempts_of_one_call_in_order(store_client):
    client, binding = store_client
    binding.first_row = {
        "log_id": "b14call_fixture0000000001", "request_id": "b14req_1",
        "outcome": "success", "token_source": "missing", "prompt_tokens": None,
    }

    response = client.get(DETAIL_PATH.format(log_id="b14call_fixture0000000001"))

    assert response.status_code == 200
    body = response.json()
    assert body["call"]["token_source"] == "missing"
    assert "attempts" in body["call"]


def test_detail_refuses_a_malformed_id_and_reports_unknown_404(store_client):
    client, _binding = store_client

    assert client.get(DETAIL_PATH.format(log_id="b14req_not_a_log_id")).status_code == 422
    missing = client.get(DETAIL_PATH.format(log_id="b14call_absent000000000001"))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "call_not_found"


def test_aggregate_reports_its_unit_so_a_fallback_is_counted_once(store_client):
    client, binding = store_client

    response = client.get(f"{AGGREGATE_PATH}?group_by=selected_provider")

    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "logical_request"
    assert payload["group_by"] == "selected_provider"
    assert "GROUP BY selected_provider" in binding.calls[0][1]


def test_aggregate_refuses_an_unknown_dimension(store_client):
    client, _binding = store_client

    response = client.get(f"{AGGREGATE_PATH}?group_by=subject_ref")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_group_by"


@pytest.mark.asyncio
async def test_a_simulated_answer_writes_no_row_even_if_the_config_says_live(
    live_lane, monkeypatch
):
    written = []

    async def capture(record):
        written.append(record)
        return "written"

    async def answered(**_kwargs):
        return _ok()

    # The platform adapter resolves an explicit B14_PROVIDER_MODE ahead of the
    # config singleton, so this is the state where the two disagree. The answer
    # came from the mock envelope, and only that fact decides the write.
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(plat, "call_platform_chat_completions", answered)

    response = await gw._handle_alpha_chat(
        "b14req_ledger05",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
    )
    await drain()

    assert response.status_code == 200
    assert written == []


@pytest.mark.asyncio
async def test_a_real_call_writes_a_row_even_if_the_config_still_says_mock(
    live_lane, monkeypatch
):
    written = []

    async def capture(record):
        written.append(record)
        return "written"

    async def answered(**_kwargs):
        return _ok()

    from app.pilot.b14_runtime_config import runtime_config

    monkeypatch.setattr(runtime_config, "provider_mode", "mock")
    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(plat, "call_platform_chat_completions", answered)

    response = await gw._handle_alpha_chat(
        "b14req_ledger06",
        {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
    )
    await drain()

    assert response.status_code == 200
    # The adapter dispatched for real (its own env said live), so dropping this
    # record would understate consumption.
    assert len(written) == 1 and written[0].outcome == "success"


@pytest.mark.asyncio
async def test_the_stream_lane_records_ttft_and_the_usage_the_provider_reported(
    monkeypatch,
):
    import httpx

    from app.pilot import stream_gateway as sg
    from app.pilot.b14_runtime_config import runtime_config

    written = []

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setattr(sg, "record_call", capture)

    def frame(payload):
        return f"data: {json.dumps(payload)}\n\n".encode()

    sse = [
        frame({"id": "up_1", "model": "gemini-3.1-flash-lite", "choices": [
            {"index": 0, "delta": {"content": "답"}, "finish_reason": None}]}),
        frame({"id": "up_1", "model": "gemini-3.1-flash-lite", "choices": [
            {"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10}}),
        b"data: [DONE]\n\n",
    ]
    app = create_app()
    app.state.stream_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"".join(sse), headers={"Content-Type": "text/event-stream"}
        )
    )
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        response = client.post(
            "/api/pilot/v1/chat/completions/stream-preview",
            json={"model": "google/gemini-3.1-flash-lite", "stream": True,
                  "messages": [{"role": "user", "content": "한 마디만"}]},
        )
        assert response.status_code == 200, response.text
        body = response.text

    await drain()
    assert "답" in body
    assert len(written) == 1
    record = written[0]
    assert record.streaming is True
    assert record.outcome == "success"
    assert record.attempt_count == 1 and record.attempts[0].dispatched is True
    # TTFT is measured, not assumed: it exists only because a visible token did.
    assert record.ttft_ms is not None and record.ttft_ms >= 0
    assert (record.prompt_tokens, record.total_tokens) == (4, 10)
    assert record.token_source == "measured"
    assert record.actual_response_model == "gemini-3.1-flash-lite"
    assert record.selected_model_id == "google/gemini-3.1-flash-lite"


@pytest.mark.asyncio
async def test_an_aborted_stream_still_leaves_its_record(monkeypatch):
    import httpx

    from app.pilot import stream_gateway as sg
    from app.pilot.b14_runtime_config import runtime_config
    from app.pilot.errors import UpstreamServerError

    written = []

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setattr(sg, "record_call", capture)

    first = {
        "id": "up_1", "model": "gemini-3.1-flash-lite",
        "choices": [{"index": 0, "delta": {"content": "답"}, "finish_reason": None}],
    }

    def chunks():
        yield f"data: {json.dumps(first)}\n\n".encode()
        raise UpstreamServerError()

    class _Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for chunk in chunks():
                yield chunk

        async def aclose(self):
            return None

    app = create_app()
    app.state.stream_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, stream=_Stream(), headers={"Content-Type": "text/event-stream"}
        )
    )
    from starlette.testclient import TestClient

    with TestClient(app) as client:
        body = client.post(
            "/api/pilot/v1/chat/completions/stream-preview",
            json={"model": "google/gemini-3.1-flash-lite", "stream": True,
                  "messages": [{"role": "user", "content": "한 마디만"}]},
        ).text

    await drain()
    assert "event: error" in body
    assert len(written) == 1
    record = written[0]
    # A stream that produced output and then died still consumed the call. The
    # record has to say so instead of disappearing with the connection.
    assert record.outcome == "error"
    assert record.attempts[0].outcome == "error"
    assert record.attempts[0].error_code == "upstream_server_error"
    assert record.ttft_ms is not None

# #5318: bind one queue per test, matching the Worker request lifecycle.
@pytest.fixture(autouse=True)
def deferred_write_scope():
    token = bind_deferred()
    try:
        yield
    finally:
        reset_deferred(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["draft", "attempt", "finish"])
@pytest.mark.parametrize("outcome", ["success", "error"])
async def test_ledger_construction_fault_preserves_status_and_exact_body(
    live_lane, monkeypatch, caplog, stage, outcome,
):
    from app.pilot.errors import UpstreamAuthFailed

    written = []

    async def answer(**kwargs):
        if outcome == "error":
            raise UpstreamAuthFailed()
        return _ok()

    async def capture(record):
        written.append(record)
        return "written"

    monkeypatch.setattr(plat, "call_platform_chat_completions", answer)
    monkeypatch.setattr(gw, "record_call", capture)
    monkeypatch.setattr(gw.time, "perf_counter", lambda: 100.0)
    body = {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]}
    baseline = await gw._handle_alpha_chat("b14req_failopen", body)
    await drain()
    written.clear()

    def broken(*args, **kwargs):
        raise ValueError("PRIVATE_LEDGER_PAYLOAD")

    if stage == "draft":
        monkeypatch.setattr(gw, "LedgerDraft", broken)
    else:
        monkeypatch.setattr(LedgerDraft, "record_attempt" if stage == "attempt" else "finish", broken)
    response = await gw._handle_alpha_chat("b14req_failopen", body)
    assert response.status_code == baseline.status_code
    assert response.body == baseline.body
    if outcome == "success":
        assert response.status_code == 200
    await drain()
    assert written == []
    assert "b14_ledger_skipped request_id=b14req_failopen reason=ValueError" in caplog.text
    assert "PRIVATE_LEDGER_PAYLOAD" not in caplog.text


@pytest.mark.asyncio
async def test_slow_record_call_starts_only_after_answer_and_explicit_drain(
    live_lane, monkeypatch,
):
    import asyncio

    started, finished = asyncio.Event(), asyncio.Event()

    async def answer(**kwargs):
        return _ok()

    async def slow(record):
        started.set()
        await asyncio.sleep(0.05)
        finished.set()
        return "written"

    monkeypatch.setattr(plat, "call_platform_chat_completions", answer)
    monkeypatch.setattr(gw, "record_call", slow)
    response = await gw._handle_alpha_chat(
        "b14req_deferred", {"model": MODEL_ID, "messages": [{"role": "user", "content": "ok"}]},
    )
    assert response.status_code == 200
    assert not started.is_set()
    pending = asyncio.create_task(drain())
    await started.wait()
    assert not finished.is_set()
    assert not pending.done()
    await pending
    assert finished.is_set()
    await drain()  # A second drain never writes the same record twice.


@pytest.mark.asyncio
async def test_background_timeout_cancels_write_without_exposing_payload(monkeypatch, caplog):
    import asyncio
    from app.pilot import deferred_writes as deferred

    cancelled = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(deferred, "WRITE_TIMEOUT_SECONDS", 0.01)
    deferred.enqueue(slow, request_id="b14req_timeout")
    await drain()
    assert cancelled.is_set()
    assert "b14_ledger_skipped request_id=b14req_timeout reason=TimeoutError" in caplog.text


@pytest.mark.asyncio
async def test_waituntil_keeps_request_d1_context_after_worker_resets_it(monkeypatch):
    import sys
    from types import ModuleType
    from app.pilot import deferred_writes as deferred
    from app.pilot.call_ledger_store import bind_ledger_env, record_call, reset_ledger_env

    ffi = ModuleType("pyodide.ffi")
    ffi.create_proxy = lambda value: value
    monkeypatch.setitem(sys.modules, "pyodide.ffi", ffi)
    pending = []
    binding = FakeD1()
    token = bind_ledger_env(SimpleNamespace(B14_CALL_LEDGER_D1=binding))
    try:
        deferred.enqueue(lambda: record_call(_call()), request_id="b14req_env")
        await drain(SimpleNamespace(waitUntil=pending.append))
    finally:
        reset_ledger_env(token)
    assert binding.calls == []
    assert len(pending) == 1
    await pending.pop()
    assert "b14_model_call " in binding.calls[0][1]
    # A streaming task may enqueue after the Worker's initial drain.
    deferred.enqueue(lambda: record_call(_call(), env=SimpleNamespace(B14_CALL_LEDGER_D1=binding)),
                     request_id="b14req_late")
    assert len(pending) == 1
    await pending.pop()


@pytest.mark.asyncio
async def test_local_asgi_drains_only_after_final_response_body():
    from app.pilot import deferred_writes as deferred

    order = []
    async def write():
        order.append("write")
    async def local_app(scope, receive, send):
        deferred.enqueue(write, request_id="b14req_local")
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"answer", "more_body": False})
    async def send(message):
        order.append(message["type"])
    # Simulate a local ASGI request without the Worker's enclosing queue.
    token = deferred._CURRENT.set(None)
    try:
        await deferred.DeferredWritesMiddleware(local_app)({"type": "http"}, None, send)
        assert deferred._CURRENT.get() is None
    finally:
        deferred._CURRENT.reset(token)
    assert order == ["http.response.start", "http.response.body", "write"]

@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["draft", "attempt", "finish"])
@pytest.mark.parametrize("outcome", ["success", "error"])
async def test_stream_ledger_fault_preserves_exact_response(monkeypatch, caplog, stage, outcome):
    import httpx
    from app.pilot import stream_gateway as sg
    from app.pilot.b14_runtime_config import runtime_config

    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "unit-google-key-not-a-secret")
    monkeypatch.delenv("B14_PROVIDER_MODE", raising=False)
    monkeypatch.setattr(runtime_config, "provider_mode", "live")
    monkeypatch.setattr(sg, "_request_id", lambda: "b14req_streamguard")
    frames = [
        {"id": "up_1", "model": "gemini-3.1-flash-lite",
         "choices": [{"index": 0, "delta": {"content": "answer"}, "finish_reason": None}]},
        {"id": "up_1", "model": "gemini-3.1-flash-lite",
         "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
    ]
    data = b"".join(("data: " + json.dumps(frame) + "\n\n").encode() for frame in frames)
    app = create_app()
    app.state.stream_transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200 if outcome == "success" else 401,
            content=data + b"data: [DONE]\n\n" if outcome == "success" else b'{"error":"denied"}',
            headers={"Content-Type": "text/event-stream" if outcome == "success" else "application/json"},
        )
    )
    body = {"model": "google/gemini-3.1-flash-lite", "stream": True,
            "messages": [{"role": "user", "content": "ok"}]}
    with TestClient(app) as client:
        baseline = client.post("/api/pilot/v1/chat/completions/stream-preview", json=body)
        await drain()
        def broken(*args, **kwargs):
            raise ValueError("PRIVATE_LEDGER_PAYLOAD")
        if stage == "draft":
            monkeypatch.setattr(sg, "LedgerDraft", broken)
        else:
            monkeypatch.setattr(LedgerDraft, "record_attempt" if stage == "attempt" else "finish", broken)
        response = client.post("/api/pilot/v1/chat/completions/stream-preview", json=body)
        await drain()
    assert response.status_code == baseline.status_code
    assert response.content == baseline.content
    assert "PRIVATE_LEDGER_PAYLOAD" not in caplog.text
    assert "b14_ledger_skipped" in caplog.text

@pytest.mark.asyncio
async def test_deferred_queues_are_isolated_between_concurrent_requests():
    import asyncio
    from app.pilot import deferred_writes as deferred

    written = []
    ready = [asyncio.Event(), asyncio.Event()]

    async def request(index):
        token = deferred.bind()
        try:
            async def write():
                written.append(index)
            deferred.enqueue(write, request_id=f"b14req_concurrent_{index}")
            ready[index].set()
            await ready[1 - index].wait()
            await drain()
            await drain()
        finally:
            deferred.reset(token)
    await asyncio.gather(request(0), request(1))
    assert sorted(written) == [0, 1]


@pytest.mark.asyncio
async def test_deferred_write_failure_is_logged_without_exception_text(caplog):
    from app.pilot import deferred_writes as deferred

    async def broken():
        raise RuntimeError("PRIVATE_LEDGER_PAYLOAD")
    deferred.enqueue(broken, request_id="b14req_writefault")
    await drain()
    assert "b14_ledger_skipped request_id=b14req_writefault reason=RuntimeError" in caplog.text
    assert "PRIVATE_LEDGER_PAYLOAD" not in caplog.text
