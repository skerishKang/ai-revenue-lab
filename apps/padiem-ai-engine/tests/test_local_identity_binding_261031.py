"""Host identity transport reuses the reviewed ingress, never an auth shortcut."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.auth_session_scope_authority import CloudflareControlPlaneAuthSessionClient
from app.local_identity_binding import (
    IDENTITY_ORIGIN_ENV, IDENTITY_SECRET_ENV, HttpsIdentityBinding, identity_binding_for,
)
from app.local_runtime import _env_view

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/padiem-control-plane"))
from internal_rpc_ingress import handle_internal_rpc

SECRET = "synthetic-identity-ingress-secret-for-test-only"
ORIGIN = "https://identity.example.test"


class _Request:
    def __init__(self, request):
        self.url, self.method, self.headers = str(request.url), request.method, request.headers
        self.raw = request.content

    async def text(self):
        return self.raw.decode()


class _ReplayGuard:
    def __init__(self):
        self.ids = set()

    async def claim(self, service_id, *, expires_at):
        if service_id in self.ids:
            return False
        self.ids.add(service_id)
        return True


async def test_host_env_identity_reaches_real_v2_ingress_and_scope_client(monkeypatch):
    session = {"session_id": "synthetic-session"}
    calls, requests = [], []
    guard = _ReplayGuard()

    async def resolve_auth_session(payload):
        calls.append(payload)
        return {"ok": True, "session": session}

    async def ingress(request):
        requests.append(request)
        result = await handle_internal_rpc(
            _Request(request), secret=SECRET,
            allowed_methods=frozenset({"resolve_auth_session"}),
            dispatcher=SimpleNamespace(resolve_auth_session=resolve_auth_session),
            service_id_policy="required", replay_guard=guard,
        )
        status, body, headers = result
        return httpx.Response(status, json=body, headers=headers)

    # Inject the HTTP boundary, not the binding factory/composition under test.
    original_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original_client(
        transport=httpx.MockTransport(ingress), **kw
    ))
    env = _env_view({IDENTITY_ORIGIN_ENV: ORIGIN, IDENTITY_SECRET_ENV: SECRET})
    client = CloudflareControlPlaneAuthSessionClient(env.CONTROL_PLANE_IDENTITY)
    assert await client.resolve_auth_session(session_id="synthetic-session") == session
    assert await client.resolve_auth_session(session_id="synthetic-session") == session
    assert calls == [{"session_id": "synthetic-session"}] * 2
    assert len(guard.ids) == 2
    assert all(r.headers["x-padiem-service-proof"].startswith("v2=") for r in requests)
    assert all(r.url.path == "/internal/rpc/resolve_auth_session" for r in requests)
    assert env.CONTROL_PLANE_ENGINE_ADMISSION is None


@pytest.mark.parametrize("values", [
    {}, {IDENTITY_ORIGIN_ENV: ORIGIN}, {IDENTITY_SECRET_ENV: SECRET},
    {IDENTITY_ORIGIN_ENV: ORIGIN, IDENTITY_SECRET_ENV: "short"},
    *({IDENTITY_ORIGIN_ENV: origin, IDENTITY_SECRET_ENV: SECRET} for origin in (
        "http://identity.example.test", "https://user:password@identity.example.test",
        ORIGIN + "/rpc", ORIGIN + "?token=private", ORIGIN + "#fragment",
        "https://[broken",
    )),
])
def test_invalid_or_missing_identity_configuration_stays_unbound(values):
    assert identity_binding_for(values) == {}


@pytest.mark.parametrize("failure", ["bad_proof", "redirect", "unreachable", "invalid_json"])
async def test_identity_transport_fails_closed_without_raw_error_material(failure, capsys):
    calls = []
    refused = []

    async def ingress(request):
        calls.append(request)
        if failure == "unreachable":
            raise httpx.ConnectError("sensitive-upstream-detail", request=request)
        if failure == "redirect":
            return httpx.Response(302, headers={"location": "https://untrusted.example.test"})
        if failure == "invalid_json":
            return httpx.Response(200, content=b"sensitive-upstream-detail")
        bad_headers = dict(request.headers)
        bad_headers["x-padiem-service-id"] = "tampered-request-id-0001"
        tampered = httpx.Request("POST", request.url, headers=bad_headers, content=request.content)
        status, body, headers = await handle_internal_rpc(
            _Request(tampered), secret=SECRET,
            allowed_methods=frozenset({"resolve_auth_session"}),
            dispatcher=SimpleNamespace(), service_id_policy="required", replay_guard=_ReplayGuard(),
        )
        refused.append((status, body["error"]["code"]))
        return httpx.Response(status, json=body, headers=headers)

    async with httpx.AsyncClient(transport=httpx.MockTransport(ingress), follow_redirects=False) as client:
        binding = HttpsIdentityBinding(ORIGIN, SECRET, client=client)
        with pytest.raises(RuntimeError, match="^identity authority is unavailable$") as caught:
            await binding.resolve_auth_session({"session_id": "synthetic-session"})
    assert len(calls) == 1
    if failure == "bad_proof":
        assert refused == [(403, "rpc_proof_invalid")]
    assert caught.value.__cause__ is None
    assert capsys.readouterr() == ("", "")
    assert SECRET not in str(caught.value)
