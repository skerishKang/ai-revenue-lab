from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import StreamingResponse

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.b14_streaming import B14StreamEvent

import app.chat_pc_drive as chat_pc_drive
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import ChatRuntimeError, ChatStreamEvent, ChatToolCall
from app.config import Settings
from app.history import ProjectProfile
from app.main import api_chat_stream, create_app
from app.usage_gate import UsageDecision


SESSION_SECRET = "slice18-session-secret-not-a-real-credential-000000"
CHAT_ID = "chat_" + "1" * 32
PROJECT_ID = "proj_" + "2" * 32
OTHER_PROJECT_ID = "proj_" + "3" * 32
USER_ID = "usr_" + "4" * 32


def _payload(**extra):
    value = {
        "messages": [{"role": "user", "content": "스트리밍으로 답해 주세요"}],
        "mode": "auto",
    }
    value.update(extra)
    return value


def _google_settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="slice18-client.apps.googleusercontent.com",
        google_client_secret="slice18-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def _event(
    content: str | None = None,
    *,
    done: bool = False,
    provider: str = "SECRET_PROVIDER",
    model: str = "secret/free-model",
) -> B14StreamEvent:
    route = B14RouteMetadata(
        route_mode="auto",
        selected_provider=provider,
        selected_model=model,
        selected_upstream_model=model,
        selected_route_id=f"secret:{model}",
        fallback_used=True,
        attempt_count=2,
    )
    return B14StreamEvent(
        model=model,
        delta_content=content,
        route=route,
        done=done,
    )


class ScriptedClient:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "skill": skill,
                "additional_system_context": additional_system_context,
            }
        )
        for item in self.script:
            if isinstance(item, BaseException):
                raise item
            yield item


class BlockingClient:
    def __init__(self):
        self.calls = 0
        self.closed = False
        self.second_requested = False

    async def stream_text_auto(self, messages, *, skill=None, additional_system_context=None):
        self.calls += 1
        try:
            yield _event("첫 토큰")
            self.second_requested = True
            await asyncio.Event().wait()
        finally:
            self.closed = True


class ToolScriptedClient:
    """Records the exact keyword shape the route sent to the B14 client."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    async def stream_text_auto(self, messages, **kwargs):
        self.calls.append(
            {"messages": [dict(item) for item in messages], **kwargs}
        )
        for item in self.script:
            if isinstance(item, BaseException):
                raise item
            yield item


class FakeCatalog:
    def __init__(self, rows):
        self.rows = list(rows)

    async def list_registered_models(self):
        return list(self.rows)


FREE_B14_MODEL_ID = "google/gemini-3.1-flash-lite"


def _catalog_row(*capabilities: str):
    return {
        "model_id": FREE_B14_MODEL_ID,
        "capabilities": list(capabilities),
        "b14_enabled": True,
        "owner_excluded": False,
    }


class MemoryHistoryStore:
    def __init__(self, *, project: ProjectProfile | None = None, conversation_project_id: str | None = None):
        self.project = project
        self.conversation_project_id = conversation_project_id
        self.append_calls: list[dict] = []

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        if conversation_id != CHAT_ID:
            return None
        return {
            "id": CHAT_ID,
            "project_id": self.conversation_project_id,
            "messages": [],
        }

    async def get_project(self, user_id, project_id):
        if self.project is None or project_id != self.project.id:
            return None
        return self.project

    async def append_exchange(
        self,
        user_id,
        conversation_id,
        user_text,
        assistant_text,
        project_id=None,
        *,
        product_scope,
    ):
        self.append_calls.append(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "project_id": project_id,
            }
        )
        return conversation_id or CHAT_ID


@dataclass(frozen=True)
class ProjectFile:
    name: str
    media_type: str
    content_text: str


class MemoryProjectFileStore:
    def __init__(self, files):
        self.files = list(files)
        self.calls = []

    async def list_files(self, user_id, project_id):
        self.calls.append((user_id, project_id))
        return list(self.files)


class DenyUsageGate:
    async def authorize(self, *, raw_ip, user_id):
        return UsageDecision(
            allowed=False,
            code="rate_limited",
            status_code=429,
            user_message="요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
            retry_after_seconds=37,
        )


async def _post(app, payload, *, settings: Settings | None = None, signed_in: bool = False):
    base_url = "https://chat.example.test" if signed_in else "http://test"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=base_url,
    ) as client:
        if signed_in:
            resolved = settings or _google_settings()
            client.cookies.set(
                SESSION_COOKIE,
                create_session_token(resolved, USER_ID),
                domain="chat.example.test",
                path="/",
            )
        return await client.post("/api/chat/stream", json=payload)


def _app_with_client(
    client,
    *,
    settings: Settings | None = None,
    history_store=None,
    project_file_store=None,
):
    app = create_app(
        settings or Settings(runtime_mode="mock"),
        history_store=history_store,
        project_file_store=project_file_store,
    )
    app.state.b14_client = client
    app.state.usage_gate_enforced = False
    return app


def test_existing_api_chat_remains_completed_json_and_new_route_is_separate():
    app = create_app(Settings(runtime_mode="mock"))

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            completed = await client.post("/api/chat", json=_payload())
            streamed = await client.post("/api/chat/stream", json=_payload())
        assert completed.status_code == 200
        assert completed.headers["content-type"].startswith("application/json")
        assert isinstance(completed.json()["answer"], str)
        assert streamed.status_code == 200
        assert streamed.headers["content-type"].startswith("text/event-stream")

    asyncio.run(scenario())


def test_public_stream_emits_bounded_delta_and_done_without_route_metadata():
    client = ScriptedClient([_event("첫째"), _event("둘째"), _event(done=True)])
    app = _app_with_client(client)
    response = asyncio.run(_post(app, _payload()))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count("event: delta") == 2
    assert 'data: {"delta":"첫째"}' in response.text
    assert 'data: {"delta":"둘째"}' in response.text
    assert response.text.count("event: done") == 1
    assert 'data: {"done":true}' in response.text
    assert "SECRET_PROVIDER" not in response.text
    assert "secret/free-model" not in response.text
    assert "selected_provider" not in response.text
    assert "selected_model" not in response.text
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ChatRuntimeError(503, "upstream_busy", "지금 사용자가 많습니다."), 503, "upstream_busy"),
        (ChatRuntimeError(502, "upstream_error", "답변을 불러오지 못했습니다."), 502, "upstream_error"),
        (ChatRuntimeError(504, "upstream_timeout", "답변 준비가 오래 걸리고 있습니다."), 504, "upstream_timeout"),
    ],
)
def test_pre_start_runtime_error_stays_json_before_sse(error, status, code):
    client = ScriptedClient([error])
    app = _app_with_client(client)
    response = asyncio.run(_post(app, _payload()))

    assert response.status_code == status
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == code
    assert "event:" not in response.text


def test_done_before_visible_content_is_json_502_not_empty_sse_200():
    client = ScriptedClient([_event(done=True)])
    app = _app_with_client(client)
    response = asyncio.run(_post(app, _payload()))

    assert response.status_code == 502
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "empty_upstream_answer"


def test_post_start_error_emits_one_bounded_error_no_done_and_writes_no_history():
    settings = _google_settings()
    store = MemoryHistoryStore()
    client = ScriptedClient(
        [
            _event("부분 답변"),
            ChatRuntimeError(503, "upstream_busy", "지금 사용자가 많습니다. 잠시 후 다시 시도해 주세요."),
        ]
    )
    app = _app_with_client(client, settings=settings, history_store=store)
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert response.text.count("event: delta") == 1
    assert response.text.count("event: error") == 1
    assert '"code":"upstream_busy"' in response.text
    assert "event: done" not in response.text
    assert store.append_calls == []


def test_stream_end_without_done_emits_malformed_error_and_no_fake_done():
    client = ScriptedClient([_event("부분")])
    app = _app_with_client(client)
    response = asyncio.run(_post(app, _payload()))

    assert response.status_code == 200
    assert "event: delta" in response.text
    assert response.text.count("event: error") == 1
    assert '"code":"malformed_upstream"' in response.text
    assert "event: done" not in response.text


@pytest.mark.parametrize(
    "extra",
    [
        {"tool": "web_search"},
        {
            "attachments": [
                {
                    "type": "document",
                    "name": "notes.txt",
                    "media_type": "text/plain",
                    "text": "streaming attachment should stay on completed JSON path",
                }
            ]
        },
    ],
)
def test_tools_and_attachments_are_rejected_before_stream_dispatch(extra):
    client = ScriptedClient([_event("should not run"), _event(done=True)])
    app = _app_with_client(client)
    response = asyncio.run(_post(app, _payload(**extra)))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "streaming_unsupported"
    assert client.calls == []


def test_quota_denial_is_json_with_retry_after_and_zero_b14_dispatch():
    client = ScriptedClient([_event("should not run"), _event(done=True)])
    app = _app_with_client(client)
    app.state.usage_gate_enforced = True
    app.state.usage_gate = DenyUsageGate()

    response = asyncio.run(_post(app, _payload()))

    assert response.status_code == 429
    assert response.headers["retry-after"] == "37"
    assert response.json()["error"]["code"] == "rate_limited"
    assert client.calls == []


def test_signed_in_success_persists_once_only_after_successful_done():
    settings = _google_settings()
    store = MemoryHistoryStore()
    client = ScriptedClient([_event("완성 "), _event("답변"), _event(done=True)])
    app = _app_with_client(client, settings=settings, history_store=store)
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert response.text.count("event: done") == 1
    assert f'"conversation_id":"{CHAT_ID}"' in response.text
    assert len(store.append_calls) == 1
    saved = store.append_calls[0]
    assert saved["user_id"] == USER_ID
    assert saved["assistant_text"] == "완성 답변"
    assert saved["user_text"] == "스트리밍으로 답해 주세요"
    assert saved["project_id"] is None


def test_project_context_and_project_files_reach_auto_stream_and_done_metadata():
    settings = _google_settings()
    project = ProjectProfile(
        id=PROJECT_ID,
        name="시장조사",
        instructions="항상 한국어로 핵심 근거를 먼저 제시하세요.",
        created_at="2026-08-27T00:00:00Z",
        updated_at="2026-08-27T00:00:00Z",
    )
    store = MemoryHistoryStore(project=project)
    files = MemoryProjectFileStore(
        [ProjectFile("brief.txt", "text/plain", "프로젝트 파일의 핵심 수치 12345")]
    )
    client = ScriptedClient([_event("프로젝트 답변"), _event(done=True)])
    app = _app_with_client(
        client,
        settings=settings,
        history_store=store,
        project_file_store=files,
    )
    response = asyncio.run(
        _post(
            app,
            _payload(project_id=PROJECT_ID),
            settings=settings,
            signed_in=True,
        )
    )

    assert response.status_code == 200
    assert len(client.calls) == 1
    context = client.calls[0]["additional_system_context"]
    assert "시장조사" in context
    assert "항상 한국어로 핵심 근거를 먼저 제시하세요." in context
    assert "brief.txt" in context
    assert "12345" in context
    assert f'"project_id":"{PROJECT_ID}"' in response.text
    assert '"project":{"id":"' + PROJECT_ID + '","name":"시장조사"}' in response.text
    assert '"project_files_used":1' in response.text
    assert store.append_calls[0]["project_id"] == PROJECT_ID
    assert files.calls == [(USER_ID, PROJECT_ID)]


def test_conversation_project_mismatch_is_rejected_before_model_dispatch():
    settings = _google_settings()
    project = ProjectProfile(
        id=PROJECT_ID,
        name="A",
        instructions="",
        created_at="2026-08-27T00:00:00Z",
        updated_at="2026-08-27T00:00:00Z",
    )
    store = MemoryHistoryStore(project=project, conversation_project_id=PROJECT_ID)
    client = ScriptedClient([_event("should not run"), _event(done=True)])
    app = _app_with_client(client, settings=settings, history_store=store)
    response = asyncio.run(
        _post(
            app,
            _payload(conversation_id=CHAT_ID, project_id=OTHER_PROJECT_ID),
            settings=settings,
            signed_in=True,
        )
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
    assert client.calls == []


def _tool_lane_app(client, *, rows, monkeypatch, pc_verified: bool):
    settings = _google_settings()
    app = _app_with_client(
        client, settings=settings, history_store=MemoryHistoryStore(),
    )
    app.state.b14_catalog_source = FakeCatalog(rows)

    async def _available(request, *, uid):
        return pc_verified

    monkeypatch.setattr(chat_pc_drive, "chat_pc_tools_available", _available)
    return app, settings


def test_verified_pc_on_a_tools_route_declares_the_closed_pc_tool_set(monkeypatch):
    client = ToolScriptedClient([_event("보통 답변"), _event(done=True)])
    app, settings = _tool_lane_app(
        client,
        rows=[_catalog_row("chat", "tools")],
        monkeypatch=monkeypatch,
        pc_verified=True,
    )

    async def _no_lane(*args, **kwargs):
        pytest.fail("an ordinary answer must not enter the PC lane")

    monkeypatch.setattr(chat_pc_drive, "execute_chat_pc_drive_lane", _no_lane)
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert '"delta":"보통 답변"' in response.text
    assert len(client.calls) == 1
    sent = client.calls[0]
    assert [tool.name for tool in sent["tools"]] == [
        "query_drives", "files_list", "files",
    ]
    assert sent["tool_choice"] == "auto"


def test_route_without_tools_capability_keeps_the_pre_slice_request(monkeypatch):
    client = ToolScriptedClient([_event("답변"), _event(done=True)])
    app, settings = _tool_lane_app(
        client,
        rows=[_catalog_row("chat")],
        monkeypatch=monkeypatch,
        pc_verified=True,
    )
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert "tools" not in client.calls[0]
    assert "tool_choice" not in client.calls[0]


def test_unverified_pc_withholds_the_tool_definitions(monkeypatch):
    client = ToolScriptedClient([_event("답변"), _event(done=True)])
    app, settings = _tool_lane_app(
        client,
        rows=[_catalog_row("chat", "tools")],
        monkeypatch=monkeypatch,
        pc_verified=False,
    )
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert "tools" not in client.calls[0]
    assert "tool_choice" not in client.calls[0]


def test_model_tool_call_hands_the_turn_to_the_pc_lane(monkeypatch):
    client = ToolScriptedClient([
        ChatStreamEvent(
            tool_call=ChatToolCall(
                id="call_1", name="files_list", arguments={},
            ),
        ),
        _event(done=True),
    ])
    app, settings = _tool_lane_app(
        client,
        rows=[_catalog_row("chat", "tools")],
        monkeypatch=monkeypatch,
        pc_verified=True,
    )
    recorded: dict = {}

    async def _lane(request, **kwargs):
        recorded.update(kwargs)
        return ("내 PC의 폴더 목록입니다", CHAT_ID)

    monkeypatch.setattr(chat_pc_drive, "execute_chat_pc_drive_lane", _lane)
    response = asyncio.run(_post(app, _payload(), settings=settings, signed_in=True))

    assert response.status_code == 200
    assert 'data: {"delta":"내 PC의 폴더 목록입니다"}' in response.text
    assert '"conversation_id":"' + CHAT_ID + '"' in response.text
    assert recorded["selected_tool"] == "files_list"
    assert recorded["declared_plan"] == chat_pc_drive.chat_pc_plan_for_tool(
        "files_list"
    )
    assert [
        step["step_id"] for step in recorded["declared_plan"]["steps"]
    ] == ["list_files"]
    assert all(
        step["tool_id"] != "claw.pc.read_file"
        for step in recorded["declared_plan"]["steps"]
    )
    assert "도구 앞의 텍스트" not in response.text


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_catalog_row("chat", "tools"), True),
        (_catalog_row("chat"), False),
        ({**_catalog_row("chat", "tools"), "b14_enabled": False}, False),
        ({**_catalog_row("chat", "tools"), "owner_excluded": True}, False),
        ({**_catalog_row("chat", "tools"), "model_id": "other/model"}, False),
    ],
)
def test_route_tools_capability_is_catalog_authoritative(row, expected):
    from app.chat_routes import _route_declares_tools

    async def scenario():
        app = SimpleNamespace(
            state=SimpleNamespace(b14_catalog_source=FakeCatalog([row])),
        )
        request = SimpleNamespace(app=app)
        return await _route_declares_tools(request, FREE_B14_MODEL_ID)

    assert asyncio.run(scenario()) is expected


def test_public_route_returns_after_first_visible_token_and_consumer_close_closes_b62_stream():
    async def scenario():
        client = BlockingClient()
        app = _app_with_client(client)
        body = json.dumps(_payload(), ensure_ascii=False).encode("utf-8")
        delivered = False

        async def receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/chat/stream",
            "raw_path": b"/api/chat/stream",
            "query_string": b"",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("test", 80),
            "app": app,
        }
        request = Request(scope, receive)

        response = await asyncio.wait_for(api_chat_stream(request), timeout=0.2)
        assert isinstance(response, StreamingResponse)
        assert client.calls == 1
        assert client.second_requested is False

        iterator = response.body_iterator
        first_chunk = await asyncio.wait_for(anext(iterator), timeout=0.2)
        assert b"event: delta" in first_chunk
        assert "첫 토큰".encode("utf-8") in first_chunk
        assert client.second_requested is False

        await iterator.aclose()
        assert client.closed is True

    asyncio.run(scenario())
