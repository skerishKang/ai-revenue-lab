"""#3930: full B54 signed-route -> P01 -> Engine client -> Service Binding NDJSON -> SSE.

Fake Engine *bytes only*: all other layers are the actual production classes.
No Cloudflare or model credentials and no production activation.
"""
from __future__ import annotations

import asyncio
import json
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.responses import JSONResponse

from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration import OrchestrationResult
from padiem_ai_engine_client import (
    ENGINE_ORCHESTRATE_STREAM_PATH,
    PadiemAiEngineClient,
)
from kagent.p01_adapter import P01_AGENT_ID, P01_APP_ID, P01CoreOrchestrationAdapter, P01RequestFactory
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from app.worker_orchestration import CloudflareEngineServiceTransport
from test_b54_claw_general_p01_routing import _client, _payload
from test_3930_engine_ndjson_stream_port import FakeRequest, FakeReader


CAP = "/api/claw/general/capabilities"
GENERAL = "/api/claw/general"
LIVE = {"X-Padiem-Claw-Live": "p01-events-v1"}
SUBJECT = "sub_" + "9" * 32


class _ResultFactory:
    """Construct only Engine-origin wire evidence for the true production ports."""
    @staticmethod
    def result(request, kinds):
        events = tuple(
            public_orchestration_event(
                event_id=f"evt_{sequence:03d}",
                run_id="orch_binding_001",
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                kind=kind,
                sequence=sequence,
                message="internal-secret-never-export",
                timestamp_iso="2026-10-10T00:00:00+00:00",
            )
            for sequence, kind in enumerate(kinds, start=1)
        )
        return OrchestrationResult(
            execution_result=ExecutionResult(
                answer="완료 답변",
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=request.context.trace_id,
                    app_id=request.app_id,
                    agent_id=P01_AGENT_ID,
                    session_id=request.execution_request.session_id,
                    status=RunStatus.COMPLETED,
                ),
            ),
            context=request.context,
            app_id=request.app_id,
            subject_id=request.subject_id,
            plan=None,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=events,
        )


class CapturingFactory(P01RequestFactory):
    def __init__(self, engine):
        super().__init__(allow_subject_identity=True)
        self.engine = engine

    def build(self, run, **kwargs):
        bundle = super().build(run, **kwargs)
        self.engine.core_request = bundle.orchestration_request
        return bundle


class EngineBindingFixture:
    """The only fake: Engine-origin response bytes and async JS reader."""
    def __init__(self, mode="completed"):
        self.mode = mode
        self.core_request = None
        self.calls = []
        self.readers = []

    async def fetch(self, request):
        self.calls.append(request)
        assert request.url.endswith(ENGINE_ORCHESTRATE_STREAM_PATH)
        assert request.method == "POST"
        payload = json.loads(request.body)
        assert payload["app_id"] == P01_APP_ID
        assert payload["subject_id"] == SUBJECT
        assert self.core_request is not None
        assert payload["execution_context"]["trace_id"] == self.core_request.context.trace_id
        kinds = (OrchestrationEventKind.RUN_STARTED,
                 OrchestrationEventKind.CONTEXT_PREPARED,
                 OrchestrationEventKind.RUN_COMPLETED)
        result = _ResultFactory.result(self.core_request, kinds)
        wire = result.to_public_dict()
        if self.mode == "foreign":
            wire["events"][1]["trace_id"] = "trace_foreign"
        frames = [{"ok": True, "event": deepcopy(e)} for e in wire["events"]]
        if self.mode == "truncated":
            frames = frames[:2]
        elif self.mode == "provider_error":
            frames = frames[:1] + [{"ok": False, "error": {"code": "provider_error", "secret": "private"}}]
        elif self.mode == "result_mismatch":
            wire["events"][1]["event_id"] = "evt_changed"
            frames.append({"ok": True, "orchestration": wire})
        elif self.mode == "foreign":
            frames.append({"ok": True, "orchestration": wire})
        else:
            frames.append({"ok": True, "orchestration": wire})
        data = b"".join((json.dumps(f, ensure_ascii=False, separators=(",", ":")) + "\n").encode() for f in frames)
        chunks = [data[:11], data[11:50], data[50:127], data[127:]]
        reader = FakeReader(chunks)
        self.readers.append(reader)
        status = 502 if self.mode == "http_502" else 429 if self.mode == "http_429" else 200
        content_type = "application/json" if status != 200 else "application/x-ndjson"
        return SimpleNamespace(
            status=status,
            headers={"content-type": content_type},
            body=SimpleNamespace(getReader=lambda: reader),
        )


class TestRealP01StreamBridge(unittest.TestCase):
    def bridge(self, mode="completed"):
        engine = EngineBindingFixture(mode)
        transport = CloudflareEngineServiceTransport(engine, request_factory=FakeRequest)
        client = PadiemAiEngineClient(
            transport=transport,
            app_id=P01_APP_ID,
            caller_id=P01_APP_ID,
            credential="test-only-internal-credential-" + "x" * 40,
        )
        runner = P01EngineOrchestrationClient(client, allow_subject_identity=True)
        adapter = P01CoreOrchestrationAdapter(
            runner,
            request_factory=CapturingFactory(engine),
            allow_subject_identity=True,
        )
        return adapter, engine

    def query(self, adapter, engine, *, live=True, disabled=False):
        session = SimpleNamespace(auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=SUBJECT)
        ))
        with patch(
            "app.b54_canonical_session.resolve_current_b54_canonical_session",
            return_value=session,
        ):
            with _client(adapter) as client:
                client.app.state.claw_live_sse_enabled = not disabled
                cap = client.get(CAP)
                response = client.post(GENERAL, json=_payload(), headers=LIVE if live else {})
        return cap, response

    def test_real_streamed_engine_bytes_become_authenticated_claw_sse(self):
        adapter, engine = self.bridge()
        cap, response = self.query(adapter, engine)
        self.assertEqual(cap.json(), {"live_events_available": True})
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: p01_event", response.text)
        self.assertIn('"kind":"run_started"', response.text)
        self.assertIn('"kind":"context_prepared"', response.text)
        self.assertIn('"kind":"run_completed"', response.text)
        self.assertEqual(response.text.count("event: done"), 1)
        self.assertEqual(response.text.count("event: delta"), 1)
        self.assertIn("완료 답변", response.text)
        self.assertEqual(len(engine.calls), 1)
        self.assertEqual(engine.readers[0].released, 1)
        self.assertEqual(engine.readers[0].cancelled, 0)

    def test_untrusted_or_incomplete_engine_result_cannot_emit_done(self):
        for mode in ("truncated", "provider_error", "foreign", "result_mismatch", "http_429", "http_502"):
            with self.subTest(mode=mode):
                adapter, engine = self.bridge(mode)
                _, response = self.query(adapter, engine)
                self.assertEqual(response.status_code, 200)
                self.assertIn("event: error", response.text)
                self.assertNotIn("event: done", response.text)
                self.assertNotIn('"kind":"run_completed"', response.text)
                self.assertNotIn("private", response.text)
                self.assertEqual(len(engine.calls), 1)

    def test_unavailable_flag_denies_before_engine_dispatch(self):
        adapter, engine = self.bridge()
        cap, response = self.query(adapter, engine, disabled=True)
        self.assertFalse(cap.json()["live_events_available"])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(engine.calls, [])

    def test_normal_completed_route_does_not_invoke_stream_engine(self):
        adapter, engine = self.bridge()
        _, response = self.query(adapter, engine, live=False)
        # The ordinary route dispatches once to the completed Engine target,
        # not the new stream path. This fake only serves the stream endpoint,
        # so the completed lane returns the historical bounded 502.
        self.assertEqual(response.status_code, 502)
        self.assertEqual(len(engine.calls), 1)
        self.assertFalse(engine.calls[0].url.endswith(ENGINE_ORCHESTRATE_STREAM_PATH))

    def test_revoked_canonical_session_denies_before_stream_or_quota(self):
        adapter, engine = self.bridge()
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
                   new=AsyncMock(return_value=None)):
            with _client(adapter) as client:
                client.app.state.claw_live_sse_enabled = True
                cap = client.get(CAP)
                denied = client.post(GENERAL, json=_payload(), headers=LIVE)
        self.assertEqual(cap.json(), {"live_events_available": False})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json()["error"]["code"], "canonical_b54_session_unavailable")
        self.assertEqual(engine.calls, [])

    def test_live_quota_denial_precedes_all_engine_dispatch(self):
        adapter, engine = self.bridge()
        session = SimpleNamespace(auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=SUBJECT)
        ))
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
                   new=AsyncMock(return_value=session)):
            with patch("app.claw_general_routes._usage_gate_denial",
                       new=AsyncMock(return_value=JSONResponse(
                           {"error": {"code": "rate_limited"}}, status_code=429))):
                with _client(adapter) as client:
                    client.app.state.claw_live_sse_enabled = True
                    blocked = client.post(GENERAL, json=_payload(), headers=LIVE)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(engine.calls, [])

    def test_capability_preflight_does_not_dispatch_engine(self):
        adapter, engine = self.bridge()
        session = SimpleNamespace(auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=SUBJECT)
        ))
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
                   new=AsyncMock(return_value=session)):
            with _client(adapter) as client:
                client.app.state.claw_live_sse_enabled = True
                response = client.get(CAP)
        self.assertTrue(response.json()["live_events_available"])
        self.assertEqual(engine.calls, [])

    def test_real_engine_binding_stream_cancel_releases_reader(self):
        from app.claw_general_routes import create_claw_run
        from app.claw_live_events import live_claw_sse
        from padiem_control_plane.product_tier_routes import ProductTierLabel

        class StallingReader(FakeReader):
            async def read(self):
                if self.parts:
                    return await super().read()
                await asyncio.Event().wait()

        class StallingBinding(EngineBindingFixture):
            async def fetch(self, request):
                self.calls.append(request)
                assert request.url.endswith(ENGINE_ORCHESTRATE_STREAM_PATH)
                core = self.core_request
                assert core is not None
                result = _ResultFactory.result(core, (
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.CONTEXT_PREPARED,
                    OrchestrationEventKind.RUN_COMPLETED,
                ))
                first = result.events[0].to_public_dict()
                event_line = (json.dumps({"ok": True, "event": first}) + "\n").encode()
                reader = StallingReader([event_line])
                self.readers.append(reader)
                return SimpleNamespace(
                    status=200,
                    headers={"content-type": "application/x-ndjson"},
                    body=SimpleNamespace(getReader=lambda: reader),
                )

        async def exercise():
            engine = StallingBinding()
            transport = CloudflareEngineServiceTransport(engine, request_factory=FakeRequest)
            client = PadiemAiEngineClient(
                transport=transport, app_id=P01_APP_ID, caller_id=P01_APP_ID,
                credential="test-only-internal-credential-" + "x" * 40,
            )
            runner = P01EngineOrchestrationClient(client, allow_subject_identity=True)
            adapter = P01CoreOrchestrationAdapter(
                runner, request_factory=CapturingFactory(engine), allow_subject_identity=True
            )
            run = create_claw_run("padiem-chat", "연결 종료 테스트")
            response = live_claw_sse(adapter, run, {
                "product_tier": ProductTierLabel.PLUS,
                "subject_id": SUBJECT,
            })
            iterator = response.body_iterator
            first = await asyncio.wait_for(anext(iterator), 3)
            assert b"event: p01_event" in first
            assert b"run_started" in first
            await asyncio.wait_for(iterator.aclose(), 3)
            await asyncio.sleep(0)
            assert len(engine.calls) == 1
            assert engine.readers[0].cancelled == 1
            assert engine.readers[0].released == 1

        asyncio.run(exercise())

    def test_user_selected_model_is_pinned_in_single_stream_dispatch(self):
        # An opaque test-only syntactically valid choice; actual provider
        # registration remains the Engine/B14-owned admission decision.
        selected_id = "test/explicit-model-1"
        adapter, engine = self.bridge()
        session = SimpleNamespace(auth_session=SimpleNamespace(
            subject=SimpleNamespace(subject_id=SUBJECT)
        ))
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
                   new=AsyncMock(return_value=session)):
            with _client(adapter) as client:
                client.app.state.claw_live_sse_enabled = True
                response = client.post(GENERAL, json=_payload(
                    model_id=selected_id
                ), headers=LIVE)
        self.assertEqual(response.status_code, 200)
        self.assertIn("event: done", response.text)
        self.assertEqual(len(engine.calls), 1)
        wire = json.loads(engine.calls[0].body)
        self.assertEqual(wire["agent"]["model_policy"]["model"], selected_id)
        self.assertEqual(wire.get("max_retries", 0), 0)
