"""#5015 — the Engine's bounded error-line stage code reaches the Claw detail.

The Engine ends a failed NDJSON stream with one bounded error line. The
transport decoder preserves the Engine's own closed stage code, and the P01
adapter maps it into the closed failure-detail vocabulary so a missing
verification owner, an unconfigured integration and a request-creation fault
stay distinguishable instead of collapsing into one downstream constant.
"""
from __future__ import annotations

import asyncio

from model_route_fixture import SyntheticPlusRouteTestCase
from test_p01_orchestration_client import _build_request

from padiem_ai_engine_client import PadiemAiEngineClientError

from kagent.p01_adapter import (
    P01AdapterError,
    P01DispatchClass,
    P01_FAILURE_DETAIL_DOWNSTREAM,
    P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED,
    P01_FAILURE_DETAIL_PROVIDER_TIMEOUT,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient


class _FailingStreamFixture:
    def __init__(self, engine_code):
        self._engine_code = engine_code

    async def orchestrate(self, request):
        raise AssertionError("non-stream route not authorized")

    async def stream_orchestration(self, request):
        metadata = {"reason": "engine_stream_error"}
        if self._engine_code is not None:
            metadata["engine_code"] = self._engine_code
        raise PadiemAiEngineClientError(
            "invalid_engine_stream",
            "Engine streaming contract failed",
            metadata=metadata,
        )
        yield {}  # pragma: no cover


class TestEngineStageCodeSurvives(SyntheticPlusRouteTestCase):
    def fail_with(self, engine_code):
        _, request = _build_request()
        port = P01EngineOrchestrationClient(_FailingStreamFixture(engine_code))
        with self.assertRaises(P01AdapterError) as ctx:
            asyncio.run(port.run_stream(request))
        return ctx.exception

    def test_bounded_stage_code_becomes_the_failure_detail(self):
        exc = self.fail_with("pc_query_admission_required")
        self.assertEqual(exc.code, "p01_engine_stream_failed")
        self.assertEqual(exc.dispatch_class, P01DispatchClass.UNKNOWN)
        self.assertEqual(exc.failure_detail, "pc_query_admission_required")

    def test_provider_rate_limit_code_becomes_the_provider_detail(self):
        # #5484: the live lane received this exact class from the Engine but
        # reported engine_downstream_execution_failed, hiding the provider 429.
        exc = self.fail_with("upstream_rate_limited")
        self.assertEqual(exc.code, "p01_engine_stream_failed")
        self.assertEqual(exc.failure_detail, P01_FAILURE_DETAIL_PROVIDER_RATE_LIMITED)

    def test_provider_timeout_code_becomes_the_provider_detail(self):
        exc = self.fail_with("upstream_timeout")
        self.assertEqual(exc.failure_detail, P01_FAILURE_DETAIL_PROVIDER_TIMEOUT)

    def test_non_stage_engine_code_keeps_the_downstream_bucket(self):
        exc = self.fail_with("engine_internal_error")
        self.assertEqual(exc.code, "p01_engine_stream_failed")
        self.assertEqual(exc.failure_detail, P01_FAILURE_DETAIL_DOWNSTREAM)

    def test_absent_engine_code_keeps_the_downstream_bucket(self):
        exc = self.fail_with(None)
        self.assertEqual(exc.code, "p01_engine_stream_failed")
        self.assertEqual(exc.failure_detail, P01_FAILURE_DETAIL_DOWNSTREAM)

    def test_unbounded_metadata_code_keeps_the_downstream_bucket(self):
        exc = self.fail_with("provider said: slow down")
        self.assertEqual(exc.failure_detail, P01_FAILURE_DETAIL_DOWNSTREAM)