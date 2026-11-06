"""Existing B14 transport, deferred-row race and non-blocking delivery."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from types import SimpleNamespace

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
    # #6954: a real finished turn has at least one model call; a turn without
    # one never reaches the transport at all (see the skip test below).
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])
    call_id = collector.model_start(messages=[{"role": "user", "content": "synthetic"}])
    collector.model_finish(call_id)
    collector.finish("completed", "completed")
    return {**IDENTITY, "metrics": collector.snapshot()}


async def test_zero_model_call_turn_skips_http_and_journals_once(caplog):
    """#6954: an MCP pc_* turn has no ledger row to attach to, so the reporter
    must not open a transport request at all — one journal line, nothing sent."""
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    collector = PcWorkMetricsCollector(IDENTITY["session_ref"])  # no model_start
    collector.finish("completed", "completed")
    assert await reporter({**IDENTITY, "metrics": collector.snapshot()}) == "skipped_no_model_call"
    assert calls == []
    assert caplog.text.count("pc_work_metrics_delivery") == 1
    assert "pc_work_metrics_delivery status=skipped_no_model_call" in caplog.text


async def test_repeated_409_backs_off_in_order_and_finishes_inside_window(caplog, monkeypatch):
    """#6954: ledger_pending retries wait 0.25 → 0.5 → 1 → 2 s instead of a fixed
    50 ms, and the delivery window still ends the loop on time."""
    waits = []
    real_sleep = asyncio.sleep
    async def recorded_sleep(delay, *args, **kwargs):
        waits.append(delay)
        await real_sleep(delay)
    monkeypatch.setattr("app.pc_work_metrics_reporter.asyncio.sleep", recorded_sleep)
    attempts = 0
    def handle(request):
        nonlocal attempts
        attempts += 1
        return httpx.Response(409, json={"error": {"code": "ledger_pending"}})
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    started = time.monotonic()
    assert await reporter(payload()) == "unavailable"
    elapsed = time.monotonic() - started
    assert waits[:4] == [0.25, 0.5, 1.0, 2.0]
    assert attempts == 5  # t=0, 0.25, 0.75, 1.75, 3.75 — the next wait crosses the window
    assert elapsed < 5.5  # the 5 s window, not the loop, ends the delivery
    assert "pc_work_metrics_delivery status=unavailable" in caplog.text


async def test_first_try_success_delivers_once_without_retry(caplog):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})
    reporter = PcWorkMetricsReporter(transport=httpx.MockTransport(handle), base_url="https://b14.internal")
    started = time.monotonic()
    assert await reporter(payload()) == "recorded"
    assert len(calls) == 1
    assert time.monotonic() - started < 0.2
    assert caplog.text.count("pc_work_metrics_delivery") == 0


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
