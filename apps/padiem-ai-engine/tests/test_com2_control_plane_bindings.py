"""#7229: the COM2 P01 host composes the same Control Plane authorities the Worker does.

The Calendar READ lane on Cloudflare asks three bindings for its authority
(``worker_identity._calendar_read_activation_service_for_env``): the identity
workspace read, the private Google OAuth binding selection, and the connector
grant store. The host used to provide only the first, so the composition
returned ``None`` and every activation answered ``503
calendar_activation_unavailable``.

These tests pin three things and nothing else:

* parity — the binding names the Worker composition requires are exactly the
  names the host composition provides once configured, so a change on either
  side alone turns red;
* fail-closed — with the new host configuration absent, the same names stay
  unbound and the reviewed 503 path is unchanged (merging changes no behavior);
* the wires actually work — each leg reaches a real v2-proof ingress and the
  reviewed adapter on top of it, and never leaks a secret or upstream text.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.calendar_read_activation import (
    CloudflareCalendarBindingClient,
    CloudflareConnectorWorkspaceClient,
)
from app.connector_grants_d1 import CloudflareD1ConnectorGrantStore
from app.local_google_oauth_binding import (
    GOOGLE_OAUTH_ORIGIN_ENV, GOOGLE_OAUTH_SECRET_ENV, google_oauth_binding_for,
)
from app.local_identity_binding import IDENTITY_ORIGIN_ENV, IDENTITY_SECRET_ENV
from app.local_runtime import DB_PATH_ENV, _env_view

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR.parents[1] / "packages/padiem-control-plane"))
from internal_rpc_ingress import handle_internal_rpc

WORKER_SOURCE = (ENGINE_DIR / "worker_identity.py").read_text(encoding="utf-8")
CALENDAR_COMPOSERS = (
    "_calendar_read_activation_service_for_env",
    "_calendar_read_state_service_for_env",
)
IDENTITY_SECRET = "synthetic-com2-identity-ingress-secret-0001"
OAUTH_SECRET = "synthetic-com2-google-oauth-ingress-secret-0002"
IDENTITY_ORIGIN = "https://identity.example.test"
OAUTH_ORIGIN = "https://google-oauth-state.example.test"


def _module_constants() -> dict[str, str]:
    """String constants ``worker_identity`` names its bindings with."""

    constants: dict[str, str] = {}
    for node in ast.parse(WORKER_SOURCE).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                constants[target.id] = node.value.value
    return constants


def _worker_required_bindings() -> set[str]:
    """Every binding name the two Calendar composers read, resolved to its value."""

    constants = _module_constants()
    required: set[str] = set()
    for name in CALENDAR_COMPOSERS:
        function = next(
            node for node in ast.parse(WORKER_SOURCE).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        )
        for call in (n for n in ast.walk(function) if isinstance(n, ast.Call)):
            target = call.func
            if not (isinstance(target, ast.Attribute) and target.attr == "_binding_value"):
                continue
            argument = call.args[1] if len(call.args) > 1 else None
            assert isinstance(argument, ast.Name), name
            required.add(constants[argument.id])
    return required


def _configured_values(tmp_path: Path) -> dict[str, str]:
    return {
        IDENTITY_ORIGIN_ENV: IDENTITY_ORIGIN,
        IDENTITY_SECRET_ENV: IDENTITY_SECRET,
        GOOGLE_OAUTH_ORIGIN_ENV: OAUTH_ORIGIN,
        GOOGLE_OAUTH_SECRET_ENV: OAUTH_SECRET,
        DB_PATH_ENV: str(tmp_path / "engine.sqlite3"),
    }


# --------------------------------------------------------------------------
# 1. parity: one composition cannot drift away from the other
# --------------------------------------------------------------------------
def test_host_composition_provides_every_binding_the_worker_calendar_lane_requires(tmp_path):
    required = _worker_required_bindings()
    # The Worker reads exactly the three authorities this issue documents; a
    # fourth one appearing there must fail here rather than at runtime on COM2.
    assert required == {
        "CONTROL_PLANE_IDENTITY",
        "CONTROL_PLANE_GOOGLE_OAUTH",
        "ENGINE_CONNECTOR_GRANTS",
    }

    env = _env_view(_configured_values(tmp_path))
    provided = {
        name for name in required
        if getattr(env, name, None) is not None
    }
    assert provided == required


def test_worker_and_host_calendar_composers_stay_paired():
    """The host must compose from these three names, not from look-alikes."""

    runtime_source = (ENGINE_DIR / "app/local_runtime.py").read_text(encoding="utf-8")
    for binding_name in ("ENGINE_IDEMPOTENCY", "ENGINE_CONNECTOR_GRANTS"):
        assert f'bindings["{binding_name}"] = database' in runtime_source, binding_name
    for factory in ("identity_binding_for", "google_oauth_binding_for"):
        assert f"bindings.update({factory}(values))" in runtime_source, factory
    for composer in CALENDAR_COMPOSERS:
        assert composer in WORKER_SOURCE, composer


# --------------------------------------------------------------------------
# 2. fail-closed: absent configuration keeps today's 503 path
# --------------------------------------------------------------------------
@pytest.mark.parametrize("values", [
    {},
    {GOOGLE_OAUTH_ORIGIN_ENV: OAUTH_ORIGIN},
    {GOOGLE_OAUTH_SECRET_ENV: OAUTH_SECRET},
    {GOOGLE_OAUTH_ORIGIN_ENV: OAUTH_ORIGIN, GOOGLE_OAUTH_SECRET_ENV: "too-short"},
    *({GOOGLE_OAUTH_ORIGIN_ENV: origin, GOOGLE_OAUTH_SECRET_ENV: OAUTH_SECRET} for origin in (
        "http://google-oauth-state.example.test",
        "https://user:password@google-oauth-state.example.test",
        OAUTH_ORIGIN + "/internal/rpc",
        OAUTH_ORIGIN + "?token=private",
        "https://[broken",
    )),
])
def test_unconfigured_or_malformed_google_oauth_leaves_the_binding_absent(values):
    assert google_oauth_binding_for(values) == {}


def test_absent_google_oauth_keeps_the_calendar_lane_fail_closed(tmp_path):
    """Without the pair, the lane has no authority — never a local stand-in."""

    env = _env_view({DB_PATH_ENV: str(tmp_path / "engine.sqlite3")})
    assert env.CONTROL_PLANE_GOOGLE_OAUTH is None
    with pytest.raises(ValueError):
        CloudflareCalendarBindingClient(env.CONTROL_PLANE_GOOGLE_OAUTH)


# --------------------------------------------------------------------------
# 3. the wires: real v2 ingress behind each reviewed adapter
# --------------------------------------------------------------------------
class _Request:
    def __init__(self, request):
        self.url = str(request.url)
        self.method = request.method
        self.headers = request.headers
        self.raw = request.content

    async def text(self):
        return self.raw.decode()


class _ReplayGuard:
    def __init__(self):
        self.ids: set[str] = set()

    async def claim(self, service_id, *, expires_at):
        if service_id in self.ids:
            return False
        self.ids.add(service_id)
        return True


def _ingress(secret: str, allowed: frozenset[str], dispatcher, seen: list):
    async def handler(request):
        seen.append(request)
        status, body, headers = await handle_internal_rpc(
            _Request(request), secret=secret, allowed_methods=allowed,
            dispatcher=dispatcher, service_id_policy="required",
            replay_guard=_ReplayGuard(),
        )
        return httpx.Response(status, json=body, headers=headers)

    return handler


async def test_identity_workspace_read_reaches_the_real_ingress(tmp_path, monkeypatch):
    calls = []
    seen = []

    async def resolve_connector_workspace(payload):
        calls.append(payload)
        return {"ok": True, "workspace": {"present": True, "workspace_ref": "ws_synthetic"}}

    _patch_transport(monkeypatch, _ingress(
        IDENTITY_SECRET, frozenset({"resolve_connector_workspace"}),
        SimpleNamespace(resolve_connector_workspace=resolve_connector_workspace), seen,
    ))
    env = _env_view(_configured_values(tmp_path))
    client = CloudflareConnectorWorkspaceClient(env.CONTROL_PLANE_IDENTITY)
    assert await client.resolve_connector_workspace(session_id="synthetic-session") == "ws_synthetic"
    assert calls == [{"session_id": "synthetic-session"}]
    assert seen[0].url.path == "/internal/rpc/resolve_connector_workspace"
    assert seen[0].headers["x-padiem-service-proof"].startswith("v2=")


async def test_google_oauth_binding_selection_reaches_the_real_ingress(tmp_path, monkeypatch):
    calls = []
    seen = []

    async def select_calendar_binding(payload):
        calls.append(payload)
        return {"ok": True, "selection": {
            "status": "resolved",
            "connector_id": "google-calendar",
            "workspace_ref": "ws_synthetic",
            "binding_ref": "bind_synthetic",
            "actor_ref": "actor_synthetic",
        }}

    _patch_transport(monkeypatch, _ingress(
        OAUTH_SECRET, frozenset({"select_calendar_binding"}),
        SimpleNamespace(select_calendar_binding=select_calendar_binding), seen,
    ))
    env = _env_view(_configured_values(tmp_path))
    client = CloudflareCalendarBindingClient(env.CONTROL_PLANE_GOOGLE_OAUTH)
    assert await client.select_calendar_binding(workspace_ref="ws_synthetic") == (
        "bind_synthetic", "actor_synthetic",
    )
    assert calls == [{"workspace_ref": "ws_synthetic"}]
    assert seen[0].url.path == "/internal/rpc/select_calendar_binding"
    assert seen[0].headers["x-padiem-service-proof"].startswith("v2=")


@pytest.mark.parametrize("failure", ["wrong_secret", "method_not_allowed", "unreachable"])
async def test_google_oauth_failure_carries_no_secret_or_upstream_text(
    failure, tmp_path, monkeypatch, capsys,
):
    async def select_calendar_binding(payload):  # pragma: no cover - never reached for some cases
        return {"ok": True, "selection": {}}

    seen: list = []
    if failure == "unreachable":
        async def handler(request):
            raise httpx.ConnectError("sensitive-upstream-detail", request=request)
    else:
        handler = _ingress(
            OAUTH_SECRET if failure != "wrong_secret" else "different-ingress-secret-0003",
            frozenset({"workspace_connector_state"}),
            SimpleNamespace(select_calendar_binding=select_calendar_binding), seen,
        )
    _patch_transport(monkeypatch, handler)
    binding = google_oauth_binding_for({
        GOOGLE_OAUTH_ORIGIN_ENV: OAUTH_ORIGIN, GOOGLE_OAUTH_SECRET_ENV: OAUTH_SECRET,
    })["CONTROL_PLANE_GOOGLE_OAUTH"]
    client = CloudflareCalendarBindingClient(binding)
    with pytest.raises(Exception) as caught:
        await client.select_calendar_binding(workspace_ref="ws_synthetic")
    message = str(caught.value)
    assert OAUTH_SECRET not in message
    assert "sensitive-upstream-detail" not in message
    assert OAUTH_ORIGIN not in message
    assert capsys.readouterr() == ("", "")


def test_connector_grants_share_the_one_engine_database(tmp_path):
    """Cloudflare declares two names over one D1; the host mirrors that exactly."""

    env = _env_view({DB_PATH_ENV: str(tmp_path / "engine.sqlite3")})
    assert env.ENGINE_CONNECTOR_GRANTS is env.ENGINE_IDEMPOTENCY

    async def read_grants():
        store = CloudflareD1ConnectorGrantStore(env.ENGINE_CONNECTOR_GRANTS)
        return await store.load_calendar_grants()

    import asyncio

    # The reviewed store reads the migrated table; an empty table is a real
    # answer ("nothing granted"), not a missing authority.
    assert asyncio.run(read_grants()) == {}


def _patch_transport(monkeypatch, handler) -> None:
    """Inject the HTTP boundary only; composition and factories stay under test."""

    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original_client(
        transport=httpx.MockTransport(handler), **kw
    ))
