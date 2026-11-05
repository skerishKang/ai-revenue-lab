"""Existing B14 transport, deferred-row race and non-blocking delivery."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import time

import httpx
import pytest

from app.byok_passthrough import credential_scope
from app.cloudflare_transport import (
    CloudflareB14ServiceBindingTransport, build_b14_transport,
)
from app.pc_work_metrics import (
    PcWorkMetricsCollector, set_pc_work_metrics, reset_pc_work_metrics,
)
from app.pc_work_metrics_reporter import PcWorkMetricsReporter, PC_WORK_METRICS_PATH
from padiem_ai_core.b14_upstream import B14Upstream

PROOF = "synthetic-b14-proof-only-" + "x" * 32
IDENTITY = {"product": "claw", "subject_ref": "usr_synthetic",
            "session_ref": "pcturn_" + "a" * 64}


def payload():
    # A reported turn is one whose execution reached a model call: the ledger
    # row the metrics attach to exists only then (#6954).
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.ledger_identity = IDENTITY
    call = collector.model_start(messages=[{"role": "user", "content": "synthetic"}])
    collector.model_finish(call)
    collector.finish("completed", "completed")
    return {**IDENTITY, "metrics": collector.snapshot()}


async def test_pending_actual_ledger_row_is_retried_with_identical_summary():
    sent = []
    def handle(request):
        sent.append(request.content)
        if len(sent) == 1:
            return httpx.Response(409, json={"error": {"code": "ledger_pending"}})
        return httpx.Response(200, json={"ok": True})
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    assert await reporter(payload()) == "recorded"
    assert len(sent) == 2 and sent[0] == sent[1]


@pytest.mark.parametrize("status,result", [(409, {"error": {"code": "conflict"}}),
                                           (403, {"error": {"code": "proof_required"}}),
                                           (200, []), (503, {"error": {"message": "PRIVATE_BODY"}})])
async def test_non_pending_failures_do_not_retry_or_leak(status, result, caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=result)
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    assert await reporter(payload()) in {"conflict", "unavailable"}
    assert len(calls) == 1
    assert "PRIVATE_BODY" not in caplog.text
    assert IDENTITY["subject_ref"] not in caplog.text


async def test_slow_telemetry_does_not_hold_completed_work_indefinitely():
    cancelled = []
    async def handle(request):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle),
        base_url="https://b14.internal", delivery_seconds=0.01)
    assert await reporter(payload()) == "unavailable"
    assert cancelled == [True]


async def test_transport_exception_never_logs_raw_exception_or_payload(caplog):
    def handle(request):
        raise RuntimeError("PRIVATE_BODY " + PROOF)
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    assert await reporter(payload()) == "unavailable"
    assert "PRIVATE_BODY" not in caplog.text and PROOF not in caplog.text


def verify_proof(headers, body):
    headers = {key.lower(): value for key, value in headers.items()}
    stamp = headers["x-padiem-b14-time"]
    expected = hmac.new(PROOF.encode(), stamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert headers["x-padiem-b14-proof"] == expected
    for key, suffix in (("product", "product"), ("subject_ref", "subject-ref"), ("session_ref", "session-ref")):
        assert headers["x-padiem-" + suffix] == IDENTITY[key]


async def test_binding_signs_metrics_and_omits_byok_reference():
    from app.local_runtime import LocalByteStream
    calls = []
    class Binding:
        async def fetch(self, request):
            calls.append(request)
            return SimpleNamespace(status=200, headers={"content-type": "application/json"},
                                   body=LocalByteStream(b'{"ok":true}'))
    def factory(url, **kwargs):
        return SimpleNamespace(js_object=SimpleNamespace(url=url, **kwargs))
    transport = CloudflareB14ServiceBindingTransport(
        binding=Binding(), request_factory=factory, proof_secret=PROOF)
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.ledger_identity = IDENTITY
    token = set_pc_work_metrics(collector)
    try:
        with credential_scope("PRIVATE_BYOK_REFERENCE"):
            reporter = PcWorkMetricsReporter(transport=transport, base_url="https://b14.internal")
            assert await reporter(payload()) == "recorded"
            body = calls[0].body.encode()
            verify_proof(calls[0].headers, body)
            assert json.loads(body) == payload()
            assert "PRIVATE_BYOK_REFERENCE" not in calls[0].body
    finally:
        reset_pc_work_metrics(token)


async def test_https_model_and_report_share_scoped_correlation_and_existing_proof():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    transport = build_b14_transport(binding=None, request_factory=lambda: None,
        proof_secret=PROOF, upstream=B14Upstream(mode="https", origin="https://b14.example.test"),
        https_client_factory=lambda: client)
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.ledger_identity = IDENTITY
    token = set_pc_work_metrics(collector)
    try:
        response = await transport.handle_async_request(httpx.Request("POST",
            "https://b14.example.test/api/pilot/v1/chat/completions", json={"model": "synthetic"}))
        await response.aclose()
        assert await PcWorkMetricsReporter(transport=transport, base_url="https://b14.example.test")(payload()) == "recorded"
        for request in seen:
            verify_proof(dict(request.headers), request.content)
        assert seen[-1].url.path == PC_WORK_METRICS_PATH
    finally:
        reset_pc_work_metrics(token)
    response = await transport.handle_async_request(httpx.Request("POST",
        "https://b14.example.test/api/pilot/v1/chat/completions", json={"model": "synthetic"}))
    await response.aclose()
    assert "x-padiem-session-ref" not in seen[-1].headers
    await client.aclose()


async def test_turn_without_a_model_call_is_skipped_without_a_post(caplog):
    posts = []
    def handle(request):
        posts.append(request)
        return httpx.Response(200, json={"ok": True})
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.finish("completed", "completed")
    empty = {**IDENTITY, "metrics": collector.snapshot()}
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    assert await reporter(empty) == "skipped"
    assert posts == []
    assert "pc_work_metrics_delivery status=skipped" in caplog.text


async def test_the_transport_carries_the_ledger_identity_headers_to_the_post():
    """#6954: identity arrives as correlation headers, never duplicated.

    The loopback binding forwards the reporter's request and the B14HttpsTransport
    merges the context collector's ledger identity with setdefault semantics —
    the ledger row match needs each x-padiem-* header exactly once.
    """

    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})
    from app.cloudflare_transport import build_b14_transport
    from padiem_ai_core.b14_upstream import B14Upstream
    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    transport = build_b14_transport(
        binding=None, request_factory=lambda: None, proof_secret=PROOF,
        upstream=B14Upstream(mode="https", origin="https://b14.example.test"),
        https_client_factory=lambda: client,
    )
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    collector.ledger_identity = IDENTITY
    call = collector.model_start(messages=[{"role": "user", "content": "synthetic"}])
    collector.model_finish(call)
    collector.finish("completed", "completed")
    token = set_pc_work_metrics(collector)
    try:
        reporter = PcWorkMetricsReporter(transport=transport, base_url="https://b14.example.test")
        assert await reporter({**IDENTITY, "metrics": collector.snapshot()}) == "recorded"
    finally:
        reset_pc_work_metrics(token)

    pairs = seen[0].headers.multi_items()
    products = [v for k, v in pairs if k.lower() == "x-padiem-product"]
    assert products == [IDENTITY["product"]], pairs
    by_name = {k.lower(): v for k, v in pairs}
    assert by_name["x-padiem-subject-ref"] == IDENTITY["subject_ref"]
    assert by_name["x-padiem-session-ref"] == IDENTITY["session_ref"]


async def test_ledger_pending_retries_climb_a_backoff_ladder(monkeypatch):
    delays = []
    real_sleep = asyncio.sleep

    async def not_a_fixed_spin(seconds):
        delays.append(seconds)
        # Yield to the loop once: the 5 s budget timer must stay able to fire.
        await real_sleep(0)

    monkeypatch.setattr("app.pc_work_metrics_reporter.asyncio.sleep", not_a_fixed_spin)
    answers = iter([
        httpx.Response(409, json={"error": {"code": "ledger_pending"}}),
        httpx.Response(409, json={"error": {"code": "ledger_pending"}}),
        httpx.Response(200, json={"ok": True}),
    ])
    def handle(request):
        return next(answers)
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    assert await reporter(payload()) == "recorded"
    # The ladder climbs (0.25 → 0.5 → …); the fixed 50 ms spin is gone.
    assert delays[:2] == [0.25, 0.5]
    assert all(d > 0.05 for d in delays)


async def test_retry_budget_never_exceeds_the_delivery_window(monkeypatch, caplog):
    delays = []
    real_sleep = asyncio.sleep

    async def record_sleep(seconds):
        delays.append(seconds)
        # Yield to the loop once: the 5 s budget timer must stay able to fire.
        await real_sleep(0)

    monkeypatch.setattr("app.pc_work_metrics_reporter.asyncio.sleep", record_sleep)
    def handle(request):
        return httpx.Response(409, json={"error": {"code": "ledger_pending"}})
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    started = time.perf_counter()
    assert await reporter(payload()) == "unavailable"
    elapsed = time.perf_counter() - started
    # The wall-clock budget is the reporter's own 5 s window; with instant
    # sleeps many ladder steps fit inside it, but each stays at the 1 s cap
    # and the ladder still starts at 0.25.
    assert elapsed <= reporter._delivery_seconds + 2.0, elapsed
    assert all(d <= 1.0 + 0.01 for d in delays), delays[:5]
    assert delays[:1] == [0.25]
    assert "pc_work_metrics_delivery status=unavailable" in caplog.text
