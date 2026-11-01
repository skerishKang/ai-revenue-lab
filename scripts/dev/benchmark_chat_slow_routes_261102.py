#!/usr/bin/env python3
"""#6460 4-1 second round: local timing for the two slow Claw reads.

Synthetic dependencies only (no COM2, no B14). Run it on a checkout to see the
route's own cost, then on another to compare. It prints wall clock, not a
production promise.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "padiem-chat"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "padiem-control-plane"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "padiem-ai-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "korean-ai-code-agent" / "src"))

from starlette.requests import Request  # noqa: E402

import app.claw_device_directory_routes as devices  # noqa: E402
import app.owner_model_preview_routes as models  # noqa: E402

UID = "usr_" + "a" * 32
WS = "tenant_" + "b" * 32
DELAY = 0.12


def _request(path: str) -> Request:
    app = SimpleNamespace(state=SimpleNamespace())
    return Request({"type": "http", "method": "GET", "path": path,
                    "headers": [], "query_string": b"", "app": app, "state": {}})


def _devices_request(count: int) -> Request:
    request = _request("/api/claw/local-access/devices")

    class Directory:
        configured = True

        async def list_devices(self, **_):
            await asyncio.sleep(DELAY)
            return []

    class Links:
        async def links_for_owner(self, *, user_id):
            await asyncio.sleep(DELAY)
            return []

    class Drives:
        async def load_drives(self, *, device_id):
            await asyncio.sleep(DELAY)
            return None

    class Mesh:
        def __init__(self, size: int) -> None:
            self.size = size

        def command_device_ids(self, *, account_ref):
            return [f"pc_{index}" for index in range(self.size)]

    async def resolve(_request, *, owner_id, workspace_id, connector=None, device_id=None):
        await asyncio.sleep(DELAY)
        return SimpleNamespace(ready=True, device_id=device_id or "primary", status="ready")

    async def connector(*_a, **_k):
        return SimpleNamespace(ready=True, account_ref="a", workspace_ref="w",
                               session_id="s", status="ready")

    async def workspace(*_a):
        return WS

    devices.auth_ready = lambda _r: True
    devices.current_user_id = lambda _r: UID
    devices._resolve_memory_workspace = workspace
    devices.resolve_pc_connector_scope = connector
    devices.resolve_pc_mesh_target = resolve
    request.app.state.claw_device_directory_source = Directory()
    request.app.state.pc_device_pairing_store = Links()
    request.app.state.mesh_device_drive_store = Drives()
    request.app.state.oracle_mesh_return_source = Mesh(count)
    request.app.state.mesh_device_presence_store = None
    request.app.state.claw_pc_device_selection_store = None
    return request


def _models_request(calls: dict) -> Request:
    request = _request("/api/claw/verified-model-choices")

    class Roster:
        async def list_selectable_models(self):
            calls["n"] += 1
            await asyncio.sleep(0.3)
            return [{"model_id": "model-a", "name": "A"}]

    async def denial(*_a, **_k):
        return None

    async def view(*_a, **_k):
        return SimpleNamespace(ok=True, model_id="model-a", fallback_model_id=None,
                              source="central"), 1

    import app.auth_routes as auth_routes
    auth_routes.auth_ready = lambda _r: True
    auth_routes.current_user_id = lambda _r: UID
    import app.member_grade_access as grade
    grade.selected_grade_denial = denial
    grade.selected_admin_denial = denial
    import app.central_model_route_runtime as runtime
    runtime.resolve_claw_tier_model_view = view
    request.app.state.b14_model_choice_resolver = Roster()
    return request


def _timed(call) -> float:
    started = time.perf_counter()
    asyncio.run(call)
    return round((time.perf_counter() - started) * 1000, 1)


def _scope_timings(delay: float, *, cache_seconds: str | None) -> tuple[float, float]:
    """First (miss) and second (hit) connector-scope resolution."""
    import app.pc_work_context as context
    from app.pc_scope_cache import clear_scope_cache

    class Authority:
        async def resolve_connector_owner_scope(self, *, session_id):
            await asyncio.sleep(delay)
            return {"account_ref": "account-1", "workspace_ref": "connector-ws"}

    def session(name: str) -> SimpleNamespace:
        return SimpleNamespace(session_id=name, tenant_id=WS,
                               subject=SimpleNamespace(subject_id="subject-1"))

    async def owner_session(_request, _owner_id):
        await asyncio.sleep(delay)
        return WS, session("sess-b62")

    async def b54(_authority, _owner_id):
        await asyncio.sleep(delay)
        return SimpleNamespace(auth_session=session("sess-b54"))

    import padiem_control_plane.b54_identity_bridge as bridge

    request = _request("/api/claw/local-access/devices")
    request.app.state.control_plane_identity_authority = Authority()
    request.app.state.identity_shadow_store = object()
    original_owner_session = context._resolve_owner_session
    original_bridge = bridge.resolve_current_b54_canonical_session
    context._resolve_owner_session = owner_session
    bridge.resolve_current_b54_canonical_session = b54
    previous = os.environ.pop("PADIEM_CHAT_SCOPE_CACHE_SECONDS", None)
    if cache_seconds is not None:
        os.environ["PADIEM_CHAT_SCOPE_CACHE_SECONDS"] = cache_seconds
    try:
        clear_scope_cache()
        first = _timed(context.resolve_pc_connector_scope(
            request, owner_id=UID, workspace_id=WS,
        ))
        second = _timed(context.resolve_pc_connector_scope(
            request, owner_id=UID, workspace_id=WS,
        ))
    finally:
        context._resolve_owner_session = original_owner_session
        bridge.resolve_current_b54_canonical_session = original_bridge
        os.environ.pop("PADIEM_CHAT_SCOPE_CACHE_SECONDS", None)
        if previous is not None:
            os.environ["PADIEM_CHAT_SCOPE_CACHE_SECONDS"] = previous
        clear_scope_cache()
    return first, second


def main() -> int:
    print(f"dependency delay: {DELAY * 1000:.0f} ms per authority read")
    for count in (0, 3):
        request = _devices_request(count)
        samples = [_timed(devices.claw_device_directory(request)) for _ in range(3)]
        print(f"/api/claw/local-access/devices (+{count} enumerated PCs): "
              f"median {statistics.median(samples):.0f} ms  samples {samples}")
    for label, ttl in (("window off", "0"), ("30s window", None)):
        first, second = _scope_timings(DELAY, cache_seconds=ttl)
        print(f"connector scope resolve ({label}): first {first:.0f} ms / "
              f"second {second:.0f} ms")
    calls = {"n": 0}
    request = _models_request(calls)
    first = _timed(models.claw_verified_model_choices(request))
    second = _timed(models.claw_verified_model_choices(request))
    window = os.getenv("PADIEM_CHAT_MODEL_ROSTER_CACHE_SECONDS", "default")
    print(f"/api/claw/verified-model-choices first/second: {first:.0f} / {second:.0f} ms, "
          f"roster reads {calls['n']} (env {window})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
