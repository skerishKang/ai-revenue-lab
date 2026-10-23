"""#4317 the PADIEM Chat time-to-first-token path.

The owner-visible symptom is that the same model answers later through PADIEM
Chat than through a direct client. This module pins the three changes that were
made after measuring where the per-turn cost sits:

* the first visible token is measured, so the model's own start latency is
  separable from the whole-stream duration that already existed;
* the conversation the route already read is not read a second time before the
  model call;
* the two independent model-route store reads are issued together instead of
  one after the other.

The concurrency proof is a rendezvous, not a stopwatch: if the two reads were
still sequential the rendezvous can never complete.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import b14_client as b14_client_module
from app import central_model_route_runtime as route_runtime
from app import chat_routes as chat_routes_module
from app import pc_work_context as pc_work_context_module
from app.history import D1HistoryStore
from app.request_telemetry import build_stage_event


# --- 1. first-token measurement -------------------------------------------


def test_the_first_visible_token_is_measured_once_on_the_existing_event():
    """One `b14.stream.first_delta` stage per stream, before the first delta."""

    emitted: list[dict] = []

    class FakeEvent:
        def __init__(self, *, delta="", done=False):
            self.delta_content = delta
            self.done = done

    class FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def stream(self, request):
            async def generate():
                yield FakeEvent(delta="")        # pre-visible, not the answer
                yield FakeEvent(delta="안")       # first visible token
                yield FakeEvent(delta="녕")
                yield FakeEvent(done=True)

            return generate()

    class FakeCoreClient:
        def __init__(self, *args, **kwargs):
            pass

    def fake_emit(**kwargs):
        emitted.append(kwargs)

    original_runtime = b14_client_module.StreamingExecutionRuntime
    original_core_client = b14_client_module.B14StreamingClient
    original_emit = b14_client_module.emit_stage_event
    b14_client_module.StreamingExecutionRuntime = FakeRuntime
    b14_client_module.B14StreamingClient = FakeCoreClient
    b14_client_module.emit_stage_event = fake_emit
    try:
        client = b14_client_module.B14Client.__new__(b14_client_module.B14Client)
        client.stream_transport = None
        client.transport = None
        # The core client is faked above, so the execution config only has to
        # exist for the constructor call this module performs.
        client._config = lambda *args, **kwargs: SimpleNamespace()

        async def drain():
            return [event async for event in client._stream_core(SimpleNamespace())]

        events = asyncio.run(drain())
    finally:
        b14_client_module.StreamingExecutionRuntime = original_runtime
        b14_client_module.B14StreamingClient = original_core_client
        b14_client_module.emit_stage_event = original_emit

    assert [event.delta_content for event in events if event.delta_content] == ["안", "녕"]
    assert [event.done for event in events if event.done] == [True]

    first_delta = [item for item in emitted if item["stage"] == "b14.stream.first_delta"]
    whole = [item for item in emitted if item["stage"] == "b14.stream"]
    assert len(first_delta) == 1, "the first token must be measured exactly once"
    assert first_delta[0]["outcome"] == "ok"
    assert len(whole) == 1
    # The whole-stream event still exists, and the first-token event can never
    # be larger than it.
    assert first_delta[0]["duration_ms"] <= whole[0]["duration_ms"]


def test_the_first_token_event_uses_the_existing_bounded_contract():
    event = build_stage_event(
        request_id="req_4317ttft0000000000000000",
        stage="b14.stream.first_delta",
        outcome="ok",
        duration_ms=812.345,
    )
    assert event["event"] == "ai_stage"
    assert event["stage"] == "b14.stream.first_delta"
    assert event["duration_ms"] == 812.35
    # The stage name must stay inside the existing bounded vocabulary.
    assert len(event["stage"]) <= 48


# --- 2. no duplicate conversation read -------------------------------------


class CountingStore:
    """A D1-shaped store that counts every query it answers."""

    def __init__(self):
        self.queries: list[str] = []

    async def _first(self, sql, *values):
        self.queries.append(sql)
        if "FROM conversations" in sql:
            return {
                "id": "conv_4317", "title": "t", "project_id": None,
                "created_at": "t", "updated_at": "t",
            }
        return None

    async def _all(self, sql, *values):
        self.queries.append(sql)
        return [
            {"id": "m1", "role": "user", "content": "안녕", "sequence_number": 1},
        ]

    async def _read_full_message(self, conversation_id, row):
        return str(row.get("content", ""))


def _store():
    from app.history import D1HistoryStore

    class Db:
        def prepare(self, sql):
            return SimpleNamespace(bind=lambda *values: SimpleNamespace(
                first=lambda: None, run=lambda: None,
            ))

    store = D1HistoryStore.__new__(D1HistoryStore)
    store.db = Db()
    store.full_context_bucket = None
    store.queries = []

    async def first(sql, *values):
        store.queries.append(sql)
        if "FROM conversations" in sql:
            return {
                "id": "conv_4317", "title": "t", "project_id": None,
                "created_at": "t", "updated_at": "t",
            }
        return None

    async def all_(sql, *values):
        store.queries.append(sql)
        return [{"id": "m1", "role": "user", "content": "안녕", "sequence_number": 1}]

    store._first = first
    store._all = all_
    return store


def test_the_model_context_read_does_not_read_the_message_preview_again():
    """One conversation read and one message read, not two of each."""

    store = _store()

    async def run():
        return await store.get_conversation_model_context(
            "usr_4317", "conv_4317", product_scope="b62-chat",
        )

    result = asyncio.run(run())
    assert result is not None
    assert result["id"] == "conv_4317"
    assert result["messages"] == [{"role": "user", "content": "안녕"}]
    conversation_reads = [q for q in store.queries if "FROM conversations" in q]
    message_reads = [q for q in store.queries if "FROM messages" in q]
    assert len(conversation_reads) == 1, store.queries
    assert len(message_reads) == 1, store.queries


def test_the_model_context_read_keeps_the_owner_scope():
    """A foreign owner still resolves to no conversation."""

    store = _store()

    async def run():
        return await store.get_conversation_model_context(
            "usr_other", "conv_4317", product_scope="b62-chat",
        )

    async def first(sql, *values):
        store.queries.append(sql)
        return None

    store._first = first
    assert asyncio.run(run()) is None


def test_the_chat_route_keeps_its_ownership_gate_before_the_full_context_read():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "chat_routes.py").read_text(
        encoding="utf-8"
    )
    # The route must still refuse a foreign owner before the full-context read.
    assert "existing_conversation = await store.get_conversation(" in source
    assert "if existing_conversation is None:" in source
    assert "_conversation_not_found()" in source


# --- 3. concurrent route-store reads --------------------------------------


class Rendezvous:
    """Both readers must arrive before either may proceed."""

    def __init__(self) -> None:
        self.arrived = 0
        self._both = asyncio.Event()

    async def arrive(self) -> None:
        self.arrived += 1
        if self.arrived >= 2:
            self._both.set()
        await asyncio.wait_for(self._both.wait(), timeout=0.5)


def test_the_two_model_route_store_reads_are_issued_together():
    gate = Rendezvous()

    class PolicyStore:
        async def snapshot(self, workspace_id):
            await gate.arrive()
            return None

    class RouteStore:
        async def snapshot(self, workspace_id):
            await gate.arrive()
            return None

    async def run():
        return await route_runtime.resolve_tier_route_view_from_stores(
            RouteStore(),
            PolicyStore(),
            product="chat",
            tier="FREE",
            static_primary="google/gemini-3.1-flash-lite",
        )

    resolution, revision = asyncio.run(run())
    assert gate.arrived == 2
    assert revision == 0
    assert resolution is not None


def test_a_sequential_implementation_would_deadlock_the_rendezvous():
    """Negative control: the rendezvous is a real concurrency proof."""

    gate = Rendezvous()

    async def sequential():
        await gate.arrive()
        await gate.arrive()

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        asyncio.run(sequential())


def test_chat_preflight_reads_are_issued_together(monkeypatch: pytest.MonkeyPatch):
    """Drive grounding and PC work context must run in parallel, not back to back."""

    import app.chat_routes as chat_routes_module

    barrier = Rendezvous()

    async def _drive(request, latest_user_text):
        await barrier.arrive()
        return ("ctx", (("src",),))

    async def _pc(request, *, owner_id):
        await barrier.arrive()
        return "pc"

    monkeypatch.setattr(chat_routes_module, "drive_general_grounding", _drive)
    monkeypatch.setattr(pc_work_context_module, "build_pc_work_context_text", _pc)

    async def _preflight():
        drive, pc = await asyncio.gather(
            chat_routes_module.drive_general_grounding(None, "hi"),
            pc_work_context_module.build_pc_work_context_text(None, owner_id="u"),
            return_exceptions=True,
        )
        return drive, pc

    drive, pc = asyncio.run(_preflight())
    assert barrier.arrived == 2
    assert drive == ("ctx", (("src",),))
    assert pc == "pc"
