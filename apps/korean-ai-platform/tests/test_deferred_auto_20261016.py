"""b14/auto is retired: the id is rejected as a string and the auto lane is gone (B7)."""
import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app

AUTO = {"model": "b14/auto", "messages": [{"role": "user", "content": "synthetic no-provider-call"}]}


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_retired_auto_on_completions(client):
    r = client.post("/api/pilot/v1/chat/completions", json=AUTO)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_body"
    assert "b14/auto" in r.json()["error"]["message"]


def test_retired_auto_on_resolve(client):
    r = client.post("/api/pilot/router/resolve", json=AUTO)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_body"


def test_auto_stream_preview_route_is_gone(client):
    r = client.post("/api/pilot/v1/chat/completions/auto-stream-preview", json={**AUTO, "stream": True})
    assert r.status_code == 404


def test_auto_lane_modules_do_not_exist():
    for name in ("app.pilot.routing_policy", "app.pilot.auto_stream_gateway", "app.pilot.auto_availability"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)


def test_future_auto_opt_in_no_longer_exists():
    root = Path(__file__).resolve().parents[1]
    env_example = (root / "b14.env.example").read_text(encoding="utf-8")
    assert "B14_ENABLE_FUTURE_AUTO" not in env_example
    app_source = "\n".join(
        p.read_text(encoding="utf-8") for p in (root / "app").rglob("*.py")
    )
    assert "B14_ENABLE_FUTURE_AUTO" not in app_source


def test_workspace_has_no_auto_selection():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/workspace.html").read_text(encoding="utf-8")
    js = (root / "static/start.js").read_text(encoding="utf-8")
    assert 'value="b14/auto"' not in template
    assert 'name="start_route_mode" value="auto"' not in template
    assert 'value="manual" checked' in template
    assert 'activeRouteMode: "manual"' in js
    assert 'var model = state.activeModel;' in js
