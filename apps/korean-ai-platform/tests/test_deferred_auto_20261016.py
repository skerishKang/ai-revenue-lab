"""Production default: generic b14/auto is deferred, exact model calls remain supported."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.auto_availability import ensure_generic_auto_enabled
from app.pilot.errors import PilotError

AUTO = {"model": "b14/auto", "messages": [{"role":"user","content":"synthetic no-provider-call"}]}


@pytest.fixture(autouse=True)
def disable_generic_auto(monkeypatch):
    monkeypatch.delenv("B14_ENABLE_FUTURE_AUTO", raising=False)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_deferred_auto_on_completions(client):
    r = client.post("/api/pilot/v1/chat/completions", json=AUTO)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auto_routing_deferred"


def test_deferred_auto_on_resolve(client):
    r = client.post("/api/pilot/router/resolve", json=AUTO)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auto_routing_deferred"


def test_deferred_auto_on_stream_preview(client):
    r = client.post("/api/pilot/v1/chat/completions/auto-stream-preview", json={**AUTO, "stream": True})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "auto_routing_deferred"


def test_exact_model_is_not_deferred():
    ensure_generic_auto_enabled("opencode-go/cat-jam-free")


def test_future_code_preserved_but_explicit_opt_in_only(monkeypatch):
    with pytest.raises(PilotError) as e:
        ensure_generic_auto_enabled("b14/auto")
    assert e.value.status_code == 422
    monkeypatch.setenv("B14_ENABLE_FUTURE_AUTO", "1")
    ensure_generic_auto_enabled("b14/auto")


def test_workspace_has_no_auto_selection():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/workspace.html").read_text(encoding="utf-8")
    js = (root / "static/start.js").read_text(encoding="utf-8")
    assert 'value="b14/auto"' not in template
    assert 'name="start_route_mode" value="auto"' not in template
    assert 'value="manual" checked' in template
    assert 'activeRouteMode: "manual"' in js
    assert 'var model = state.activeModel;' in js
