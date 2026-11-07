"""Connector-intent turns reach the connector tool lane, not the search lane.

Production measurement after the connector READ tools landed (#7096): the
owner's "이번 주 구글 캘린더 일정 알려줘" and "구글 드라이브에서 최근 파일
찾아줘" both ran on POST /api/orchestration and were answered by the web
search grounding — the browser sends every signed-in, orchestration-ready
turn to the orchestration lane first, so the connector tools declared on the
main chat turn were never reached.

These regressions pin the fixed routing:

* an explicit Google name, or a broad calendar/drive read intent whose named
  service is granted, is handed back to the main chat turn (409
  ``orchestration_not_applicable``, the code the transport already falls back
  on), where the same bounded grant check declares the tools;
* a grant-less or unverified owner keeps the orchestration search path
  byte-for-byte: the check answers False without widening anything;
* without its own service grant, "일정" stays with the workspace-native
  calendar and "드라이브" stays with the PC lane — the broad rules are
  connection-gated.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from app import chat_connector_tools as tools_module
from app import orchestration_routes as routes

OWNER = "usr_" + "b" * 32
CALENDAR_QUESTION = "이번 주 구글 캘린더 일정 알려줘"
DRIVE_QUESTION = "구글 드라이브에서 최근 파일 찾아줘"
SEARCH_QUESTION = "오늘 Meta의 최신 실적을 웹에서 확인해 줘"

CONNECTED = ("connected", None)
_NOT_CONNECTED = ("not_connected", None)

TESTS = Path(__file__).parent
STATIC = TESTS.parent / "static"


def _patch_truth(monkeypatch, *, overrides, authority, calendar_state=None):
    async def _reviewed_workspace_truth(request):
        return overrides, "canonical_workspace_connector_not_reported", authority, "authsession:test"

    async def _reviewed_calendar_state(request, sid):
        return calendar_state

    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _reviewed_workspace_truth)
    monkeypatch.setattr(tools_module, "_reviewed_calendar_read_grant_state", _reviewed_calendar_state)


@pytest.fixture(autouse=True)
def _clean_cache():
    tools_module.invalidate_connector_tool_grant_cache()
    yield
    tools_module.invalidate_connector_tool_grant_cache()


def test_calendar_ask_words_and_explicit_google_naming_route_between_lanes():
    assert tools_module.google_connector_intent(CALENDAR_QUESTION) is True
    assert tools_module.google_connector_intent(DRIVE_QUESTION) is True
    assert tools_module.google_connector_intent("google drive에서 찾아줘") is True
    assert tools_module.google_connector_intent("Google Calendar events please") is True
    # #7088: Gmail joins the same explicit-naming rule.
    assert tools_module.google_connector_intent("지메일에서 중요 메일 검색해줘") is True
    assert tools_module.google_connector_intent("gmail 읽어줘") is True
    assert tools_module.google_connector_intent("구글 메일 확인해줘") is True
    # #7128: calendar ask words WITHOUT explicit Google naming are broad
    # intent, promoted only when the calendar grant is connected (owner
    # 2026-11-08: granted users' "내일 일정 뭐야" must reach Google Calendar).
    assert tools_module.google_connector_intent("내일 일정 뭐야") is False
    assert tools_module.google_connector_broad_intent("내일 일정 뭐야") == "calendar"
    assert tools_module.google_connector_broad_intent("오늘 일정 알려줘") == "calendar"
    assert tools_module.google_connector_broad_intent("이번 주 스케줄 알려줘") == "calendar"
    # The PC lane and Gmail keep their own rules: Gmail stays explicit-only,
    # bare drive/file words stay with the PC lane.
    assert tools_module.google_connector_broad_intent("지메일 확인해줘") is None
    assert tools_module.google_connector_intent("드라이브 목록 보여줘") is False
    assert tools_module.google_connector_intent("메일 확인해줘") is False
    assert tools_module.google_connector_intent("") is False
    assert tools_module.google_connector_intent(None) is False


@pytest.mark.asyncio
async def test_the_fallback_guard_answers_true_only_for_a_granted_owner(monkeypatch, caplog):
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    with caplog.at_level("INFO", logger="padiem_chat.connector_tools"):
        granted = await tools_module.connector_tools_granted_for_fallback(
            SimpleNamespace(), uid="u1",
        )
    assert granted is True
    assert any("orchestration_fallback=True" in record.message for record in caplog.records)

    _patch_truth(monkeypatch, overrides={}, authority=False)
    tools_module.invalidate_connector_tool_grant_cache()
    with caplog.at_level("INFO", logger="padiem_chat.connector_tools"):
        granted = await tools_module.connector_tools_granted_for_fallback(
            SimpleNamespace(), uid="u1",
        )
    assert granted is False
    assert any("orchestration_fallback=False" in record.message for record in caplog.records)


class _RecordingBridge:
    """Records whether the turn reached the Engine search lane."""

    def __init__(self) -> None:
        self.requests: list[dict] = []

    async def start(self, **fields):
        self.requests.append({"user_text": fields.get("user_text")})
        return SimpleNamespace(
            orchestration={"status": "completed"},
            answer="웹에서 확인했습니다.",
            decision_status="completed",
            user_text=fields.get("user_text"),
            conversation_id="chat_" + "c" * 32,
        )


class _History:
    async def get_conversation(self, user_id, conversation_id):
        return None

    async def append_exchange(self, *args, **kwargs):
        return "chat_" + "s" * 32


class _NoGrounding:
    async def prepare(self, messages, *, skill, additional_system_context=None,
                      explicit_search=False, util_scope=None):
        return SimpleNamespace(prepared=None)


def _install(monkeypatch) -> _RecordingBridge:
    bridge = _RecordingBridge()
    monkeypatch.setattr(routes, "_bridge", lambda request: bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: OWNER)
    return bridge


def _request(payload: dict) -> Request:
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/orchestration",
        "headers": [(b"content-type", b"application/json")],
    })
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=bridge,
            history_store=_History(),
            usage_gate_enforced=False,
            usage_gate=None,
            b66_member_admin_store=SimpleNamespace(is_admin=False, runtime_access=None),
            settings=SimpleNamespace(runtime_mode="mock"),
            auto_grounding=_NoGrounding(),
        )
    )
    request._body = json.dumps(payload).encode("utf-8")
    return request


def _payload(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}]}


bridge = None


@pytest.mark.asyncio
async def test_a_granted_calendar_question_hands_back_to_the_main_turn(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await routes.api_orchestration(_request(_payload(CALENDAR_QUESTION)))

    assert response.status_code == 409
    body = json.loads(response.body)
    assert body["error"]["code"] == "orchestration_not_applicable"
    # The search lane never ran for this turn.
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_a_granted_drive_question_hands_back_to_the_main_turn(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await routes.api_orchestration(_request(_payload(DRIVE_QUESTION)))

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_a_granted_calendar_ask_hands_back_to_the_main_turn(monkeypatch):
    """Granted 사용자의 '내일 일정 뭐야'가 커넥터 경로로 간다(도구 선언 전제)."""
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await routes.api_orchestration(_request(_payload("내일 일정 뭐야")))

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    assert bridge.requests == []
    # The same promotion drives the main turn's declaration decision.
    assert await tools_module.google_connector_turn_for_text(
        SimpleNamespace(), uid="u1", user_text="내일 일정 뭐야",
    ) is True


def test_the_unavailable_note_states_the_miss_without_inventing():
    note = tools_module.CONNECTOR_UNAVAILABLE_NOTE
    assert "실제로 읽지 못했습니다" in note
    assert "만들어내지 말" in note


@pytest.mark.asyncio
async def test_a_granted_gmail_question_hands_back_to_the_main_turn(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": _NOT_CONNECTED, "gmail": CONNECTED},
        authority=True,
    )
    response = await routes.api_orchestration(_request(_payload("지메일에서 중요 메일 검색해줘")))

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_a_grant_less_owner_keeps_the_orchestration_search_path(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    # No trusted authority: unverified answers False and the lane proceeds.
    _patch_truth(monkeypatch, overrides={}, authority=False)
    response = await routes.api_orchestration(_request(_payload(CALENDAR_QUESTION)))

    assert response.status_code == 200
    assert len(bridge.requests) == 1, "the search path answered the turn unchanged"


@pytest.mark.asyncio
async def test_a_non_google_question_never_pays_the_grant_check(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)

    calls: list[str] = []

    async def _unexpected_check(request, *, uid):
        calls.append("check")
        return False

    monkeypatch.setattr(tools_module, "connector_tools_granted_for_fallback", _unexpected_check)
    response = await routes.api_orchestration(_request(_payload(SEARCH_QUESTION)))

    assert response.status_code == 200
    assert calls == [], "the grant check is paid by connector-intent turns only"


@pytest.mark.asyncio
async def test_the_connectors_status_answer_fills_the_grant_cache(monkeypatch):
    """앱 연결 화면(status)이 계산한 granted로 캐시가 채워진다: 다음 턴 확인 0회."""
    from app import connector_status_projection as projection_module

    truth_calls: list[str] = []

    async def _trusted_truth(request):
        return {"drive": CONNECTED, "calendar": CONNECTED}, None, True, "authsession:test"

    async def _active_state(request, sid):
        return "active"

    async def _counting_turn_truth(request, *, uid, intent_turn):
        # The turn-path truth read must NOT run: the cache already knows.
        truth_calls.append("truth")
        return ()

    monkeypatch.setattr(projection_module, "_reviewed_workspace_truth", _trusted_truth)
    monkeypatch.setattr(projection_module, "_reviewed_calendar_read_grant_state", _active_state)
    monkeypatch.setattr(projection_module, "current_user_id", lambda request: "u1")
    monkeypatch.setattr(tools_module, "_reviewed_workspace_truth", _counting_turn_truth)

    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/connectors/status",
        "headers": [],
    })
    request.scope["app"] = SimpleNamespace(state=SimpleNamespace())
    response = await projection_module.connectors_status(request)
    assert response.status_code == 200

    tools = await tools_module.connector_tools_for_turn(
        SimpleNamespace(), uid="u1", intent_turn=True,
    )
    assert [tool.name for tool in tools] == ["drive_read", "calendar_read"]
    assert truth_calls == [], "the seeded cache answers the next turn at 0ms"


TRANSPORT_SOURCE = (STATIC / "chat-transport.js").read_text(encoding="utf-8")


def run_node(source: str) -> Any:
    result = subprocess.run(
        ["node", "-e", source], capture_output=True, text=True,
        encoding="utf-8", timeout=20,
        env={**os.environ, "TRANSPORT_MODULE": str(STATIC / "chat-transport.js")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_the_browser_falls_back_to_the_main_stream_on_the_connector_refusal():
    """The streaming lane's 409 not_applicable falls back to /api/chat/stream."""
    result = run_node("""
const assert=require('node:assert/strict');
const calls=[];
global.window={
  PadiemProductCapabilities:{get:()=>({auth:{loaded:true,ready:true,authenticated:true}})},
};
global.fetch=async(url,init)=>{
  calls.push(url);
  if(url==='/api/orchestration/status')
    return {ok:true,status:200,json:async()=>({orchestration_ready:true,authenticated:true})};
  if(url==='/api/orchestration')
    return {ok:false,status:409,json:async()=>({error:{code:'orchestration_not_applicable',message:'x'}})};
  if(url==='/api/chat/stream')
    return {ok:true,status:200,headers:{get:()=>'text/event-stream'}};
  throw new Error('unexpected '+url);
};
""" + TRANSPORT_SOURCE + """
(async()=>{
  const transport=window.PadiemChatTransport;
  const response=await transport.requestStreaming({messages:[{role:'user',content:'이번 주 구글 캘린더 일정 알려줘'}]});
  assert.deepEqual(calls,['/api/orchestration/status','/api/orchestration','/api/chat/stream']);
  assert.equal(response.ok,true);
  console.log(JSON.stringify({fallback:'/api/chat/stream',calls:calls.length}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"fallback": "/api/chat/stream", "calls": 3}


def test_a_real_stream_refusal_still_throws_without_a_silent_fallback():
    """Only the connector refusal may hand the turn to the main stream."""
    result = run_node("""
const assert=require('node:assert/strict');
const calls=[];
global.window={
  PadiemProductCapabilities:{get:()=>({auth:{loaded:true,ready:true,authenticated:true}})},
};
global.fetch=async(url,init)=>{
  calls.push(url);
  if(url==='/api/orchestration/status')
    return {ok:true,status:200,json:async()=>({orchestration_ready:true,authenticated:true})};
  return {ok:false,status:503,json:async()=>({error:{code:'orchestration_unavailable',message:'x'}})};
};
""" + TRANSPORT_SOURCE + """
(async()=>{
  const transport=window.PadiemChatTransport;
  await assert.rejects(()=>transport.requestStreaming({messages:[{role:'user',content:'안녕'}]}),
    (e)=>e.code==='orchestration_unavailable');
  assert.deepEqual(calls,['/api/orchestration/status','/api/orchestration']);
  console.log(JSON.stringify({threw:true,calls:calls.length}));
})().catch(e=>{console.error(e);process.exitCode=1});
""")
    assert result == {"threw": True, "calls": 2}


BROAD_CALENDAR_QUESTIONS = (
    "내일 일정 뭐야",
    "이번 주 회의 몇 개야",
    "오늘 약속 있어?",
    "다음 주 스케줄 보여줘",
    "이번 달 일정 알려줘",
    "내일 미팅 일정 확인해줘",
    "이번 주 캘린더 조회해줘",
    "오후에 회의 있어?",
    "금요일 일정 알려줘",
    "다음 주에 잡힌 약속 뭐가 있어",
    "이번 주말 일정 정리해줘",
    "내일 3시 회의 확인",
    "오늘 일정 검색해줘",
    "이번 주 미팅 몇 건이야",
    "모레 약속 어때",
)

BROAD_DRIVE_QUESTIONS = (
    "드라이브에서 견적서 찾아줘",
    "드라이브 목록 보여줘",
    "내 파일에서 찾아줘",
    "내 파일 목록 보여줘",
    "지난주 올린 파일",
    "공유된 파일",
    "이번 주 공유된 문서",
    "문서 찾아줘",
    "견적서 어디 있어",
    "최근 사진 보여줘",
    "드라이브에 있는 보고서",
    "이번 주 회의 자료 찾아줘",
)

BROAD_NEGATIVE_QUESTIONS = (
    "일정한 간격으로 회의를 해요",
    "그는 회의적인 태도를 보였다",
    "회의록 쓰는 법 알려줘",
    "이번 주 회의록 쓰는 법",
    "오늘 일정한 속도로 달렸다",
    "내일 회의적인 사람을 만난다",
    "약속을 지키는 법",
    "오늘 약속을 지키는 법",
    "문서 작성법",
    "파일 정리하는 법",
    "드라이브 고치는 법",
    "드라이브란 무엇인가요",
    "내 파일이 안 열려요",
    "PDF 파일 여는 법",
    "이번 주 회의는 끝났다",
    "오늘 회의실 위치 알려줘",
    "다음 주 법정 일정",
    "일정 관리 방법",
    "파일을 찾는 방법",
    "지난주 올린 파일 정리하는 법",
    "파일 올려줘",
    "공유해줘",
    "내 파일이 최근에 안 열려요",
    "3시간 회의",
)

BROAD_CALENDAR_QUESTION = "이번 주 회의 몇 개야"
BROAD_DRIVE_QUESTION = "드라이브에서 견적서 찾아줘"


@pytest.mark.parametrize("text", BROAD_CALENDAR_QUESTIONS)
def test_broad_calendar_read_intents_are_recognized(text):
    assert tools_module.google_connector_broad_intent(text) == "calendar"


@pytest.mark.parametrize("text", BROAD_DRIVE_QUESTIONS)
def test_broad_drive_read_intents_are_recognized(text):
    assert tools_module.google_connector_broad_intent(text) == "drive"


@pytest.mark.parametrize("text", BROAD_NEGATIVE_QUESTIONS)
def test_broad_intent_refuses_false_positives(text):
    assert tools_module.google_connector_broad_intent(text) is None


def test_explicit_google_naming_is_not_double_counted_as_broad_intent():
    assert tools_module.google_connector_broad_intent("구글 캘린더 일정") is None
    assert tools_module.google_connector_broad_intent("구글 드라이브 파일") is None
    assert tools_module.google_connector_broad_intent("지메일 검색") is None


@pytest.mark.asyncio
async def test_a_broad_turn_requires_its_own_service_grant(monkeypatch):
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
    )
    request = SimpleNamespace()
    assert await tools_module.google_connector_turn_for_text(
        request, uid="u1", user_text=BROAD_CALENDAR_QUESTION,
    ) is False
    assert await tools_module.google_connector_turn_for_text(
        request, uid="u1", user_text=BROAD_DRIVE_QUESTION,
    ) is True

    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    tools_module.invalidate_connector_tool_grant_cache()
    assert await tools_module.google_connector_turn_for_text(
        request, uid="u1", user_text=BROAD_CALENDAR_QUESTION,
    ) is True
    assert await tools_module.google_connector_turn_for_text(
        request, uid="u1", user_text=BROAD_DRIVE_QUESTION,
    ) is False


@pytest.mark.asyncio
async def test_broad_turn_does_not_run_without_an_owner(monkeypatch):
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    assert await tools_module.google_connector_turn_for_text(
        SimpleNamespace(), uid=None, user_text=BROAD_CALENDAR_QUESTION,
    ) is False


@pytest.mark.asyncio
async def test_explicit_google_naming_keeps_its_existing_turn_path(monkeypatch):
    _patch_truth(monkeypatch, overrides={}, authority=False)
    assert await tools_module.google_connector_turn_for_text(
        SimpleNamespace(), uid="u1", user_text="구글 캘린더 일정",
    ) is True


@pytest.mark.asyncio
async def test_the_fallback_guard_can_require_the_named_service(monkeypatch):
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
    )
    assert await tools_module.connector_tools_granted_for_fallback(
        SimpleNamespace(), uid="u1", service="drive",
    ) is True
    assert await tools_module.connector_tools_granted_for_fallback(
        SimpleNamespace(), uid="u1", service="calendar",
    ) is False

    _patch_truth(
        monkeypatch,
        overrides={"drive": _NOT_CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    tools_module.invalidate_connector_tool_grant_cache()
    assert await tools_module.connector_tools_granted_for_fallback(
        SimpleNamespace(), uid="u1", service="calendar",
    ) is True
    assert await tools_module.connector_tools_granted_for_fallback(
        SimpleNamespace(), uid="u1", service="drive",
    ) is False


@pytest.mark.asyncio
async def test_a_granted_broad_calendar_question_hands_back_to_the_main_turn(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await routes.api_orchestration(_request(_payload(BROAD_CALENDAR_QUESTION)))

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_a_granted_broad_drive_question_hands_back_to_the_main_turn(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": CONNECTED},
        authority=True,
        calendar_state="active",
    )
    response = await routes.api_orchestration(_request(_payload(BROAD_DRIVE_QUESTION)))

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "orchestration_not_applicable"
    assert bridge.requests == []


@pytest.mark.asyncio
async def test_a_broad_question_without_its_own_grant_keeps_the_search_path(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(
        monkeypatch,
        overrides={"drive": CONNECTED, "calendar": _NOT_CONNECTED},
        authority=True,
    )
    response = await routes.api_orchestration(_request(_payload(BROAD_CALENDAR_QUESTION)))

    assert response.status_code == 200
    assert len(bridge.requests) == 1


@pytest.mark.asyncio
async def test_a_broad_question_from_an_unconnected_owner_keeps_the_search_path(monkeypatch):
    global bridge
    bridge = _install(monkeypatch)
    _patch_truth(monkeypatch, overrides={}, authority=False)
    response = await routes.api_orchestration(_request(_payload(BROAD_CALENDAR_QUESTION)))

    assert response.status_code == 200
    assert len(bridge.requests) == 1
