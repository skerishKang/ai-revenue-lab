from __future__ import annotations

import base64

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import HistoryForbidden
from app.main import create_app
from padiem_ai_core.b14_streaming import B14StreamEvent


SESSION_SECRET = "slice19-edge-session-secret-not-a-real-credential-000000"
USER_ID = "usr_" + "a" * 32
CHAT_ID = "chat_" + "b" * 32
PAYLOAD = {
    "messages": [{"role": "user", "content": "안녕하세요"}],
    "mode": "auto",
}


def _google_settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="slice19-edge.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class ScriptedClient:
    def __init__(self, events):
        self.events = list(events)
        self.calls = 0

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        self.calls += 1
        for event in self.events:
            yield event


class ForbiddenHistoryStore:
    def __init__(self):
        self.append_calls = 0

    async def get_conversation(self, user_id, conversation_id):
        if user_id == USER_ID and conversation_id == CHAT_ID:
            return {
                "id": CHAT_ID,
                "project_id": None,
                "messages": [],
            }
        return None

    async def append_exchange(
        self,
        user_id,
        conversation_id,
        user_text,
        assistant_text,
        project_id=None,
    ):
        self.append_calls += 1
        raise HistoryForbidden("ownership changed after stream start")


async def _post(app, payload, *, signed=False):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        if signed:
            client.cookies.set(
                SESSION_COOKIE,
                create_session_token(_google_settings(), USER_ID),
                domain="chat.example.test",
                path="/",
            )
        return await client.post("/api/chat/stream", json=payload)


@pytest.mark.asyncio
async def test_history_forbidden_after_model_done_becomes_sse_error_without_public_done():
    store = ForbiddenHistoryStore()
    app = create_app(_google_settings(), history_store=store)
    app.state.b14_client = ScriptedClient(
        [B14StreamEvent(delta_content="완성 답변"), B14StreamEvent(done=True)]
    )
    app.state.usage_gate_enforced = False

    response = await _post(
        app,
        {**PAYLOAD, "conversation_id": CHAT_ID},
        signed=True,
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: delta") == 1
    assert response.text.count("event: error") == 1
    assert '"code":"conversation_not_found"' in response.text
    assert "event: done" not in response.text
    assert store.append_calls == 1


@pytest.mark.asyncio
async def test_image_attachment_is_rejected_before_stream_dispatch():
    scripted = ScriptedClient(
        [B14StreamEvent(delta_content="should not run"), B14StreamEvent(done=True)]
    )
    app = create_app(Settings(runtime_mode="mock"))
    app.state.b14_client = scripted
    app.state.usage_gate_enforced = False

    png = base64.b64encode(b"\x89PNG\r\n\x1a\nslice19-edge").decode("ascii")
    response = await _post(
        app,
        {
            **PAYLOAD,
            "attachments": [
                {
                    "type": "image",
                    "name": "photo.png",
                    "media_type": "image/png",
                    "base64": png,
                }
            ],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "streaming_unsupported"
    assert scripted.calls == 0


@pytest.mark.asyncio
async def test_mock_public_stream_never_calls_injected_transport():
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(500, content=b"should never be reached")

    app = create_app(
        Settings(runtime_mode="mock"),
        transport=httpx.MockTransport(handler),
    )
    response = await _post(app, PAYLOAD)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-store"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: delta" in response.text
    assert response.text.count("event: done") == 1
    assert calls == 0
