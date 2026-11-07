"""End-to-end connector turn regressions through the real Chat stream route.

The three production failures this file guards against were:
* #7128: the intent classifier saw only the word "구글";
* #7135: the tool declaration failed JSON serialization at B14 dispatch;
* #7124: the route gate withheld native tools.

Only three boundaries are fake: the B14 HTTP gateway, the Engine tool execute
boundary (its Google HTTP call uses ``httpx.MockTransport``), and the reviewed
connector grant.  The real app route, intent classifier, grant gate, tool
declaration, ``B14ChatRequest.to_payload`` JSON bytes, tool loop and journals
run unchanged.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from starlette.testclient import TestClient

from app import chat_connector_tools as connector_tools
from app import native_calendar_adapter
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import B14Client
from app.calendar_store import InMemoryCalendarStore
from app.model_policy import MAX_HOLD_MODEL_ID
from test_b54_claw_general_p01_routing import SIGNED_IN_USER_ID, _settings

CONNECTED = ("connected", None)
NOT_CONNECTED = ("not_connected", None)
CALENDAR_TITLE = "디자인 리뷰"
DRIVE_FILE = "2026년 견적서.pdf"
CALENDAR_QUESTION = "내일 일정 뭐야"
DRIVE_QUESTION = "드라이브에서 견적서 찾아줘"
GENERAL_CALENDAR_QUESTION = "이번 주 회의 몇 개야"
CREATE_QUESTION = "내일 오전 9시 회의 일정 등록해줘"


class _History:
    async def get_conversation(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def append_exchange(self, *args: Any, **kwargs: Any) -> str:
        return "chat_" + "e" * 32


class _MaxCatalog:
    """The normalized B14 catalog row the #7124 route gate reads."""

    async def list_registered_models(self) -> list[dict[str, Any]]:
        return [
            {
                "model_id": MAX_HOLD_MODEL_ID,
                "capabilities": ["chat", "tools"],
                "b14_enabled": True,
                "owner_excluded": False,
            }
        ]


class _MaxMemberStore:
    """The verified member access the max-tier request needs."""

    async def runtime_access(self, _user_id: str) -> dict[str, str]:
        return {"status": "approved", "tier": "max"}

    async def is_google_admin(self, _user_id: str) -> bool:
        return False


class _ShadowProjection:
    auth_session_id = "authsession:test"


class _ShadowStore:
    async def load_projection(self, _user_id: str) -> _ShadowProjection:
        return _ShadowProjection()


class _ConnectorWorkspaceAuthority:
    async def resolve_connector_workspace(self, *, session_id: str) -> str:
        assert session_id == "authsession:test"
        return "workspace:e2e"


class _DriveGroundingEngine:
    """The existing Drive preflight's Engine boundary; it finds nothing.

    The connector READ tool under test is a different, already-granted path;
    the preflight only needs to be observable rather than unavailable.
    """

    async def general_search(self, *, workspace_ref: str, query: str) -> dict[str, list]:
        assert workspace_ref == "workspace:e2e"
        assert query
        return {"files": []}


class _B14Gateway:
    """Fake B14 stream gateway; records the real JSON request bytes."""

    def __init__(
        self,
        *,
        tool_name: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        answer: str = "일반 경로로 답변했습니다.",
        expected_context_title: str | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.tool_arguments = tool_arguments or {}
        self.answer = answer
        self.expected_context_title = expected_context_title
        self.raw_requests: list[bytes] = []
        self.requests: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        raw = request.content
        body = json.loads(raw)
        self.raw_requests.append(raw)
        self.requests.append(body)
        if self.tool_name is not None and body.get("tools"):
            names = [tool["function"]["name"] for tool in body["tools"]]
            assert names == [self.tool_name], names
            tool_call = json.dumps(
                {
                    "id": "call_e2e",
                    "name": self.tool_name,
                    "arguments": json.dumps(self.tool_arguments, ensure_ascii=False),
                    "index": 0,
                },
                ensure_ascii=False,
            ).encode("utf-8")
            return _sse(
                b"event: tool_call\ndata: " + tool_call + b"\n\n"
                b'event: done\ndata: {"finish_reason":"tool_calls"}\n\n'
            )
        if self.expected_context_title is not None:
            wire = json.dumps(body, ensure_ascii=False)
            assert self.expected_context_title in wire, wire
        return _sse(_content_frame(self.answer))


def _sse(body: bytes) -> httpx.Response:
    return httpx.Response(
        200, content=body, headers={"content-type": "text/event-stream"}
    )


def _content_frame(text: str) -> bytes:
    payload = {
        "id": "b14_e2e",
        "object": "chat.completion.chunk",
        "model": MAX_HOLD_MODEL_ID,
        "choices": [
            {"index": 0, "delta": {"content": text}, "finish_reason": None}
        ],
        "business14": {
            "request_id": "b14_e2e",
            "route_mode": "manual",
            "selected_provider": "Repro Provider",
            "selected_model": MAX_HOLD_MODEL_ID,
            "fallback_used": False,
        },
    }
    return b"data: " + json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n\ndata: [DONE]\n\n"


class _GoogleToolEngine:
    """The Engine execute boundary, with a real httpx Google API mock inside."""

    def __init__(self, *, calendar_title: str = CALENDAR_TITLE, drive_file: str = DRIVE_FILE):
        self.calendar_title = calendar_title
        self.drive_file = drive_file
        self.calls: list[dict[str, Any]] = []
        self.google_urls: list[str] = []

    def _google(self, request: httpx.Request) -> httpx.Response:
        self.google_urls.append(str(request.url))
        if "/calendar/v3/" in str(request.url):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "summary": self.calendar_title,
                            "start": {"dateTime": "2026-11-09T10:00:00+09:00"},
                        }
                    ]
                },
            )
        if "/drive/v3/" in str(request.url):
            return httpx.Response(200, json={"files": [{"name": self.drive_file}]})
        raise AssertionError(str(request.url))

    async def execute(self, *, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"tool_name": tool_name, "arguments": dict(arguments)})
        transport = httpx.MockTransport(self._google)
        async with httpx.AsyncClient(transport=transport) as client:
            if tool_name == "calendar_read":
                response = await client.get(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                    params={
                        "timeMin": arguments["timeMin"],
                        "timeMax": arguments["timeMax"],
                    },
                )
                return {"status": "completed", "output": {"events": response.json()["items"]}}
            if tool_name == "drive_read":
                response = await client.get(
                    "https://www.googleapis.com/drive/v3/files",
                    params={"q": "name contains '" + str(arguments.get("query", "")) + "'"},
                )
                return {"status": "completed", "output": {"files": response.json()["files"]}}
        raise AssertionError(tool_name)


def _patch_grant(monkeypatch: pytest.MonkeyPatch, *, drive: bool, calendar: bool) -> None:
    async def truth(_request: Any):
        overrides = {
            "drive": CONNECTED if drive else NOT_CONNECTED,
            "calendar": CONNECTED if calendar else NOT_CONNECTED,
        }
        return overrides, "canonical_workspace_connector_not_reported", True, "authsession:test"

    async def calendar_state(_request: Any, _session_id: str):
        return "active" if calendar else "inactive"

    monkeypatch.setattr(connector_tools, "_reviewed_workspace_truth", truth)
    monkeypatch.setattr(connector_tools, "_reviewed_calendar_read_grant_state", calendar_state)
    connector_tools.invalidate_connector_tool_grant_cache()


@contextmanager
def _client(gateway: _B14Gateway, engine: _GoogleToolEngine):
    settings = _settings(runtime_mode="b14", b14_base_url="https://b14.test")
    app = create_app(
        settings=settings,
        history_store=_History(),
        calendar_store=InMemoryCalendarStore(),
    )
    app.state.b14_client = B14Client(
        settings, stream_transport=httpx.MockTransport(gateway.handle)
    )
    app.state.b14_model_choice_resolver = _MaxCatalog()
    app.state.b66_member_admin_store = _MaxMemberStore()
    app.state.connector_tool_engine_client = engine
    app.state.identity_shadow_store = _ShadowStore()
    app.state.control_plane_identity_authority = _ConnectorWorkspaceAuthority()
    app.state.drive_case_folder_engine_client = _DriveGroundingEngine()
    app.state.usage_gate_enforced = False
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _post(client: TestClient, text: str, *, tier: str = "max", **extra: Any):
    payload = {
        "messages": [{"role": "user", "content": text}],
        "tier": tier,
        "timezone": "Asia/Seoul",
        **extra,
    }
    return client.post("/api/chat/stream", json=payload)


def _journal_lines(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_a_max_calendar_turn_declares_serializes_executes_and_answers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_grant(monkeypatch, drive=False, calendar=True)
    gateway = _B14Gateway(
        tool_name="calendar_read",
        tool_arguments={
            "calendarId": "primary",
            "timeMin": "2026-11-09T00:00:00+09:00",
            "timeMax": "2026-11-10T00:00:00+09:00",
        },
        answer=f"연결된 캘린더에서 '{CALENDAR_TITLE}' 일정을 확인했습니다.",
        expected_context_title=CALENDAR_TITLE,
    )
    engine = _GoogleToolEngine()

    with _client(gateway, engine) as client:
        response = _post(client, CALENDAR_QUESTION)

    assert response.status_code == 200, response.text
    assert "event: done" in response.text
    assert CALENDAR_TITLE in response.text

    assert len(gateway.requests) == 2, gateway.requests
    first = gateway.requests[0]
    assert first["tool_choice"] == "auto"
    assert [tool["function"]["name"] for tool in first["tools"]] == ["calendar_read"]
    parameters = first["tools"][0]["function"]["parameters"]
    assert parameters["required"] == ["calendarId", "timeMin", "timeMax"]
    # Actual serialized request bytes, not only the in-memory object: this is
    # the #7135 mappingproxy/JSON boundary.
    assert b"calendar_read" in gateway.raw_requests[0]
    assert b'"tool_choice":"auto"' in gateway.raw_requests[0].replace(b" ", b"")

    second = gateway.requests[1]
    assert "tools" not in second
    assert CALENDAR_TITLE in json.dumps(second, ensure_ascii=False)
    assert engine.calls == [
        {
            "tool_name": "calendar_read",
            "arguments": {
                "calendarId": "primary",
                "timeMin": "2026-11-09T00:00:00+09:00",
                "timeMax": "2026-11-10T00:00:00+09:00",
            },
        }
    ]
    assert engine.google_urls and "calendar/v3" in engine.google_urls[0]

    journal = _journal_lines(capsys)
    assert "connector_tools declared=1 reason=granted" in journal
    assert "connector_tools execute tool=calendar_read items=1" in journal
    assert CALENDAR_TITLE not in journal


def test_a_drive_grant_declares_the_drive_tool_and_returns_the_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_grant(monkeypatch, drive=True, calendar=False)
    gateway = _B14Gateway(
        tool_name="drive_read",
        tool_arguments={"query": "견적서"},
        answer=f"드라이브에서 '{DRIVE_FILE}'를 찾았습니다.",
        expected_context_title=DRIVE_FILE,
    )
    engine = _GoogleToolEngine()

    with _client(gateway, engine) as client:
        response = _post(client, DRIVE_QUESTION)

    assert response.status_code == 200, response.text
    assert DRIVE_FILE in response.text
    assert [tool["function"]["name"] for tool in gateway.requests[0]["tools"]] == [
        "drive_read"
    ]
    assert "tools" not in gateway.requests[1]
    assert DRIVE_FILE in json.dumps(gateway.requests[1], ensure_ascii=False)
    assert engine.calls[0]["tool_name"] == "drive_read"
    assert engine.google_urls and "drive/v3" in engine.google_urls[0]

    journal = _journal_lines(capsys)
    assert "connector_tools declared=1 reason=granted" in journal
    assert "connector_tools execute tool=drive_read items=1" in journal
    assert DRIVE_FILE not in journal


def test_an_unconnected_owner_gets_no_connector_tools(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_grant(monkeypatch, drive=False, calendar=False)
    gateway = _B14Gateway(answer="일반 경로로 답변했습니다.")
    engine = _GoogleToolEngine()

    with _client(gateway, engine) as client:
        response = _post(client, GENERAL_CALENDAR_QUESTION)

    assert response.status_code == 200, response.text
    assert "일반 경로로 답변했습니다." in response.text
    assert gateway.requests
    assert "tools" not in gateway.requests[0]
    assert "tool_choice" not in gateway.requests[0]
    assert engine.calls == []
    journal = _journal_lines(capsys)
    assert "connector_tools execute" not in journal


def test_the_same_calendar_ask_without_a_grant_stays_on_the_general_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact released regression ask, with the native lane held out.

    ``util=meeting`` is an existing request scope: it keeps the native
    calendar branch out of the way so this test observes the general B14
    request.  The point under test is that an unconnected owner's declaration
    list is empty and no connector tool reaches the Engine.
    """

    _patch_grant(monkeypatch, drive=False, calendar=False)
    gateway = _B14Gateway(answer="일반 경로로 답변했습니다.")
    engine = _GoogleToolEngine()

    with _client(gateway, engine) as client:
        response = _post(client, CALENDAR_QUESTION, util="meeting")

    assert response.status_code == 200, response.text
    assert "일반 경로로 답변했습니다." in response.text
    assert "tools" not in gateway.requests[0]
    assert "tool_choice" not in gateway.requests[0]
    assert engine.calls == []


def test_a_create_ask_stays_on_the_native_calendar_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_grant(monkeypatch, drive=False, calendar=True)

    async def workspace(_request: Any, _uid: str) -> str:
        return "workspace:e2e"

    monkeypatch.setattr(native_calendar_adapter, "_resolve_memory_workspace", workspace)
    gateway = _B14Gateway(tool_name="calendar_read", answer="B14가 답하면 안 됩니다.")
    engine = _GoogleToolEngine()

    with _client(gateway, engine) as client:
        response = _post(client, CREATE_QUESTION)

    assert response.status_code == 200, response.text
    assert "네이티브 일정이 등록되었습니다" in response.text
    assert gateway.requests == []
    assert engine.calls == []
