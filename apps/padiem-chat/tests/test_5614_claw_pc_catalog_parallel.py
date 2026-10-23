"""#5614 — the Claw PC work context and the model-roster read run together.

#5554 measured both reads on Production: ``claw.pc_context`` 0.5-2.6 s and
``claw.catalog`` 0.1-1.5 s. They read unrelated authorities (the Broker/Mesh
directory and the B14 selectable-model roster) for the same signed request, and
the roster read used to start only after the PC block finished, so every Claw
turn paid their sum.

This module pins the properties the change must not trade away:

1. the two reads are genuinely in flight at the same time - a barrier each one
   waits on can only clear when the other has already started, so the previous
   sequential code fails this test instead of merely being slower;
2. the roster result is still EVALUATED after the PC block, so a PC refusal
   still wins and the roster refusal keeps its own status (422/503);
3. the fail-closed branches are unchanged: a resolver without the roster
   method and a failing roster read both keep the 503;
4. each stage still reports its OWN read time, so the overlap cannot be
   mistaken for a faster read.

No Production D1, model, Drive, Engine, secret or network activity: the
provider adapter and the roster resolver are in-process stubs.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

import app.pc_work_context as pc_work_context_module
from padiem_control_plane import product_tier_routes

import test_b54_claw_general_p01_routing as base

GENERAL_ROUTE_PATH = "/api/claw/general"


def _route_model_ids() -> list[str]:
    """Every tier's currently declared execution model id."""
    ids: list[str] = []
    for label in product_tier_routes.ProductTierLabel:
        route = product_tier_routes.active_route_for(label)
        for value in (
            getattr(route, "model_id", None),
            getattr(route, "fallback_model_id", None),
        ):
            if isinstance(value, str) and value and value not in ids:
                ids.append(value)
    return ids


class _Rendezvous:
    """Cross-task rendezvous for the two reads, with a bounded wait."""

    def __init__(self) -> None:
        self.pc_started = threading.Event()
        self.roster_started = threading.Event()
        self.pc_timed_out = False
        self.roster_timed_out = False

    async def wait(self, event: threading.Event) -> bool:
        for _ in range(200):
            if event.is_set():
                return True
            await asyncio.sleep(0.005)
        return False


def _pc_context():
    return pc_work_context_module.PcWorkContext(
        broker_status=pc_work_context_module._UNVERIFIED_OWNER
    )


class _Roster:
    """Minimal selectable-model resolver; the route reads it from app.state."""

    def __init__(self, *, model_ids=None, error: Exception | None = None,
                 delay_s: float = 0.0, on_call=None) -> None:
        self._model_ids = _route_model_ids() if model_ids is None else list(model_ids)
        self._error = error
        self._delay_s = delay_s
        self._on_call = on_call
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        if self._on_call is not None:
            await self._on_call()
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._error is not None:
            raise self._error
        return [{"model_id": model_id} for model_id in self._model_ids]


class _NoRosterMethod:
    """A composed resolver that cannot list models at all."""


def _install_pc_read(monkeypatch: pytest.MonkeyPatch, read) -> None:
    # The route imports the helper inside the turn, so the module attribute is
    # the real seam.
    monkeypatch.setattr(pc_work_context_module, "resolve_pc_work_context", read)


def test_pc_read_and_roster_read_are_issued_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both reads must be in flight at the same time."""
    rendezvous = _Rendezvous()

    async def _pc_read(request, **kwargs):
        rendezvous.pc_started.set()
        if not await rendezvous.wait(rendezvous.roster_started):
            rendezvous.pc_timed_out = True
            raise AssertionError("the roster read never started")
        return _pc_context()

    async def _roster_wait():
        rendezvous.roster_started.set()
        if not await rendezvous.wait(rendezvous.pc_started):
            rendezvous.roster_timed_out = True
            raise AssertionError("the PC read never started")

    _install_pc_read(monkeypatch, _pc_read)
    adapter = base._make_adapter()
    with base._client(adapter) as client:
        client.app.state.b14_model_choice_resolver = _Roster(on_call=_roster_wait)
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 200, resp.text
    assert not rendezvous.pc_timed_out, "the PC read waited alone: the reads are serial again"
    assert not rendezvous.roster_timed_out, (
        "the roster read waited alone: the reads are serial again"
    )
    adapter.execute.assert_awaited_once()


def test_roster_refusal_is_still_evaluated_after_the_pc_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown model keeps 422, and only after the PC read has run."""
    pc_calls: list[object] = []

    async def _pc_read(request, **kwargs):
        pc_calls.append(request)
        return _pc_context()

    _install_pc_read(monkeypatch, _pc_read)
    adapter = base._make_adapter()
    with base._client(adapter) as client:
        client.app.state.b14_model_choice_resolver = _Roster(model_ids=["other/model"])
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "model_not_available"
    assert len(pc_calls) == 1, "the PC work context must still be resolved first"
    adapter.execute.assert_not_awaited()


def test_missing_roster_method_keeps_the_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A composed resolver without the roster method still fails closed."""

    async def _pc_read(request, **kwargs):
        return _pc_context()

    _install_pc_read(monkeypatch, _pc_read)
    adapter = base._make_adapter()
    with base._client(adapter) as client:
        client.app.state.b14_model_choice_resolver = _NoRosterMethod()
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "model_catalog_unavailable"
    adapter.execute.assert_not_awaited()


def test_failing_roster_read_keeps_the_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A roster read that raises must not reach the Engine."""

    async def _pc_read(request, **kwargs):
        return _pc_context()

    _install_pc_read(monkeypatch, _pc_read)
    adapter = base._make_adapter()
    with base._client(adapter) as client:
        client.app.state.b14_model_choice_resolver = _Roster(
            error=RuntimeError("roster unavailable")
        )
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "model_catalog_unavailable"
    adapter.execute.assert_not_awaited()


def test_each_stage_reports_only_its_own_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both stages are recorded, and neither includes the other's wait."""
    events: list[dict] = []

    def _capture(*, stage, outcome, duration_ms, **extra):
        events.append({"stage": stage, "duration_ms": duration_ms, **extra})

    monkeypatch.setattr(
        "app.claw_general_routes.emit_stage_event", _capture
    )

    read_delay = 0.12

    async def _pc_read(request, **kwargs):
        await asyncio.sleep(read_delay)
        return _pc_context()

    _install_pc_read(monkeypatch, _pc_read)
    adapter = base._make_adapter()
    with base._client(adapter) as client:
        client.app.state.b14_model_choice_resolver = _Roster(delay_s=read_delay)
        resp = client.post(GENERAL_ROUTE_PATH, json=base._payload())

    assert resp.status_code == 200, resp.text
    by_stage = {event["stage"]: event["duration_ms"] for event in events}
    assert "claw.pc_context" in by_stage
    assert "claw.catalog" in by_stage
    # Each stage measures its own read, so an overlapped read still reports one
    # delay instead of the sum.
    assert by_stage["claw.pc_context"] >= read_delay * 1000
    assert by_stage["claw.catalog"] >= read_delay * 1000
    assert by_stage["claw.pc_context"] < read_delay * 1000 * 2
    assert by_stage["claw.catalog"] < read_delay * 1000 * 2
