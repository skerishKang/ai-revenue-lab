"""P01 live Engine consumer contract regression (#3930)."""
import asyncio
from copy import deepcopy
from padiem_ai_core import OrchestrationResult
from padiem_ai_engine_client import PadiemAiEngineClientError
from kagent.p01_adapter import P01AdapterError, P01DispatchClass
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.p01_approval_pause_transport import P01PausedWireResult
from model_route_fixture import SyntheticPlusRouteTestCase
from test_p01_orchestration_client import _build_request, _public_result, _paused_public_result

class StreamingFixture:
    def __init__(self, events, result, error=None):
        self.events, self.result, self.error = events, result, error
        self.calls = []
        self.closed = False
    async def orchestrate(self, request):
        raise AssertionError("completed route not authorized")
    async def stream_orchestration(self, request):
        self.calls.append(request)
        try:
            for event in self.events:
                yield {"event": event}
            if self.error:
                raise self.error
            if self.result is not None:
                yield {"orchestration": self.result}
        finally:
            self.closed = True

class TestLiveP01Consumer(SyntheticPlusRouteTestCase):
    def fixture(self, pause=False):
        _, request = _build_request()
        result = _paused_public_result(request) if pause else _public_result(request)
        return request, result, deepcopy(result["events"])
    def call(self, request, events, result, error=None, observer=None):
        fixture = StreamingFixture(events, result, error)
        value = asyncio.run(P01EngineOrchestrationClient(fixture).run_stream(request, on_event=observer))
        return value, fixture
    def test_success_with_canonical_correlation(self):
        request, result, events = self.fixture()
        seen = []
        async def observe(event):
            seen.append(event.kind.value)
        value, fixture = self.call(request, events, result, observer=observe)
        self.assertIsInstance(value, OrchestrationResult)
        self.assertEqual(seen, ["run_started", "context_prepared", "run_completed"])
        self.assertEqual(len(fixture.calls), 1)
        self.assertEqual(fixture.calls[0]["execution_context"]["trace_id"], request.context.trace_id)
    def test_missing_result_never_emits_terminal_success(self):
        request, result, events = self.fixture()
        seen = []
        async def observe(event):
            seen.append(event.kind.value)
        with self.assertRaises(P01AdapterError) as ctx:
            self.call(request, events, None, observer=observe)
        self.assertEqual(ctx.exception.code, "p01_stream_missing_result")
        self.assertEqual(seen, ["run_started", "context_prepared"])
    def test_missing_end_and_mismatched_event_refused(self):
        request, result, events = self.fixture()
        with self.assertRaises(P01AdapterError) as ctx:
            self.call(request, events[:-1], result)
        self.assertEqual(ctx.exception.code, "p01_stream_missing_terminal_event")
        events[1]["event_id"] = "evt_tampered"
        with self.assertRaises(P01AdapterError) as ctx:
            self.call(request, events, result)
        self.assertEqual(ctx.exception.code, "p01_stream_event_result_mismatch")
    def test_foreign_identity_refused(self):
        for key in ("run_id", "trace_id", "app_id"):
            request, result, events = self.fixture()
            events[1][key] = "other"
            with self.subTest(key=key), self.assertRaises(P01AdapterError) as ctx:
                self.call(request, events, result)
            self.assertEqual(ctx.exception.code, "p01_stream_correlation_mismatch")
    def test_replay_and_illegal_kind_refused(self):
        request, result, events = self.fixture()
        events[1]["sequence"] = 1
        with self.assertRaises(P01AdapterError) as ctx:
            self.call(request, events, result)
        self.assertEqual(ctx.exception.code, "p01_stream_sequence_violation")
        request, result, events = self.fixture()
        events[1]["kind"] = "unknown_lifecycle"
        with self.assertRaises(P01AdapterError) as ctx:
            self.call(request, events, result)
        self.assertEqual(ctx.exception.code, "p01_stream_invalid_event")
    def test_approval_pause_retains_engine_issued_authority(self):
        request, result, events = self.fixture(pause=True)
        value, _ = self.call(request, events, result)
        self.assertIsInstance(value, P01PausedWireResult)
        self.assertEqual(value.wire.continuation_ref, result["continuation_ref"])
    def test_ambiguous_engine_failure_is_not_refundable(self):
        request, result, events = self.fixture()
        try:
            self.call(request, events[:1], result, error=PadiemAiEngineClientError("engine_http_error", "upstream", status=502))
        except P01AdapterError as exc:
            self.assertEqual(exc.dispatch_class, P01DispatchClass.UNKNOWN)
        else:
            self.fail("expected fail closed")
    def test_completed_only_client_never_silently_falls_back(self):
        class OldClient:
            async def orchestrate(self, request):
                return {}
        request, _, _ = self.fixture()
        try:
            asyncio.run(P01EngineOrchestrationClient(OldClient()).run_stream(request))
        except P01AdapterError as exc:
            self.assertEqual(exc.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
        else:
            self.fail("expected opt-in denial")

    def test_invalid_event_closes_upstream(self):
        request, result, events = self.fixture()
        events[1]["kind"] = "unknown_lifecycle"
        fixture = StreamingFixture(events, result)
        with self.assertRaises(P01AdapterError):
            asyncio.run(P01EngineOrchestrationClient(fixture).run_stream(request))
        self.assertTrue(fixture.closed)
