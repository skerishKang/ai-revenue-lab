"""#5554 — the Claw preflight reads overlap and the turn records its own stages.

The Claw general composer used to await the owned history read, the canonical
B54 session and the Drive grounding one after another, so a short message paid
their sum before the model was asked anything. Measured on Production, the
whole turn was 18.5 s / 22.0 s for ``안녕`` while the Chat lane answered the same
question in 4.4 s; the per-request duration could not say which step held it.

These tests pin the two load-bearing properties of the change:

1. the three preflight reads are genuinely issued together - a barrier that
   each read waits on can only clear when the other is already running, so the
   previous sequential code fails this test instead of merely being slower;
2. the refusal precedence is unchanged - a failing history read still answers
   409 ``conversation_context_incomplete`` even when the Drive read also fails,
   which a naive ``asyncio.gather`` (first exception wins) would not;
3. each stage is recorded as a name plus a duration and nothing else.

No Production D1, model, Drive, Engine, secret or network activity: the
provider adapter is the in-process stub the existing Claw route tests use.
"""

from __future__ import annotations

import asyncio
import re
import threading

import pytest

import app.claw_general_routes as general_routes_module
from app.drive_general_grounding import DriveGroundingError
from app.history import HistoryContextIncomplete

import test_b54_claw_general_p01_routing as base

GENERAL_ROUTE_PATH = "/api/claw/general"

# Stage names this route owns. The telemetry contract allows a fixed name and a
# duration only, so anything else in the event would be a leak, not a feature.
CLAW_STAGES = {
    "claw.route",
    "claw.history",
    "claw.b54_session",
    "claw.drive",
    "claw.pc_context",
    "claw.catalog",
    "claw.quota",
    "claw.search_judgement",
    "claw.answer",
    "claw.persist",
}


class _Barrier:
    """Cross-thread rendezvous for the two preflight reads.

    The route runs in the TestClient's event loop thread, so the reads are
    awaited there; the events are only used to observe *relative* start order.
    A read that blocks waiting for the other one to start completes only when
    both are in flight at the same time.
    """

    def __init__(self) -> None:
        self.history_started = threading.Event()
        self.drive_started = threading.Event()
        self.history_timeout = False
        self.drive_timeout = False

    async def _wait(self, event: threading.Event) -> bool:
        for _ in range(200):
            if event.is_set():
                return True
            await asyncio.sleep(0.005)
        return False


def _install_barrier(monkeypatch: pytest.MonkeyPatch, barrier: _Barrier) -> None:
    async def _history(request, conversation_id, user_text):
        barrier.history_started.set()
        if not await barrier._wait(barrier.drive_started):
            barrier.history_timeout = True
            raise AssertionError("the Drive read never started")
        return user_text

    async def _drive(request, user_text):
        barrier.drive_started.set()
        if not await barrier._wait(barrier.history_started):
            barrier.drive_timeout = True
            raise AssertionError("the history read never started")
        return None, ()

    monkeypatch.setattr(general_routes_module, "_owner_claw_context", _history)
    monkeypatch.setattr(general_routes_module, "drive_general_grounding", _drive)


def _record_stages(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    events: list[dict] = []

    def _capture(*, stage, outcome, duration_ms, **extra):
        events.append({"stage": stage, "outcome": outcome, "duration_ms": duration_ms, **extra})

    monkeypatch.setattr(general_routes_module, "emit_stage_event", _capture)
    return events


def test_preflight_reads_are_issued_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """The history and Drive reads must be in flight at the same time."""
    barrier = _Barrier()
    _install_barrier(monkeypatch, barrier)
    adapter = base._make_adapter()

    with base._client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 200, resp.text
    assert not barrier.history_timeout, "the history read waited alone: the reads are serial again"
    assert not barrier.drive_timeout, "the Drive read waited alone: the reads are serial again"
    adapter.execute.assert_awaited_once()


def test_history_refusal_still_wins_when_drive_also_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refusal precedence is unchanged: history 409 before any Drive refusal."""

    async def _history(request, conversation_id, user_text):
        raise HistoryContextIncomplete("prior original unavailable")

    async def _drive(request, user_text):
        raise DriveGroundingError("drive_read_failed", "드라이브 검색을 완료하지 못했습니다.", 502)

    monkeypatch.setattr(general_routes_module, "_owner_claw_context", _history)
    monkeypatch.setattr(general_routes_module, "drive_general_grounding", _drive)
    adapter = base._make_adapter()

    with base._client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "conversation_context_incomplete"
    adapter.execute.assert_not_awaited()


def test_drive_refusal_is_unchanged_when_history_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real Drive refusal keeps its own status/code on the overlapped path."""

    async def _history(request, conversation_id, user_text):
        return user_text

    async def _drive(request, user_text):
        raise DriveGroundingError("drive_not_connected", "Google Drive를 먼저 연결해 주세요.", 409)

    monkeypatch.setattr(general_routes_module, "_owner_claw_context", _history)
    monkeypatch.setattr(general_routes_module, "drive_general_grounding", _drive)
    adapter = base._make_adapter()

    with base._client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 409, resp.text
    assert resp.json()["error"]["code"] == "drive_not_connected"
    adapter.execute.assert_not_awaited()


def test_turn_records_bounded_stage_durations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A completed turn emits known stage names with numeric durations only."""
    events = _record_stages(monkeypatch)
    adapter = base._make_adapter()

    with base._client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 200, resp.text
    names = [event["stage"] for event in events]
    assert names, "the Claw turn must record its own stages"
    assert set(names) <= CLAW_STAGES
    for required in ("claw.route", "claw.history", "claw.drive", "claw.quota", "claw.answer", "claw.persist"):
        assert required in names, f"{required} was not recorded: {names}"
    for event in events:
        assert isinstance(event["duration_ms"], float)
        assert event["duration_ms"] >= 0
        assert event["outcome"] in ("ok", "error")
        assert set(event) == {"stage", "outcome", "duration_ms"}
    # No message text, answer text or identifier may travel with the timing.
    payload_text = base._payload()["messages"][0]["content"]
    serialized = repr(events)
    assert payload_text not in serialized
    assert not re.search(r"usr_|req_|orch_run_", serialized)


def test_an_inactive_search_lane_records_no_judgement_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the #4469 lane off, the judgement stage must cost nothing.

    The stage is emitted at the call site either way, so this also proves the
    disabled lane returns immediately instead of paying a provider round trip.
    """
    events = _record_stages(monkeypatch)
    adapter = base._make_adapter()

    with base._client(adapter) as client:
        assert client.app.state.claw_web_search_enabled is False
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 200, resp.text
    judgement = [event for event in events if event["stage"] == "claw.search_judgement"]
    assert len(judgement) == 1, [event["stage"] for event in events]
    assert judgement[0]["duration_ms"] < 50
