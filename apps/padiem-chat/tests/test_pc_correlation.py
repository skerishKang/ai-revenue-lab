import asyncio
import hashlib
import logging
import pytest

import test_5881_queue_store_proxy as q
import test_5573_pc_http_boundary as h
from app.pc_correlation import run_hash, dispatch_id

RUN = "chat_pcq_" + "a" * 32
DISPATCH = "dsp_" + "b" * 32
MARKER = "DO_NOT_LOG_ARGUMENT_OR_SECRET"


def test_hash_is_stable_and_rejects_untrusted_values():
    assert run_hash(RUN) == hashlib.sha256(RUN.encode("ascii")).hexdigest()[:16]
    for value in (None, "usr_secret", RUN + "x", 123):
        assert run_hash(value) is None
    assert dispatch_id(DISPATCH) == DISPATCH
    assert dispatch_id(MARKER) is None


def test_queue_header_and_safe_success_log(caplog):
    caplog.set_level(logging.INFO)
    client, recorder = q._client(lambda sent: q._Response(200, {"ok": True, "result": {"dispatch_id": DISPATCH}}))
    result = asyncio.run(client.call("create_oracle_mesh_dispatch", run_id=RUN, user_id=MARKER))
    assert result["dispatch_id"] == DISPATCH
    assert recorder.sent[0]["headers"]["X-Padiem-PC-Run-Hash"] == run_hash(RUN)
    assert "run_hash=" + run_hash(RUN) in caplog.text
    assert "dispatch_id=" + DISPATCH in caplog.text
    assert MARKER not in caplog.text and RUN not in caplog.text
    assert q.SECRET not in caplog.text


def test_queue_failure_keeps_hash_without_secret(caplog):
    caplog.set_level(logging.WARNING)
    client, recorder = q._client(lambda sent: q._Response(502, {"ok": False}))
    with pytest.raises(q.proxy.QueueUnavailable):
        asyncio.run(client.call("create_oracle_mesh_dispatch", run_id=RUN, user_id=MARKER))
    assert recorder.sent[0]["headers"]["X-Padiem-PC-Run-Hash"] == run_hash(RUN)
    assert "run_hash=" + run_hash(RUN) in caplog.text
    assert "status=502" in caplog.text and "dispatch_id=none" in caplog.text
    assert MARKER not in caplog.text and q.SECRET not in caplog.text


@pytest.mark.asyncio
async def test_chat_stages_share_safe_hash(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    app, bridge, _ = h._wire(monkeypatch)
    async with h._client(app) as client:
        response = await client.post("/api/orchestration", headers={"Origin": h.ORIGIN},
           json={"messages": [{"role": "user", "content": MARKER}], "skill":"auto", "pc_run_id": RUN})
        assert response.status_code == 200
    for stage in ("request_received", "contract_accepted", "stream_started", "stream_ended"):
        assert "stage=" + stage + " run_hash=" + run_hash(RUN) in caplog.text
    assert "reason=completed" in caplog.text
    assert MARKER not in caplog.text and RUN not in caplog.text

@pytest.mark.asyncio
async def test_cancelled_stream_reports_reason_and_closes(caplog):
    from app.claw_live_events import chat_pc_orchestration_sse
    caplog.set_level(logging.INFO)
    started = asyncio.Event()
    closed = asyncio.Event()
    async def source():
        try:
            started.set()
            await asyncio.Event().wait()
            yield {}
        finally:
            closed.set()
    async def complete(_result):
        return {}
    response = chat_pc_orchestration_sse(source(), pc_run_id=RUN, on_completed=complete)
    task = asyncio.create_task(response.body_iterator.__anext__())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed.is_set()
    assert "stage=stream_ended run_hash=" + run_hash(RUN) + " reason=cancelled" in caplog.text

@pytest.mark.asyncio
async def test_missing_browser_run_id_is_assigned_once(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    app, bridge, _ = h._wire(monkeypatch)
    async with h._client(app) as client:
        response = await client.post("/api/orchestration", headers={"Origin": h.ORIGIN},
           json={"messages": [{"role": "user", "content": "synthetic"}], "skill": "auto"})
        assert response.status_code == 200
    token = run_hash(bridge.requests[0]["session_id"])
    assert token
    for stage in ("request_received", "contract_accepted", "stream_started", "stream_ended"):
        assert "stage=" + stage + " run_hash=" + token in caplog.text
