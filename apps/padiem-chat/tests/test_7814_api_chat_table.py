"""T4 api_chat A~D 공개 진입점 골든 표 (#7814).

골든은 리팩터 전 origin/main(74d0eb40b)에서 뽑았다. A(본문 크기·수신),
B(디코드 + PC 세션 게이트 + 검증), C(모델·도구 가용성),
D(인증·권한·한도)의 반환 상태·본문·헤더와, 정상 입력이 G 이후의 모델·저장소
·외부 대역을 거치는 순서와 주요 인자를 고정한다.

재생성은 리팩터 전 main에서만 실행한다:
  PADIEM_REGEN_7814_API_CHAT=1 pytest apps/padiem-chat/tests/test_7814_api_chat_table.py

실제 운영 값·비밀값을 쓰지 않는다. 도우미 내부 진입값 비교는 하지 않는다.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from starlette.requests import Request

from app import chat_routes, claw_general_run_history, pc_work_context
from app.app_factory import create_app
from app.config import Settings

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_api_chat_table_golden.json"
)

UID = "usr_" + "a" * 32
CID = "chat_" + "9" * 32
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fakefake"
IMAGE_ATTACHMENT = {
    "type": "image",
    "name": "a.png",
    "media_type": "image/png",
    "base64": base64.b64encode(PNG_BYTES).decode("ascii"),
}
DOCUMENT_ATTACHMENT = {
    "type": "document",
    "name": "a.txt",
    "media_type": "text/plain",
    "text": "fake document text",
}


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
        "path": "/api/chat",
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


class _AdminDenial:
    def __init__(self, response):
        self.response = response

    async def __call__(self, request, user_id, selected_grade):
        return self.response


ERROR_CASES = [
    ("A_선언_초과", _json(_payload()), {"limit": 10}, "100"),
    ("A_선언_깨짐", _json(_payload()), {"limit": 10}, "abc"),
    ("A_청크_초과", b"x" * 100, {"limit": 10}, None),
    ("B_빈_본문", b"", {}, None),
    ("B_깨진_JSON", b"{", {}, None),
    ("B_깨진_UTF8", b"\xff\xfe", {}, None),
    ("B_깨진_이진_프레임", b"garbage-body", {"content_type": "application/octet-stream"}, None),
    ("B_게스트_이진_프레임", _frame({
        "messages": [{"role": "user", "content": "사진 설명해줘"}],
        "attachments": [{"type": "image", "name": "a.png", "media_type": "image/png"}],
    }), {"content_type": "application/octet-stream"}, None),
    ("B_PC세션_게이트_422", _json(_payload("PC 세션 secret `fixture-private`")), {"pc": True}, None),
    ("B_객체_아님", _json([1, 2]), {}, None),
    ("B_메시지_없음", _json({"messages": []}), {}, None),
    ("B_빈_텍스트", _json(_payload("   ")), {}, None),
    ("B_미지원_키", _json(_payload(role="system")), {}, None),
    ("B_첨부_형식_오류", _json(_payload(attachments="oops")), {}, None),
    ("B_옛_클라이언트", _json(_payload(mode="auto")), {}, None),
    ("B_미지_등급", _json(_payload(tier="diamond")), {}, None),
    ("C_사진_모델_없음", _json(_payload(attachments=[IMAGE_ATTACHMENT])), {
        "runtime": "b14", "caps": {"free": False, "fallback": False}}, None),
    ("C_심층리서치_mock", _json(_payload(tool="deep_research")), {"web": "mock"}, None),
    ("C_심층리서치_web_off", _json(_payload(tool="deep_research")), {"runtime": "b14"}, None),
    ("D_비로그인", _json(_payload()), {"runtime": "b14", "uid": None}, None),
    ("D_custom_비로그인", _json(_payload(custom={"provider": "fake-provider", "model": "fake-model"})),
     {"uid": None}, None),
    ("D_admin_저장소_없음", _json(_payload(tier="admin")), {}, None),
    ("D_admin_거부", _json(_payload(tier="admin")), {"admin_store": False}, None),
    ("D_admin_확인_실패", _json(_payload(tier="admin")), {"admin_store": "raise"}, None),
    ("D_등급_초과", _json(_payload(tier="max")), {"runtime": "b14"}, None),
    ("D_프로젝트_비로그인", _json(_payload(project_id="proj_" + "8" * 32)), {"uid": None}, None),
    ("겹침_선언초과_깨진JSON", b"{", {"limit": 10}, "100"),
    ("겹침_PC게이트_빈메시지", _json({"messages": [
        {"role": "user", "content": "PC 세션 시작 `python`"},
        {"role": "user", "content": "   "}]}), {"pc": True}, None),
    ("겹침_비로그인_미지등급", _json(_payload(tier="diamond")),
     {"runtime": "b14", "uid": None}, None),
    ("겹침_사진모델없음_비로그인", _json(_payload(attachments=[IMAGE_ATTACHMENT])), {
        "runtime": "b14", "uid": None, "caps": {"free": False, "fallback": False}}, None),
    ("겹침_비로그인_admin", _json(_payload(tier="admin")),
     {"runtime": "b14", "uid": None}, None),
]

NORMAL_CASES = [
    ("정상_기본", _json(_payload()), {}, None),
    ("정상_문서_첨부", _json(_payload("요약해줘 fake", skill="plan", tier="free",
                                 attachments=[DOCUMENT_ATTACHMENT],
                                 conversation_id=CID, product="claw")),
     {"drive_context": "fake drive context", "pc_context": "fake pc context"}, None),
]

ALL_CASES = [(name, body, opts, length, "error")
             for name, body, opts, length in ERROR_CASES]
ALL_CASES += [(name, body, opts, length, "success")
              for name, body, opts, length in NORMAL_CASES]


def _settings(opts):
    return Settings.from_values(
        runtime_mode=opts.get("runtime", "mock"),
        b14_base_url="https://b14.example.test",
        web_provider=opts.get("web", "off"),
        chat_pc_session_enabled=opts.get("pc", False),
    )


def _skill(skill):
    return None if skill is None else {"id": skill.id, "title": skill.title}


def _attachment(item):
    return item.public_dict()


class _TraceClient:
    """Reuses the existing mock B14 client contract with a call trace."""

    def __init__(self, events):
        self.events = events
        self.completed = []

    async def complete(self, messages, **kwargs):
        self.events.append({
            "call": "model.complete",
            "messages": messages,
            "skill": _skill(kwargs.get("skill")),
            "additional_system_context": kwargs.get("additional_system_context"),
            "attachments": [_attachment(item) for item in kwargs.get("attachments", ())],
        })
        self.completed.append(messages)
        return {"answer": "fake model answer", "runtime": "mock"}


class _TraceStore:
    """Reuses the completed-turn store contract with a call trace."""

    def __init__(self, events):
        self.events = events
        self.appended = []
        self.runs = []

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        if conversation_id != CID:
            return None
        return {"id": conversation_id, "project_id": None}

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        if conversation_id != CID:
            return None
        return {"id": conversation_id, "messages": [
            {"role": "user", "content": "previous fake question"},
            {"role": "assistant", "content": "previous fake answer"},
        ]}

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


def _install(monkeypatch, opts, app, events):
    uid = opts.get("uid", UID)
    monkeypatch.setattr(chat_routes, "auth_ready", lambda request: uid is not None)
    monkeypatch.setattr(chat_routes, "current_user_id", lambda request: uid)
    monkeypatch.setattr(claw_general_run_history, "auth_ready", lambda request: uid is not None)
    monkeypatch.setattr(claw_general_run_history, "current_user_id", lambda request: uid)
    if "limit" in opts:
        monkeypatch.setattr(chat_routes, "MAX_BROWSER_BODY_BYTES", opts["limit"])
    if "caps" in opts:
        caps = opts["caps"]

        def supports(model_id, capability):
            if capability != "image":
                return False
            if model_id == chat_routes.FREE_B14_MODEL_ID:
                return caps["free"]
            if model_id == chat_routes.FREE_FALLBACK_B14_MODEL_ID:
                return caps["fallback"]
            return False

        monkeypatch.setattr(chat_routes, "model_supports", supports)
    if "admin_store" in opts:
        value = opts["admin_store"]
        result = RuntimeError("fake admin verify failure") if value == "raise" else value
        app.state.b66_member_admin_store = _AdminStore(result)

    async def drive(request, latest_user_text):
        events.append({"call": "external.drive", "text": latest_user_text})
        context = opts.get("drive_context")
        if context is None:
            return (None, ())
        return (context, ({
            "title": "fake source",
            "url": "https://example.test/fake",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_type": "google_drive",
        },))

    async def pc(request, *, owner_id):
        events.append({"call": "external.pc", "owner_id": owner_id})
        return opts.get("pc_context")

    monkeypatch.setattr(chat_routes, "drive_general_grounding", drive)
    monkeypatch.setattr(pc_work_context, "build_pc_work_context_text", pc)


def _response_row(response):
    return {
        "status": response.status_code,
        "body": json.loads(response.body.decode("utf-8")),
        "headers": [list(item) for item in sorted(response.headers.items())],
    }


async def _run_case(body, opts, content_length, kind):
    events = []
    app = create_app(_settings(opts), history_store=_TraceStore(events))
    app.state.usage_gate_enforced = False
    app.state.calendar_store = None
    app.state.b14_client = _TraceClient(events)

    def decide(messages, **kwargs):
        events.append({
            "call": "auto_grounding.decide",
            "messages": messages,
            "skill": _skill(kwargs.get("skill")),
            "util_scope": kwargs.get("util_scope"),
            "explicit_search": kwargs.get("explicit_search"),
        })
        return None

    app.state.auto_grounding = type("StubAutoGrounding", (), {"decide": staticmethod(decide)})()
    request = _request(body, opts.get("content_type", "application/json"), content_length)
    request.scope["app"] = app

    with pytest.MonkeyPatch.context() as monkeypatch:
        _install(monkeypatch, opts, app, events)
        response = await chat_routes.api_chat(request)

    row = {"case": None, "kind": kind, "response": _response_row(response)}
    if kind == "success":
        row["calls"] = events
    return row


@pytest.mark.asyncio
async def test_api_chat_public_entry_table_is_identical_to_golden():
    rows = []
    for name, body, opts, content_length, kind in ALL_CASES:
        row = await _run_case(body, dict(opts), content_length, kind)
        row["case"] = name
        rows.append(json.loads(json.dumps(row, ensure_ascii=False)))

    if os.environ.get("PADIEM_REGEN_7814_API_CHAT") == "1":
        GOLDEN_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert rows == golden
