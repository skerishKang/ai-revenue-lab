"""Measured Engine PC turns reach the authenticated B14 ledger and summary.

The model and PC are fakes. Collector/lifecycle, signing transport, metrics
reporter, B14 authentication, SQLite migrations/store and recent-turn API are
the actual implementations; no provider, PC or external service is contacted.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount

from padiem_ai_core import StreamingExecutionRuntime
from app.b14_service_proof import service_proof_headers
from app.cloudflare_transport import CloudflareB14ServiceBindingTransport
from app.orchestration_service import ORCHESTRATION_STREAM_PATH
from app.pc_work_metrics_reporter import PcWorkMetricsReporter
from app.service import ServiceResponse
from tests.test_6460_pc_action_driver import _payload, _service
from tests.test_5574_pc_read_boundary_end_to_end import (
    DEVICE_ID, LIST_STEP, LIST_WIRE_ROWS, _FakePcEndpoint, _Request,
    _ScriptedModel,
)
from tests.test_cloudflare_transport import FakeResponse
from tests.test_orchestration_service import _NativePcModel


PLATFORM = Path(__file__).resolve().parents[2] / "korean-ai-platform"
# Engine and B14 deliberately both name their application package `app`.
# Load only B14's disjoint pilot namespace, never replace Engine modules.
import app as engine_app
if str(PLATFORM / "app") not in engine_app.__path__:
    engine_app.__path__.append(str(PLATFORM / "app"))

from app.pilot.call_ledger import CallRecord
from app.pilot.call_ledger_store import CallLedgerStore
from app.pilot.pc_work_metrics_routes import router

_spec = importlib.util.spec_from_file_location(
    "pc_metrics_test_b14_sqlite", PLATFORM / "app" / "local_runtime.py")
_sqlite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sqlite)

PROOF = "synthetic-metrics-end-to-end-proof-not-a-real-secret"
RECENT = "/api/pilot/v1/admin/model-calls/pc-turns"
ANSWER = "파일 목록을 확인했습니다."


class _B14Binding:
    """Only the network boundary is in process; production signing stays on."""

    def __init__(self, app):
        self.app = app
        self.responses = []

    async def fetch(self, request):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                    base_url="https://b14.internal") as client:
            response = await client.request(request.method, request.url,
                                            headers=request.headers, content=request.body)
        self.responses.append((response.status_code, response.json()))
        return FakeResponse(status=response.status_code, chunks=[response.content])


class _TruncatedListingPc(_FakePcEndpoint):
    async def fetch(self, request):
        response = await super().fetch(request)
        body = json.loads(request.body)
        if body["mode"] == "dispatch" and body["op"] == "list":
            row = self.rows[next(reversed(self.rows))]
            row["output"] = json.dumps({"ok": True, "entries": json.loads(LIST_WIRE_ROWS),
                                         "truncated": True})
            row["content_bytes"] = len(row["output"].encode())
        return response


@pytest.fixture
def b14_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_B14_SERVICE_PROOF_SECRET", PROOF)
    ledger = _sqlite.SqliteLedger(tmp_path / "actual-b14.sqlite3")
    ledger.apply_migrations()
    store = CallLedgerStore(ledger)
    app = Starlette(routes=[Mount("/api/pilot", app=router)])
    app.state.call_ledger_store = store
    binding = _B14Binding(app)
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding, request_factory=_Request, proof_secret=PROOF)
    reporter = PcWorkMetricsReporter(transport=transport, base_url="https://b14.internal")
    yield app, ledger, store, reporter, binding
    ledger.close()


async def _recent(app, *, signed=True, limit=10):
    headers = service_proof_headers(PROOF, b"") if signed else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                base_url="https://b14.internal") as client:
        return await client.get(RECENT, params={"limit": limit}, headers=headers)


def _turn_payload(route):
    payload = deepcopy(_payload([{"role": "user", "content": "내 PC 파일 목록 보여줘"}], write=False))
    payload["session_id"] = "chat_pcq_" + route.replace("-", "_")
    if route.startswith("native"):
        for key in ("agent_plan", "tool_arguments", "declared_plan"):
            payload.pop(key, None)
        payload["pc_tools"] = {"device_id": DEVICE_ID, "allowed_scopes": ["files"]}
    return payload


async def _anchor(store, collector, suffix):
    """The fake model writes the normal B14 usage anchor, as a provider call does."""
    row = CallRecord(
        log_id="b14call_e2e_" + suffix, request_id="b14req_e2e_" + suffix,
        endpoint="/api/pilot/v1/chat/completions", **collector.ledger_identity,
        started_at="2026-11-01T12:00:00Z", prompt_tokens=100, completion_tokens=20,
        total_tokens=120, token_source="measured",
    )
    assert await store.record(row) == "written"


async def _run_turn(monkeypatch, store, reporter, route):
    from app.pc_work_metrics import current_pc_work_metrics

    class Model(_ScriptedModel):
        async def execute(self, request):
            try:
                collector = current_pc_work_metrics()
                assert collector is not None
                await _anchor(store, collector, route.replace("-", "_") + "_" + str(len(self.prompts)))
                result = await super().execute(request)
                result.usage = {"prompt_tokens": 100}
                return result
            except Exception as exc:
                self.fixture_failure = exc
                raise

    pc = _TruncatedListingPc()
    complete = json.dumps({"action": "complete", "answer": ANSWER})
    model = Model([complete] if route.startswith("native") else [LIST_STEP, complete])
    service = _service(model, pc)
    service._pc_work_metrics_reporter = reporter
    payload = _turn_payload(route)
    if route.startswith("native"):
        class Native(_NativePcModel):
            async def stream(self, request):
                collector = current_pc_work_metrics()
                assert collector is not None
                await _anchor(store, collector, route.replace("-", "_") + "_native")
                async for event in super().stream(request):
                    yield event

        native = Native("files_list")

        async def capable(_):
            return True

        service._pc_tools_capability = capable
        service._pc_streaming_runtime_factory = lambda app_id: StreamingExecutionRuntime(
            app_id=app_id, b14_stream_client=native)

    async def no_poll_delay(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_poll_delay)
    if not route.endswith("stream"):
        response = await service.orchestrate_payload(payload)
        assert response.status_code == 200, (response.body, getattr(model, "fixture_failure", None))
        execution = response.body["orchestration"]["execution"]
    else:
        prepared = await service.prepare_stream(
            method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
            body=json.dumps(payload).encode(), pc_progress=True)
        assert not isinstance(prepared, ServiceResponse), prepared
        events = [json.loads(line) async for line in service.iter_ndjson(prepared)]
        assert all(event.get("ok") is True for event in events), events
        execution = next(event["orchestration"]["execution"] for event in events
                         if "orchestration" in event)
    assert execution["answer"] == ANSWER
    assert execution["metadata"]["status"] == "completed"
    assert pc.ops == ["list"]
    return pc, model


@pytest.mark.parametrize("route", ["json", "stream", "native-json", "native-stream"])
def test_real_turn_counters_attach_to_b14_once_without_changing_usage(b14_metrics, monkeypatch, route):
    app, ledger, store, reporter, binding = b14_metrics

    async def run():
        pc, model = await _run_turn(monkeypatch, store, reporter, route)
        assert binding.responses[-1][0] == 200, binding.responses
        response = await _recent(app, limit=1)
        assert response.status_code == 200
        result = response.json()
        assert result["unit"] == "pc_turn" and result["summary"]["turn_count"] == 1
        measured = result["turns"][0]["metrics"]
        assert measured["outcome"] == "completed"
        assert measured["calls"] == measured["pc_round_trips"] == 1
        assert measured["tool_calls"]["claw.pc.list_files"]["calls"] == 1
        assert measured["truncation_count"] == 1
        assert measured["truncated_bytes"] is None
        assert measured["truncated_bytes_unknown_count"] == 1
        assert measured["timeout_count"] == 0
        assert measured["model_calls"] == len(model.prompts) + int(route.startswith("native"))
        assert measured["model_input_tokens"] == (None if route.startswith("native") else 200)
        assert measured["model_input_tokens_observed"] == 100 * len(model.prompts)
        assert measured["model_input_tokens_missing_calls"] == int(route.startswith("native"))
        assert measured["tool_result_tokens_estimated"] > 0
        assert 0 < measured["tool_result_input_ratio"] < 1
        assert result["summary"]["counters"]["pc_round_trips"]["average"] == 1
        assert result["summary"]["counters"]["truncated_bytes"]["missing_turns"] == 1
        assert (await _recent(app, signed=False)).status_code == 401
        # One turn annotation, even though the PC loop called the model twice.
        rows = ledger.connect().execute(
            "SELECT prompt_tokens,completion_tokens,total_tokens,pc_work_metrics_json "
            "FROM b14_model_call").fetchall()
        assert len(rows) == measured["model_calls"] == 2
        assert all(tuple(row)[:3] == (100, 20, 120) for row in rows)
        assert sum(row[3] is not None for row in rows) == 1
        encoded = json.dumps(result)
        assert PROOF not in encoded and LIST_WIRE_ROWS not in encoded
        assert "meshcentral-padiem-trial.txt" not in encoded

    asyncio.run(run())


def test_actual_pc_timeout_is_retained_in_recent_two_turn_summary(b14_metrics, monkeypatch):
    app, ledger, store, reporter, binding = b14_metrics

    async def run():
        from app.pc_work_metrics import current_pc_work_metrics

        await _run_turn(monkeypatch, store, reporter, "stream")

        class TimeoutPc(_FakePcEndpoint):
            async def fetch(self, request):
                if json.loads(request.body)["mode"] == "command_status":
                    raise TimeoutError("synthetic PC transport timeout")
                return await super().fetch(request)

        class Model(_ScriptedModel):
            async def execute(self, request):
                await _anchor(store, current_pc_work_metrics(), "timeout_" + str(len(self.prompts)))
                return await super().execute(request)

        # No model can turn a missing PC result into a successful answer.
        # The only scripted decision dispatches the real common list handler.
        model, pc = Model([LIST_STEP]), TimeoutPc()
        service = _service(model, pc)
        service._pc_work_metrics_reporter = reporter
        payload = _turn_payload("timeout_stream")
        prepared = await service.prepare_stream(
            method="POST", path=ORCHESTRATION_STREAM_PATH, content_type="application/json",
            body=json.dumps(payload).encode(), pc_progress=True)
        assert not isinstance(prepared, ServiceResponse), prepared
        events = [json.loads(line) async for line in service.iter_ndjson(prepared)]
        assert any(event.get("ok") is False for event in events), events
        assert pc.ops == ["list"]
        assert binding.responses[-1][0] == 200, binding.responses

        result = (await _recent(app, limit=2)).json()
        assert result["summary"]["turn_count"] == 2
        assert result["summary"]["outcomes"] == {"completed": 1, "failed": 1}
        failed = next(row["metrics"] for row in result["turns"]
                      if row["metrics"]["outcome"] == "failed")
        assert failed["calls"] == failed["pc_round_trips"] == failed["timeout_count"] == 1
        assert failed["tool_calls"]["claw.pc.list_files"]["timeout_count"] == 1
        assert failed["truncation_count"] == 0
        assert result["summary"]["counters"]["timeout_count"] == {
            "average": 0.5, "max": 1, "observed_turns": 2, "missing_turns": 0,
        }
        assert result["summary"]["tools"][0]["pc_round_trips"] == 2
        assert len((await _recent(app, limit=1)).json()["turns"]) == 1
        assert ledger.connect().execute(
            "SELECT count(*) FROM b14_model_call WHERE pc_work_metrics_json IS NOT NULL"
        ).fetchone()[0] == 2

    asyncio.run(run())
