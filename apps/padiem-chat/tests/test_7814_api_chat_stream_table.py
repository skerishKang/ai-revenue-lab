"""T4 _api_chat_stream_body 1/3 앞쪽 준비 구간 골든 (#7814).

골든은 리팩터 전 origin/main(1e020b741)에서 뽑았다. 공개 진입점
``api_chat_stream``을 호출해 683-837행의 모든 반환 경로 상태·본문·헤더를
고정하고, 정상 입력 2개는 최종 SSE 이벤트 순서와 대역 호출 순서·저장 행을
고정한다. 실제 운영 값·비밀값을 쓰지 않는다.

재생성은 리팩터 전 main에서만 실행한다:
  PADIEM_REGEN_7814_STREAM_PREP=1 pytest apps/padiem-chat/tests/test_7814_api_chat_stream_table.py
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import chat_routes, claw_general_run_history, pc_work_context
from app.app_factory import create_app
from app.config import Settings
from app.history import HistoryContextIncomplete

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_api_chat_stream_table_golden.json"
)

UID = "usr_" + "a" * 32
CID = "chat_" + "9" * 32
PID = "proj_" + "8" * 32
OTHER_PID = "proj_" + "7" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fakefake"


def _payload(text="hello fake", **extra):
    return {"messages": [{"role": "user", "content": text}], **extra}


def _json(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _frame(payload):
    header = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return len(header).to_bytes(4, "big") + header + b"fake-bytes"


def _request(body, content_type="application/json", content_length=None):
    headers = [(b"content-type", content_type.encode())]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode()))
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/chat/stream",
        "headers": headers,
    })
    request._body = body
    return request


class _AdminStore:
    def __init__(self, result):
        self._result = result

    async def is_google_admin(self, user_id):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _TraceStore:
    def __init__(self, events, opts):
        self.events = events
        self.opts = opts
        self.appended = []
        self.runs = []

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        self.events.append({"call": "store.get_conversation", "conversation_id": conversation_id})
        mode = self.opts.get("store")
        if mode == "get_raise":
            raise RuntimeError("fake get failure")
        if mode == "not_found":
            return None
        project_id = {
            "bad_project": 123,
            "project_mismatch": OTHER_PID,
        }.get(mode)
        return {"id": conversation_id, "project_id": project_id}

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        self.events.append({"call": "store.get_conversation_model_context", "conversation_id": conversation_id})
        mode = self.opts.get("store")
        if mode == "owned_incomplete":
            raise HistoryContextIncomplete("fake incomplete context")
        if mode == "owned_overflow":
            raise OverflowError("fake overflow")
        if mode == "owned_other":
            raise RuntimeError("fake owned failure")
        return {"id": conversation_id, "messages": [
            {"role": "user", "content": "previous fake question"},
            {"role": "assistant", "content": "previous fake answer"},
        ]}

    async def get_project(self, user_id, project_id):
        self.events.append({"call": "store.get_project", "project_id": project_id})
        mode = self.opts.get("store")
        if mode == "project_raise":
            raise RuntimeError("fake project failure")
        if mode == "project_none":
            return None
        return SimpleNamespace(id=project_id, name="fake project", instructions="")

    async def list_files(self, user_id, project_id):
        self.events.append({"call": "store.list_files", "project_id": project_id})
        if self.opts.get("store") == "files_raise":
            raise RuntimeError("fake files failure")
        return []

    async def append_exchange(self, user_id, conversation_id, user_text, answer,
                              *args, **kwargs):
        self.events.append({
            "call": "store.append_exchange",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_text": user_text,
            "answer": answer,
            "kwargs": kwargs,
        })
        self.appended.append((user_text, answer))
        return conversation_id or ("chat_1" + "f" * 31)

    async def record_claw_run(self, **kwargs):
        self.events.append({
            "call": "store.record_claw_run",
            "kwargs": {key: value for key, value in kwargs.items() if key != "run_id"},
        })
        self.runs.append(kwargs)


class _TraceStreamClient:
    def __init__(self, events, thought="fake thought", answer="fake streamed answer"):
        self.events = events
        self.thought = thought
        self.answer = answer

    def stream_text_auto(self, messages, **kwargs):
        self.events.append({
            "call": "model.stream_text_auto",
            "messages": messages,
            "skill": None if kwargs.get("skill") is None else kwargs["skill"].id,
            "additional_system_context": kwargs.get("additional_system_context"),
            "tools": [getattr(tool, "id", str(tool)) for tool in kwargs.get("tools", ())],
        })

        async def stream():
            if self.thought:
                yield SimpleNamespace(delta_thought=self.thought, delta_content=None, done=False, tool_call=None)
            yield SimpleNamespace(delta_thought=None, delta_content=self.answer, done=False, tool_call=None)
            yield SimpleNamespace(delta_thought=None, delta_content=None, done=True, tool_call=None)

        return stream()


class _StubAutoGrounding:
    def __init__(self, events):
        self.events = events

    async def prepare(self, messages, **kwargs):
        self.events.append({
            "call": "grounding.prepare",
            "messages": messages,
            "skill": None if kwargs.get("skill") is None else kwargs["skill"].id,
            "additional_system_context": kwargs.get("additional_system_context"),
            "util_scope": kwargs.get("util_scope"),
        })
        return SimpleNamespace(prepared=None, error=None)


ERROR_CASES = [
    ("A_선언_초과", _json(_payload()), {"limit": 10}, "100", "application/json"),
    ("A_선언_깨짐", _json(_payload()), {"limit": 10}, "abc", "application/json"),
    ("A_청크_초과", b"x" * 100, {"limit": 10}, None, "application/json"),
    ("B_빈_본문", b"", {}, None, "application/json"),
    ("B_깨진_JSON", b"{", {}, None, "application/json"),
    ("B_깨진_UTF8", b"\xff\xfe", {}, None, "application/json"),
    ("B_깨진_이진_프레임", b"garbage-body", {}, None, "application/octet-stream"),
    ("B_PC세션_게이트_422", _json(_payload("PC 세션 secret `fixture-private`")), {"pc": True}, None, "application/json"),
    ("B_객체_아님", _json([1, 2]), {}, None, "application/json"),
    ("B_메시지_없음", _json({"messages": []}), {}, None, "application/json"),
    ("B_빈_텍스트", _json(_payload("   ")), {}, None, "application/json"),
    ("B_미지원_키", _json(_payload(role="system")), {}, None, "application/json"),
    ("B_첨부_형식_오류", _json(_payload(attachments="oops")), {}, None, "application/json"),
    ("B_옛_클라이언트", _json(_payload(mode="auto")), {}, None, "application/json"),
    ("B_미지_등급", _json(_payload(tier="diamond")), {}, None, "application/json"),
    ("C_도구_스트림_거부", _json(_payload(tool="deep_research")), {}, None, "application/json"),
    ("C_첨부_스트림_거부", _json(_payload(attachments={
        "type": "image", "name": "a.png", "media_type": "image/png",
        "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
    })), {}, None, "application/json"),
    ("D_비로그인", _json(_payload()), {"runtime": "b14", "uid": None}, None, "application/json"),
    ("D_custom_비로그인", _json(_payload(custom={"provider": "fake-provider", "model": "fake-model"})),
     {"uid": None}, None, "application/json"),
    ("D_admin_저장소_없음", _json(_payload(tier="admin")), {}, None, "application/json"),
    ("D_admin_거부", _json(_payload(tier="admin")), {"admin_store": False}, None, "application/json"),
    ("D_admin_확인_실패", _json(_payload(tier="admin")), {"admin_store": "raise"}, None, "application/json"),
    ("D_등급_초과", _json(_payload(tier="max")), {"runtime": "b14"}, None, "application/json"),
    ("D_프로젝트_비로그인", _json(_payload(project_id=PID)), {"uid": None}, None, "application/json"),
    ("H_조회_실패", _json(_payload(conversation_id=CID)), {"store": "get_raise"}, None, "application/json"),
    ("H_대화_없음", _json(_payload(conversation_id=CID)), {"store": "not_found"}, None, "application/json"),
    ("H_저장된_프로젝트_ID_형식", _json(_payload(conversation_id=CID)), {"store": "bad_project"}, None, "application/json"),
    ("H_프로젝트_ID_불일치", _json(_payload(conversation_id=CID, project_id=PID)), {"store": "project_mismatch"}, None, "application/json"),
    ("H_모델문맥_불완전", _json(_payload(conversation_id=CID)), {"store": "owned_incomplete"}, None, "application/json"),
    ("H_모델문맥_초과", _json(_payload(conversation_id=CID)), {"store": "owned_overflow"}, None, "application/json"),
    ("H_모델문맥_실패", _json(_payload(conversation_id=CID)), {"store": "owned_other"}, None, "application/json"),
    ("H_복원_불완전", _json(_payload(conversation_id=CID)), {"restore": "incomplete"}, None, "application/json"),
    ("H_복원_초과", _json(_payload(conversation_id=CID)), {"restore": "overflow"}, None, "application/json"),
    ("H_복원_실패", _json(_payload(conversation_id=CID)), {"restore": "other"}, None, "application/json"),
    ("P_조회_실패", _json(_payload(project_id=PID)), {"store": "project_raise"}, None, "application/json"),
    ("P_프로젝트_없음", _json(_payload(project_id=PID)), {"store": "project_none"}, None, "application/json"),
    ("P_파일목록_실패", _json(_payload(project_id=PID)), {"store": "files_raise"}, None, "application/json"),
    ("겹침_선언초과_깨진JSON", b"{", {"limit": 10}, "100", "application/json"),
    ("겹침_PC게이트_빈메시지", _json({"messages": [
        {"role": "user", "content": "PC 세션 시작 `python`"},
        {"role": "user", "content": "   "}]}), {"pc": True}, None, "application/json"),
    ("겹침_비로그인_미지등급", _json(_payload(tier="diamond")),
     {"runtime": "b14", "uid": None}, None, "application/json"),
    ("겹침_첨부_비로그인", _json(_payload(attachments={
        "type": "image", "name": "b.png", "media_type": "image/png",
        "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
    })), {"runtime": "b14", "uid": None}, None, "application/json"),
]

NORMAL_CASES = [
    ("정상_기본", _json(_payload("hello fake")), {}, None, "application/json"),
    ("정상_대화복원", _json(_payload("이어서 답해줘 fake", tier="free", conversation_id=CID)),
     {}, None, "application/json"),
]

ALL_CASES = [(name, body, opts, length, ctype, "error")
             for name, body, opts, length, ctype in ERROR_CASES]
ALL_CASES += [(name, body, opts, length, ctype, "success")
              for name, body, opts, length, ctype in NORMAL_CASES]


def _settings(opts):
    return Settings.from_values(
        runtime_mode=opts.get("runtime", "mock"),
        b14_base_url="https://b14.example.test",
        web_provider="off",
        chat_pc_session_enabled=opts.get("pc", False),
    )


def _install(monkeypatch, opts, app, events):
    uid = opts.get("uid", UID)
    signed = uid is not None
    monkeypatch.setattr(chat_routes, "auth_ready", lambda request: signed)
    monkeypatch.setattr(chat_routes, "current_user_id", lambda request: uid)
    monkeypatch.setattr(claw_general_run_history, "auth_ready", lambda request: signed)
    monkeypatch.setattr(claw_general_run_history, "current_user_id", lambda request: uid)
    if "limit" in opts:
        monkeypatch.setattr(chat_routes, "MAX_BROWSER_BODY_BYTES", opts["limit"])
    if "admin_store" in opts:
        result = RuntimeError("fake admin verify failure") if opts["admin_store"] == "raise" else opts["admin_store"]
        app.state.b66_member_admin_store = _AdminStore(result)

    mode = opts.get("restore")
    if mode is not None:
        error = {
            "incomplete": HistoryContextIncomplete("fake restore incomplete"),
            "overflow": OverflowError("fake restore overflow"),
            "other": RuntimeError("fake restore failure"),
        }[mode]

        async def restore(*args, **kwargs):
            raise error

        monkeypatch.setattr(chat_routes, "_restore_owner_chat_model_messages", restore)

    async def drive(request, latest_user_text):
        events.append({"call": "external.drive", "text": latest_user_text})
        return (None, ())

    async def pc(request, *, owner_id):
        events.append({"call": "external.pc", "owner_id": owner_id})
        return None

    async def no_pc_tools(*args, **kwargs):
        events.append({"call": "pc_tools"})
        return ()

    async def no_connector_tools(*args, **kwargs):
        events.append({"call": "connector_tools"})
        return ()

    async def connector_turn(*args, **kwargs):
        return False

    monkeypatch.setattr(chat_routes, "drive_general_grounding", drive)
    monkeypatch.setattr(pc_work_context, "build_pc_work_context_text", pc)
    monkeypatch.setattr(chat_routes, "_chat_pc_tools_for_turn", no_pc_tools)
    monkeypatch.setattr(chat_routes, "_chat_connector_tools_for_turn", no_connector_tools)
    monkeypatch.setattr(chat_routes, "google_connector_turn_for_text", connector_turn)


def _response_row(response):
    return {
        "status": response.status_code,
        "body": json.loads(response.body.decode("utf-8")),
        "headers": [list(item) for item in sorted(response.headers.items())],
    }


def _stream_row(response, events):
    return {
        "status": response.status_code,
        "headers": [list(item) for item in sorted(response.headers.items())],
        "sse": [chunk.decode("utf-8") for chunk in events],
    }


async def _run_case(name, body, opts, content_length, content_type, kind):
    events = []
    store = _TraceStore(events, opts)
    project_file_store = None if opts.get("store") in {"project_raise", "project_none"} else store
    app = create_app(_settings(opts), history_store=store, project_file_store=project_file_store)
    app.state.usage_gate_enforced = False
    app.state.calendar_store = None
    app.state.b14_client = _TraceStreamClient(events)
    app.state.auto_grounding = _StubAutoGrounding(events)
    request = _request(body, content_type, content_length)
    request.scope["app"] = app

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, opts, app, events)
        response = await chat_routes.api_chat_stream(request)
        if kind == "success":
            chunks = [chunk async for chunk in response.body_iterator]
            return {"kind": kind, "response": _stream_row(response, chunks), "calls": events}
    assert hasattr(response, "body"), name
    return {"kind": kind, "response": _response_row(response)}


@pytest.mark.asyncio
async def test_api_chat_stream_prep_public_entry_table_is_identical_to_golden():
    rows = []
    for name, body, opts, length, content_type, kind in ALL_CASES:
        row = await _run_case(name, body, dict(opts), length, content_type, kind)
        row["case"] = name
        rows.append(json.loads(json.dumps(row, ensure_ascii=False)))

    if os.environ.get("PADIEM_REGEN_7814_STREAM_PREP") == "1":
        GOLDEN_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert rows == golden
