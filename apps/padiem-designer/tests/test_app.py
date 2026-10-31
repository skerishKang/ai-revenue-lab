"""The HTTP surface answers honestly and serves the preview."""

from __future__ import annotations

from typing import Any, Mapping

import pytest
from starlette.testclient import TestClient

from app.app_factory import build_app
from app.config import Settings
from app.contracts import ModelTurn
from app.model_route import ModelRequest


class _StubRoute:
    """A route that returns one fixed tool call."""

    kind = "openai_compatible"

    def __init__(self, tool_called: bool = True) -> None:
        self.tool_called = tool_called
        self.requests: list[ModelRequest] = []

    @property
    def supports_tool_calls(self) -> bool:
        return True

    async def generate(self, request: ModelRequest) -> ModelTurn:
        self.requests.append(request)
        calls: tuple[Mapping[str, Any], ...] = ()
        if self.tool_called:
            calls = (
                {
                    "function": {
                        "name": "generateSandboxedUi",
                        "arguments": '{"css": ".a{color:red}", "html": "<div id=\'x\'>hi</div>"}',
                    }
                },
            )
        return ModelTurn(
            text="Made it.",
            tool_calls=calls,
            model_id="stub/model",
            route_kind=self.kind,
        )


def _client(route: Any | None = None, settings: Settings | None = None) -> TestClient:
    effective = settings or Settings(dev_tenant_id="tenant-a", dev_user_id="user-a")
    app = build_app(settings=effective, model_route=route or _StubRoute())
    return TestClient(app)


def test_health_reports_what_is_actually_configured() -> None:
    with _client() as client:
        payload = client.get("/api/designer/health").json()

    assert payload["ok"] is True
    assert payload["route"]["supportsToolCalls"] is True
    assert payload["settings"]["authMode"] == "dev_configured"
    assert payload["upstream"]["commit"] == "8391a94c1c3939c679e40ddd7bfc08a9ef690e70"
    assert payload["upstream"]["license"] == "MIT"


def test_a_turn_returns_the_generated_ui() -> None:
    with _client() as client:
        response = client.post("/api/designer/turn", json={"prompt": "make a form"})
        payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["toolCalled"] is True
    assert payload["ui"]["html"] == "<div id='x'>hi</div>"
    assert payload["ui"]["css"] == ".a{color:red}"
    assert payload["identity"]["tenantId"] == "tenant-a"


def test_a_turn_without_a_prompt_is_refused() -> None:
    with _client() as client:
        response = client.post("/api/designer/turn", json={})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "prompt_required"


def test_the_interaction_state_is_sent_to_the_model_on_a_follow_up_turn() -> None:
    route = _StubRoute()
    with _client(route) as client:
        client.post(
            "/api/designer/turn",
            json={
                "prompt": "raise the total to 5",
                "interaction_state": {"values": {"qty": "3"}},
            },
        )

    assert len(route.requests) == 1
    sent = route.requests[0].user_prompt
    assert "raise the total to 5" in sent
    assert "qty" in sent
    assert "3" in sent


def test_the_sent_context_is_reported_back_to_the_caller() -> None:
    with _client() as client:
        payload = client.post(
            "/api/designer/turn",
            json={"prompt": "next", "interaction_state": {"values": {"qty": "7"}}},
        ).json()

    assert payload["contextSent"] == {"values": {"qty": "7"}, "prompt": None}


def test_a_turn_without_a_tool_call_reports_no_ui() -> None:
    with _client(_StubRoute(tool_called=False)) as client:
        payload = client.post("/api/designer/turn", json={"prompt": "hello"}).json()

    assert payload["toolCalled"] is False
    assert payload["ui"] is None
    assert payload["text"] == "Made it."


def test_the_sandbox_endpoint_serves_the_generated_document() -> None:
    with _client() as client:
        response = client.post(
            "/api/designer/sandbox",
            json={
                "ui": {
                    "html": "<input id='qty'>",
                    "css": ".a{}",
                    "jsFunctions": "function go(){}",
                    "jsExpressions": ["go();"],
                }
            },
        )

    assert response.status_code == 200
    body = response.text
    assert "<!DOCTYPE html>" in body
    assert "function go(){}" in body
    assert "ui_state" in body


def test_a_turn_on_a_route_without_a_tool_channel_is_refused() -> None:
    class _TextRoute(_StubRoute):
        @property
        def supports_tool_calls(self) -> bool:
            return False

    with _client(_TextRoute()) as client:
        response = client.post("/api/designer/turn", json={"prompt": "hello"})

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "model_route_lacks_tool_channel"


def test_the_preview_page_is_served() -> None:
    with _client() as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "PADIEM Designer" in response.text


def test_a_configured_session_secret_requires_a_session_cookie() -> None:
    settings = Settings(
        b14_session_secret="x" * 40,
        dev_tenant_id="tenant-a",
        dev_user_id="user-a",
    )
    with _client(settings=settings) as client:
        response = client.post("/api/designer/turn", json={"prompt": "hello"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "session_required"
