"""The COM2 host binds the Calendar READ grant-state client, like the Worker does.

Two surfaces answer the same question: the deployed Worker
(``apps/padiem-chat/worker.py``) binds ``calendar_read_state_engine_client`` over
the P01 Engine Service Binding, and the CPython host
(``apps/padiem-chat/app/local_cpython.py``) must bind the SAME client class over
its loopback Engine binding. Before this wiring the host bound only the
activation half, so ``GET /api/connectors/status`` silently dropped the
``calendar_read_grant_state`` field on COM2 while the Worker path answered it.

These regressions are load-bearing in both directions:

* the behavioural ones fail if the host builder stops reaching the reviewed
  read-state path or stops sending the same caller surface;
* the parity one fails if either assembly drops either of the two Calendar
  clients, so one side cannot drift away from the other again.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.connector_status_projection import _reviewed_calendar_read_grant_state
from app.local_p01_engine import build_local_calendar_read_state_client

ENGINE_ORIGIN = "http://127.0.0.1:8811"
CALLER_ID = "b54-padiem-claw-calendar"
CALLER_CREDENTIAL = "synthetic-engine-credential-value-0001"
SESSION_ID = "sess_" + "b" * 32
READ_STATE_PATH = "/internal/connectors/calendar/read/state"

ENGINE_ENV = {
    "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": ENGINE_ORIGIN,
    "PADIEM_CHAT_LOCAL_P01_CALLER_ID": CALLER_ID,
    "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": CALLER_CREDENTIAL,
}

APP_DIR = Path(__file__).resolve().parents[1] / "app"
WORKER_SOURCE = APP_DIR.parent / "worker.py"
LOCAL_SOURCE = APP_DIR / "local_cpython.py"

# The closed read-state document the Engine client accepts.
STATE_OK = {
    "ok": True,
    "calendar_read_grant_state": "active",
    "calendar_write_authorized": False,
    "binding_ref_projected": False,
    "actor_ref_projected": False,
    "workspace_ref_projected": False,
    "session_id_projected": False,
}


def _state_handler(seen: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == READ_STATE_PATH:
            return httpx.Response(200, json=STATE_OK)
        return httpx.Response(
            404, json={"ok": False, "error": {"code": "not_found", "message": "synthetic"}}
        )

    return httpx.MockTransport(handler)


def _bound_state(state_module_attr: str, value: object) -> SimpleNamespace:
    """The minimal ``request`` shape the grant-state projection reads."""

    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(**{state_module_attr: value}))
    )


def test_the_host_builder_binds_the_shared_worker_client_class():
    client, diagnostic = build_local_calendar_read_state_client(
        ENGINE_ENV, client=httpx.AsyncClient(transport=_state_handler([]))
    )
    assert diagnostic is None
    assert client is not None
    assert type(client).__name__ == "CloudflareCalendarReadStateEngineClient"


def test_an_unconfigured_engine_surface_keeps_the_state_client_unbound():
    client, diagnostic = build_local_calendar_read_state_client({})
    assert client is None
    assert diagnostic is None


@pytest.mark.asyncio
async def test_the_host_state_client_asks_the_reviewed_path_with_the_worker_caller():
    seen: list[httpx.Request] = []
    engine = httpx.AsyncClient(transport=_state_handler(seen))
    try:
        client, _ = build_local_calendar_read_state_client(ENGINE_ENV, client=engine)
        assert client is not None
        assert await client.read_state(session_id=SESSION_ID) == "active"
    finally:
        await engine.aclose()

    assert [request.url.path for request in seen] == [READ_STATE_PATH]
    request = seen[0]
    assert request.method == "POST"
    assert request.headers["x-padiem-engine-caller"] == CALLER_ID
    assert request.headers["x-padiem-engine-credential"] == CALLER_CREDENTIAL


@pytest.mark.asyncio
async def test_the_status_projection_asks_the_engine_for_the_grant_state():
    engine = httpx.AsyncClient(transport=_state_handler([]))
    try:
        client, _ = build_local_calendar_read_state_client(ENGINE_ENV, client=engine)
        request = _bound_state("calendar_read_state_engine_client", client)
        assert await _reviewed_calendar_read_grant_state(request, SESSION_ID) == "active"
    finally:
        await engine.aclose()


@pytest.mark.asyncio
async def test_an_unbound_state_client_leaves_the_grant_field_absent():
    request = _bound_state("calendar_read_state_engine_client", None)
    assert await _reviewed_calendar_read_grant_state(request, SESSION_ID) is None


@pytest.mark.asyncio
async def test_a_rejected_state_check_is_unavailable_never_inactive():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"ok": False, "error": {"code": "service_app_not_authorized"}}
        )

    engine = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        client, _ = build_local_calendar_read_state_client(ENGINE_ENV, client=engine)
        request = _bound_state("calendar_read_state_engine_client", client)
        assert (
            await _reviewed_calendar_read_grant_state(request, SESSION_ID) == "unavailable"
        )
    finally:
        await engine.aclose()


def _bound_state_attributes(source: Path) -> set[str]:
    """Every ``<app>.state.<name> =`` assignment target in one assembly module."""

    bound: set[str] = set()
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            value = target.value
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "state"
            ):
                bound.add(target.attr)
    return bound


CALENDAR_CLIENTS = (
    "calendar_read_activation_client",
    "calendar_read_state_engine_client",
)


def test_both_assemblies_bind_both_calendar_engine_clients():
    """One side dropping a client is the regression this pins."""

    worker_bound = _bound_state_attributes(WORKER_SOURCE)
    host_bound = _bound_state_attributes(LOCAL_SOURCE)
    for name in CALENDAR_CLIENTS:
        assert name in worker_bound, f"worker.py stopped binding {name}"
        assert name in host_bound, f"local_cpython.py stopped binding {name}"


def test_the_host_binds_the_state_client_through_the_local_builder():
    """The host must reuse the shared builder, not a second composition."""

    source = LOCAL_SOURCE.read_text(encoding="utf-8")
    assert "build_local_calendar_read_state_client" in source
    assert (
        "app.state.calendar_read_state_engine_client = calendar_read_state_client"
        in source
    )
