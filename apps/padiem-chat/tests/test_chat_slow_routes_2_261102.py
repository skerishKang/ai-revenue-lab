"""#6460 4-1 second round: the two measured slow Claw reads.

COM2 journal (2026-11-01) showed `/api/claw/local-access/devices` at 8.4 s
median (identity 4.6 s, i.e. several sequential authority round trips) and
`/api/claw/verified-model-choices` re-reading the B14 roster on every request
(2.1 s unattributed). These tests pin the two fixes: independent reads overlap,
and the read-only roster is shared for a short, switchable window.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from types import SimpleNamespace

import pytest
from starlette.requests import Request

import app.claw_device_directory_routes as devices
import app.owner_model_preview_routes as models
from app.claw_device_directory_routes import claw_device_directory
from app.owner_model_preview_routes import claw_verified_model_choices

UID = "usr_" + "a" * 32
WORKSPACE = "tenant_" + "b" * 32
DELAY = 0.12


def _request(module_path: str, *, query: bytes = b"") -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({
        "type": "http", "method": "GET", "path": module_path,
        "headers": [], "query_string": query, "app": app, "state": {},
    })


class _Directory:
    configured = True

    def __init__(self, *, delay: float, items: list | None = None) -> None:
        self.delay = delay
        self.items = items or []
        self.calls = 0

    async def list_devices(self, **_):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return list(self.items)


class _Links:
    def __init__(self, *, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def links_for_owner(self, *, user_id):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return []


class _Drives:
    def __init__(self, *, delay: float) -> None:
        self.delay = delay
        self.calls = 0

    async def load_drives(self, *, device_id):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return None


class _Target:
    def __init__(self, device_id: str) -> None:
        self.ready = True
        self.device_id = device_id
        self.status = "ready"


class _Mesh:
    def __init__(self, device_ids: list[str]) -> None:
        self.device_ids = device_ids

    def command_device_ids(self, *, account_ref):
        return list(self.device_ids)


def _target_tracker(delay: float):
    state = {"in_flight": 0, "peak": 0, "calls": 0}

    async def resolve(request, *, owner_id, workspace_id, connector=None, device_id=None):
        state["calls"] += 1
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        try:
            await asyncio.sleep(delay)
        finally:
            state["in_flight"] -= 1
        return _Target(device_id or "pc_primary")

    return resolve, state


def _wire_devices(monkeypatch, *, extra_devices: list[str] | None = None):
    resolve, state = _target_tracker(DELAY)
    directory = _Directory(delay=DELAY)
    links = _Links(delay=DELAY)
    drives = _Drives(delay=DELAY)
    request = _request("/api/claw/local-access/devices")

    async def _workspace(_request, _uid):
        return WORKSPACE

    async def _connector(*_a, **_k):
        return SimpleNamespace(
            ready=True, account_ref="account-1", workspace_ref="connector-ws-1",
            session_id="sess-1", status="ready",
        )

    monkeypatch.setattr(devices, "auth_ready", lambda _r: True)
    monkeypatch.setattr(devices, "current_user_id", lambda _r: UID)
    monkeypatch.setattr(devices, "_resolve_memory_workspace", _workspace)
    monkeypatch.setattr(devices, "resolve_pc_connector_scope", _connector)
    monkeypatch.setattr(devices, "resolve_pc_mesh_target", resolve)
    request.app.state.claw_device_directory_source = directory
    request.app.state.pc_device_pairing_store = links
    request.app.state.mesh_device_drive_store = drives
    request.app.state.oracle_mesh_return_source = _Mesh(extra_devices or [])
    request.app.state.mesh_device_presence_store = None
    request.app.state.claw_pc_device_selection_store = None
    return request, state, directory, links, drives


def test_device_reads_overlap_instead_of_waiting_one_by_one(monkeypatch):
    request, state, directory, links, drives = _wire_devices(
        monkeypatch, extra_devices=["pc_a", "pc_b", "pc_c"],
    )
    started = time.perf_counter()
    response = asyncio.run(claw_device_directory(request))
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    body = response.body
    assert b'"available":true' in body and b'"deviceId":"pc_a"' in body
    # Serial would be directory + links + 1 primary + 3 enumerated + 3 drive
    # reads = 8 x 120 ms. Every group now overlaps, so the whole read costs
    # three waves.
    assert elapsed < 0.55, f"device reads still serialised ({elapsed:.3f}s)"
    assert state["peak"] >= 3, "the enumerated grants must be resolved together"
    assert directory.calls == 1 and links.calls == 1
    # One primary grant plus the three enumerated PCs, all read together.
    assert drives.calls == 4


def test_a_failing_drive_read_never_hides_the_device(monkeypatch):
    request, _state, _directory, _links, _drives = _wire_devices(monkeypatch)

    class _Broken:
        async def load_drives(self, *, device_id):
            raise RuntimeError("inventory unavailable")

    request.app.state.mesh_device_drive_store = _Broken()
    response = asyncio.run(claw_device_directory(request))
    assert response.status_code == 200
    assert b'"drivesStatus":"unavailable"' in response.body


class _Roster:
    def __init__(self, *, delay: float, models: list[dict]) -> None:
        self.delay = delay
        self.models = models
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return [dict(row) for row in self.models]


def _wire_models(monkeypatch, roster: _Roster):
    request = _request("/api/claw/verified-model-choices")

    async def _denial(*_a, **_k):
        return None

    async def _view(*_a, **_k):
        return SimpleNamespace(
            ok=True, model_id="model-a", fallback_model_id=None, source="central",
        ), 7

    # The route imports these inside the call, so the source module is patched.
    import app.auth_routes as auth_routes
    monkeypatch.setattr(auth_routes, "auth_ready", lambda _r: True)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda _r: UID)
    import app.member_grade_access as grade
    monkeypatch.setattr(grade, "selected_grade_denial", _denial)
    monkeypatch.setattr(grade, "selected_admin_denial", _denial)
    import app.central_model_route_runtime as runtime
    monkeypatch.setattr(runtime, "resolve_claw_tier_model_view", _view)
    request.app.state.b14_model_choice_resolver = roster
    return request


def test_roster_is_read_once_inside_the_window(monkeypatch):
    monkeypatch.delenv(models.ROSTER_CACHE_TTL_ENV, raising=False)
    models.clear_roster_cache()
    roster = _Roster(delay=0.08, models=[
        {"model_id": "model-a", "name": "파디엠 프리"},
        {"model_id": "model-b", "name": "다른 모델"},
    ])
    request = _wire_models(monkeypatch, roster)

    first = time.perf_counter()
    response = asyncio.run(claw_verified_model_choices(request))
    first_elapsed = time.perf_counter() - first
    assert response.status_code == 200
    # The central route still decides membership on every request.
    assert b'"model_id":"model-a"' in response.body
    assert b"model-b" not in response.body

    second = time.perf_counter()
    again = asyncio.run(claw_verified_model_choices(request))
    second_elapsed = time.perf_counter() - second

    assert again.status_code == 200
    assert roster.calls == 1, "a second screen read must reuse the short window"
    assert second_elapsed < first_elapsed / 2
    assert second_elapsed < 0.05


def test_window_can_be_switched_off(monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0")
    models.clear_roster_cache()
    roster = _Roster(delay=0.02, models=[{"model_id": "model-a", "name": "A"}])
    request = _wire_models(monkeypatch, roster)
    for _ in range(2):
        assert asyncio.run(claw_verified_model_choices(request)).status_code == 200
    assert roster.calls == 2


def test_another_resolver_never_reads_a_shared_entry(monkeypatch):
    monkeypatch.delenv(models.ROSTER_CACHE_TTL_ENV, raising=False)
    models.clear_roster_cache()
    first = _Roster(delay=0.01, models=[{"model_id": "model-a", "name": "A"}])
    second = _Roster(delay=0.01, models=[{"model_id": "model-a", "name": "B"}])
    for _ in range(2):
        assert asyncio.run(
            claw_verified_model_choices(_wire_models(monkeypatch, first))
        ).status_code == 200
        assert asyncio.run(
            claw_verified_model_choices(_wire_models(monkeypatch, second))
        ).status_code == 200
    assert (first.calls, second.calls) == (1, 1)


def test_roster_window_is_bounded(monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "9999")
    assert models.roster_cache_ttl() == models._ROSTER_CACHE_TTL_DEFAULT
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "-1")
    assert models.roster_cache_ttl() == models._ROSTER_CACHE_TTL_DEFAULT
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "nonsense")
    assert models.roster_cache_ttl() == models._ROSTER_CACHE_TTL_DEFAULT
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "5")
    assert models.roster_cache_ttl() == 5.0
