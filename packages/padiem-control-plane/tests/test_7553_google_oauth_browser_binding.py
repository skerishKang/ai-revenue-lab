"""#7553 — a Google connector callback completes only in the starting browser.

Chat places a random value in a cookie on the browser that starts a Google
connection and sends only its SHA-256 to the private runtime with the connect
ticket. The OAuth edge forwards the cookie with the callback; the runtime
compares it before any code exchange. A callback finished in any other browser
never stores a credential for the starting workspace.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import hashlib

from google_oauth_ingress_runtime import (
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from test_google_oauth_ingress_runtime import (
    AUTH_CODE,
    CLIENT_SECRET,
    NOW,
    TokenSource,
    fixture,
    ticket,
)

ROOT = Path(__file__).resolve().parents[1]


def browser_binding_digest_for(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

STARTER = "starter-browser-binding-value-0123456789abcdef"
OTHER = "another-browser-binding-value-0123456789abcdef"


def bound_runtime():
    _, storage, durable_store, sealer, authority, exchange = fixture()
    runtime = GoogleOAuthIngressRuntime(
        store=durable_store,
        sealer=sealer,
        ticket_authority=authority,
        config=GoogleOAuthIngressConfig(
            client_id="client-id-public",
            client_secret=CLIENT_SECRET,
            redirect_uri="https://oauth.example.invalid/v1/google/callback",
        ),
        token_exchange=exchange,
        clock=lambda: NOW,
        random_token=TokenSource(),
        require_browser_binding=True,
    )
    return runtime, storage, authority, exchange


def start(runtime, authority, binding: str = STARTER) -> str:
    receipt = asyncio.run(
        runtime.begin(
            connect_ticket=ticket(authority),
            browser_binding_digest=browser_binding_digest_for(binding),
        )
    )
    return parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]


def finish(runtime, state_ref: str, binding: str | None):
    return asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
            browser_binding=binding,
        )
    )


@pytest.mark.parametrize("binding", [None, OTHER])
def test_a_callback_finished_in_another_browser_never_attaches_to_the_starting_workspace(binding):
    runtime, storage, authority, exchange = bound_runtime()
    state_ref = start(runtime, authority)

    with pytest.raises(ControlPlaneContractError) as exc:
        finish(runtime, state_ref, binding)

    assert exc.value.code == "google_oauth_browser_mismatch"
    assert exchange.calls == []
    assert storage.count("google_oauth_refresh_credential") == 0
    # The state is spent: the same callback cannot be retried with a guess.
    with pytest.raises(ControlPlaneContractError):
        finish(runtime, state_ref, STARTER)


def test_the_starting_browser_still_connects_its_own_workspace():
    runtime, storage, authority, exchange = bound_runtime()
    state_ref = start(runtime, authority)

    connected = finish(runtime, state_ref, STARTER)

    assert connected.workspace_ref == "workspace_1"
    assert len(exchange.calls) == 1
    assert storage.count("google_oauth_refresh_credential") == 1
    assert STARTER not in storage.all_text()


def test_a_bound_runtime_refuses_to_start_without_a_browser_binding():
    runtime, storage, authority, _ = bound_runtime()
    with pytest.raises(ControlPlaneContractError) as exc:
        asyncio.run(runtime.begin(connect_ticket=ticket(authority)))
    assert exc.value.code == "google_oauth_browser_binding_required"
    assert storage.count("google_oauth_authorization_state") == 0


def test_production_worker_composes_the_bound_runtime():
    source = (ROOT / "google_oauth_worker.py").read_text(encoding="utf-8")
    assert "require_browser_binding=True" in source
    assert "browser_binding=payload.get(\"browser_binding\")" in source


class _FakeResponse:
    def __init__(self, body="", status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = dict(headers or {})


class _FakeEntrypoint:
    def __init__(self, env=None):
        self.env = env


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key.lower(), default)


class _Request:
    def __init__(self, url, *, method="GET", headers=None):
        self.url = url
        self.method = method
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.body = None


class _Service:
    def __init__(self):
        self.calls = []

    async def complete_callback(self, payload):
        self.calls.append(dict(payload))
        return {"ok": True, "connection": {"connector_id": "gmail"}}


def _edge():
    fake = types.ModuleType("workers")
    fake.Response = _FakeResponse
    fake.WorkerEntrypoint = _FakeEntrypoint
    previous = sys.modules.get("workers")
    sys.modules["workers"] = fake
    try:
        spec = importlib.util.spec_from_file_location("edge_7553", ROOT / "google_oauth_edge_worker.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            del sys.modules["workers"]
        else:
            sys.modules["workers"] = previous


def test_edge_forwards_the_binding_cookie_and_always_expires_it():
    edge = _edge()
    service = _Service()
    env = types.SimpleNamespace(
        GOOGLE_OAUTH_SERVICE=service, GOOGLE_OAUTH_ALLOWED_ORIGIN="https://chat.padiem.net"
    )
    worker = edge.Default(env)
    request = _Request(
        "https://oauth.padiem.net/v1/google/callback?state=state_1&code=c",
        headers={"Cookie": f"other=1; {edge.BROWSER_BINDING_COOKIE}={STARTER}"},
    )
    response = asyncio.run(worker.fetch(request))
    assert service.calls == [
        {"state_ref": "state_1", "authorization_code": "c", "provider_error": None, "browser_binding": STARTER}
    ]
    assert response.status == 303
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{edge.BROWSER_BINDING_COOKIE}=;")
    assert "Domain=padiem.net" in cookie and "Max-Age=0" in cookie and "Path=/v1/google/callback" in cookie

    # Without the cookie nothing is forwarded, so the runtime refuses it.
    service.calls.clear()
    asyncio.run(worker.fetch(_Request("https://oauth.padiem.net/v1/google/callback?state=s&code=c")))
    assert "browser_binding" not in service.calls[0]


def test_edge_accepts_the_binding_digest_with_the_connect_ticket():
    edge = _edge()
    digest = browser_binding_digest_for(STARTER)
    body = json.dumps({"connect_ticket": "t", "browser_binding_digest": digest}).encode()
    assert edge._parse_connect_body(body) == {"connect_ticket": "t", "browser_binding_digest": digest}
    with pytest.raises(ValueError):
        edge._parse_connect_body(json.dumps({"connect_ticket": "t", "browser_binding_digest": "x"}).encode())
