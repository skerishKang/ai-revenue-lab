"""T4 api_chat A~D 구간 증거 시험 (#7814).

리팩터 전 origin/main(d61f5e1d6)에서 api_chat 입력 구간(A 본문 크기·수신,
B 디코드+PC 세션 게이트+검증, C 모델·도구 가용성, D 인증·권한·한도)이
일으키는 모든 거부 응답과 정상 진입 값 묶음을 골든 표로 고정한다.
상태 코드·응답 본문·주요 헤더가 하나라도 바뀌면 이 시험이 실패한다.
legacy_turn_error 422 경로와 겹친 오류의 검사 순서를 포함한다.
시험 대역만 쓴다(실제 운영 값·비밀값 없음).

골든 재생성: PADIEM_REGEN_7814_API_CHAT=1 python -m pytest 이 파일
(리팩터 전 main에서만 실행한다. 리팩터 후에는 재생성하지 않는다.)

리팩터 전 채집: 본체를 그대로 실행하고 프레임 지역 변수로 E 구간 진입
시점의 값을 읽는다. 정상 입력은 E 첫 문장(effective_project_id 대입)을
실행하기 직전의 프레임을 고정한다(값 묶음은 D 끝과 같다).
리팩터 후 채집: _api_chat_intake의 (응답 | None, 값 묶음) 반환을 그대로 쓴다.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

from app import chat_routes

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "test_7814_api_chat_table_golden.json"
)

UID = "usr_" + "a" * 32
CID = "chat_" + "9" * 32
PID = "proj_" + "8" * 32

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


def _payload(text: str = "hello fake", **extra) -> dict:
    return {"messages": [{"role": "user", "content": text}], **extra}


def _json(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _frame(payload: dict, tail: bytes = b"fake-bytes") -> bytes:
    header = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return len(header).to_bytes(4, "big") + header + tail


def _request(body: bytes, headers: dict[str, str]) -> Request:
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/chat",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
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


class _Boundary(Exception):
    pass


async def _boundary_store_get(*args, **kwargs):
    raise _Boundary()


class _BoundaryClient:
    async def complete(self, messages, **kwargs):
        raise _Boundary()


def _boundary_scope():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def scope(*args, **kwargs):
        raise _Boundary()
        yield

    return scope


# (이름, 종류, 본문, 헤더, 상태 설정)
# 상태 설정 키: runtime, pc(PC 세션 스위치), web(web_provider), uid(None=비로그인),
# signed(auth_ready), limit(MAX_BROWSER_BODY_BYTES 패치), admin_store, grade(대역 등급),
# caps(모델 사진 지원 대역), no_store(history_store=None), no_pfs(project_file_store=None)
CASES = [
    # A: 본문 크기·수신
    ("A_선언_초과", "error", _json(_payload()),
     {"content-type": "application/json", "content-length": "100"},
     {"limit": 10}),
    ("A_선언_깨짐", "error", _json(_payload()),
     {"content-type": "application/json", "content-length": "abc"},
     {"limit": 10}),
    ("A_청크_초과", "error", b"x" * 100,
     {"content-type": "application/json"},
     {"limit": 10}),
    # B: 디코드·PC 세션 게이트·검증
    ("B_빈_본문", "error", b"", {"content-type": "application/json"}, {}),
    ("B_깨진_JSON", "error", b"{", {"content-type": "application/json"}, {}),
    ("B_깨진_UTF8", "error", b"\xff\xfe", {"content-type": "application/json"}, {}),
    ("B_깨진_이진_프레임", "error", b"garbage-body",
     {"content-type": "application/octet-stream"}, {}),
    ("B_게스트_이진_프레임", "error",
     _frame({"messages": [{"role": "user", "content": "사진 설명해줘"}],
             "attachments": [{"type": "image", "name": "a.png", "media_type": "image/png"}]}),
     {"content-type": "application/octet-stream"}, {}),
    ("B_PC세션_게이트_422", "error", _json(_payload("PC 세션 secret `fixture-private`")),
     {"content-type": "application/json"}, {"pc": True}),
    ("B_객체_아님", "error", _json([1, 2]), {"content-type": "application/json"}, {}),
    ("B_메시지_없음", "error", _json({"messages": []}), {"content-type": "application/json"}, {}),
    ("B_빈_텍스트", "error", _json({"messages": [{"role": "user", "content": "   "}]}),
     {"content-type": "application/json"}, {}),
    ("B_미지원_키", "error", _json(_payload(role="system")),
     {"content-type": "application/json"}, {}),
    ("B_첨부_형식_오류", "error", _json(_payload(attachments="oops")),
     {"content-type": "application/json"}, {}),
    ("B_옛_클라이언트", "error", _json(_payload(mode="auto")),
     {"content-type": "application/json"}, {}),
    ("B_미지_등급", "error", _json(_payload(tier="diamond")),
     {"content-type": "application/json"}, {}),
    # C: 모델·도구 가용성
    ("C_사진_모델_없음", "error", _json(_payload(attachments=[IMAGE_ATTACHMENT])),
     {"content-type": "application/json"},
     {"runtime": "b14", "caps": {"free": False, "fallback": False}}),
    ("C_사진_폴백_진입", "success", _json(_payload(attachments=[IMAGE_ATTACHMENT])),
     {"content-type": "application/json"},
     {"caps": {"free": False, "fallback": True}}),
    ("C_심층리서치_mock", "error", _json(_payload(tool="deep_research")),
     {"content-type": "application/json"}, {"web": "mock"}),
    ("C_심층리서치_web_off", "error", _json(_payload(tool="deep_research")),
     {"content-type": "application/json"}, {"runtime": "b14", "web": "off"}),
    # D: 인증·권한·한도
    ("D_비로그인", "error", _json(_payload()), {"content-type": "application/json"},
     {"runtime": "b14"}),
    ("D_custom_비로그인", "error",
     _json(_payload(custom={"provider": "fake-provider", "model": "fake-model"})),
     {"content-type": "application/json"}, {"uid": None}),
    ("D_admin_저장소_없음", "error", _json(_payload(tier="admin")),
     {"content-type": "application/json"}, {"signed": True}),
    ("D_admin_거부", "error", _json(_payload(tier="admin")),
     {"content-type": "application/json"}, {"admin_store": False}),
    ("D_admin_확인_실패", "error", _json(_payload(tier="admin")),
     {"content-type": "application/json"}, {"admin_store": "raise"}),
    ("D_등급_초과", "error", _json(_payload(tier="max")),
     {"content-type": "application/json"}, {"grade": "free"}),
    ("D_프로젝트_비로그인", "error", _json(_payload(project_id=PID)),
     {"content-type": "application/json"}, {"uid": None}),
    # 겹친 오류: 먼저 나오는 거부가 그대로인지(검사 순서)
    ("겹침_선언초과_깨진JSON", "error", b"{",
     {"content-type": "application/json", "content-length": "100"},
     {"limit": 10}),
    ("겹침_PC게이트_빈메시지", "error",
     _json({"messages": [{"role": "user", "content": "PC 세션 시작 `python`"},
                          {"role": "user", "content": "   "}]}),
     {"content-type": "application/json"}, {"pc": True}),
    ("겹침_비로그인_미지등급", "error", _json(_payload(tier="diamond")),
     {"content-type": "application/json"}, {"runtime": "b14"}),
    ("겹침_사진모델없음_비로그인", "error",
     _json(_payload(attachments=[IMAGE_ATTACHMENT])),
     {"content-type": "application/json"},
     {"runtime": "b14", "caps": {"free": False, "fallback": False}}),
    ("겹침_비로그인_admin", "error", _json(_payload(tier="admin")),
     {"content-type": "application/json"}, {"runtime": "b14"}),
    ("겹침_게스트_프레임_빈메시지", "error",
     _frame({"messages": [],
             "attachments": [{"type": "image", "name": "a.png", "media_type": "image/png"}]}),
     {"content-type": "application/octet-stream"}, {}),
    # 정상 진입: E 구간 시작 시점의 값 묶음
    ("정상_기본", "success", _json(_payload()), {"content-type": "application/json"}, {}),
    ("정상_문서_첨부", "success",
     _json(_payload("요약해줘 fake", skill="plan", attachments=[DOCUMENT_ATTACHMENT],
                    conversation_id=CID, product="claw")),
     {"content-type": "application/json"}, {}),
    ("정상_로그인_free", "success", _json(_payload(tier="free", conversation_id=CID)),
     {"content-type": "application/json"}, {"signed": True, "no_pfs": True}),
]


def _response_row(response) -> dict:
    return {
        "status": response.status_code,
        "body": json.loads(response.body.decode("utf-8")),
        "content_type": response.headers.get("content-type"),
        "headers": [list(item) for item in sorted(response.headers.items())],
    }


_BUNDLE_KEYS = (
    "raw", "messages", "skill", "tool_request", "attachments", "conversation_id",
    "browser_project_id", "custom", "selected_model", "uid", "store",
    "project_file_store",
)


def _bundle_row(bundle, surface) -> dict:
    return {
        "raw": bundle["raw"],
        "messages": bundle["messages"],
        "skill": {"id": bundle["skill"].id, "title": bundle["skill"].title},
        "tool_request": None if bundle["tool_request"] is None else {
            "id": bundle["tool_request"].tool.id,
            "title": bundle["tool_request"].tool.title,
            "tool_input": bundle["tool_request"].tool_input,
        },
        "attachments": [item.public_dict() for item in bundle["attachments"]],
        "conversation_id": bundle["conversation_id"],
        "browser_project_id": bundle["browser_project_id"],
        "custom": None if bundle["custom"] is None else {
            "provider": bundle["custom"].provider,
            "model": bundle["custom"].model,
            "reasoning_effort": bundle["custom"].reasoning_effort,
        },
        "selected_model": bundle["selected_model"],
        "uid": bundle["uid"],
        "store_type": type(bundle["store"]).__name__,
        "project_file_store_type": type(bundle["project_file_store"]).__name__,
        "surface": surface,
    }


def _install_stubs(monkeypatch, state, opts):
    uid = opts.get("uid", UID)
    signed = opts.get("signed", uid is not None)
    monkeypatch.setattr(chat_routes, "auth_ready", lambda req: signed)
    monkeypatch.setattr(chat_routes, "current_user_id", lambda req: uid)

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
        result = RuntimeError("fixture admin verify failure") if value == "raise" else value
        state.b66_member_admin_store = _AdminStore(result)
    if "grade" in opts:
        async def grade_denial(req, user_id, selected_grade):
            return JSONResponse(
                {"error": {"code": "tier_not_available",
                           "message": "회원 등급 이하의 AI 등급을 선택해 주세요."}},
                status_code=403,
            )
        monkeypatch.setattr(chat_routes, "selected_grade_denial", grade_denial)


def _state_for(opts):
    settings = SimpleNamespace(
        runtime_mode=opts.get("runtime", "mock"),
        web_provider=opts.get("web", "off"),
        chat_pc_session_enabled=opts.get("pc", False),
    )
    return SimpleNamespace(
        settings=settings,
        history_store=None if opts.get("no_store") else SimpleNamespace(),
        project_file_store=None if opts.get("no_pfs") else SimpleNamespace(),
    )


async def _run_refactored(request, kind, name, monkeypatch, opts):
    state = _state_for(opts)
    request.scope["app"] = SimpleNamespace(state=state)
    _install_stubs(monkeypatch, state, opts)
    resp, bundle = await chat_routes._api_chat_intake(request)
    if resp is not None:
        assert kind == "error", name
        assert bundle is None, name
        return {"case": name, "kind": kind, "response": _response_row(resp)}
    assert kind == "success", name
    assert set(bundle._fields) == set(_BUNDLE_KEYS), name
    return {
        "case": name, "kind": kind,
        "bundle": _bundle_row(bundle._asdict(), request.state.chat_product_surface),
    }


async def _run_pre_refactor(request, kind, name, monkeypatch, opts):
    state = _state_for(opts)
    request.scope["app"] = SimpleNamespace(state=state)
    _install_stubs(monkeypatch, state, opts)

    # 정상 입력이 E~I를 지나치지 않게 하는 경계 대역: E 첫 저장소 조회,
    # G 드라이브 preflight, I 티어 문맥/모델 호출에서 즉시 멈춘다.
    if state.history_store is not None:
        state.history_store.get_conversation = _boundary_store_get

    async def no_drive(req, text):
        raise _Boundary()

    monkeypatch.setattr(chat_routes, "drive_general_grounding", no_drive)
    monkeypatch.setattr(chat_routes, "chat_request_tier_context", _boundary_scope())
    state.b14_client = _BoundaryClient()
    state.usage_gate_enforced = False
    state.calendar_store = None

    captured = {}
    handler_code = chat_routes.api_chat.__code__
    boundary_line = handler_code.co_firstlineno + 86  # E 첫 문장: effective_project_id 대입

    def tracer(frame, event, arg):
        if frame.f_code is not handler_code:
            return None
        if event == "line" and frame.f_lineno == boundary_line and "bundle" not in captured:
            captured["bundle"] = {key: frame.f_locals[key] for key in _BUNDLE_KEYS}
            captured["surface"] = frame.f_locals["request"].state.chat_product_surface
        if event == "return":
            captured["response"] = arg
        return tracer

    sys.settrace(tracer)
    try:
        response = await chat_routes.api_chat(request)
    except _Boundary:
        response = captured.get("response")
    finally:
        sys.settrace(None)

    if kind == "error":
        assert response is not None, name
        return {"case": name, "kind": kind, "response": _response_row(response)}
    assert "bundle" in captured, name
    return {
        "case": name, "kind": kind,
        "bundle": _bundle_row(captured["bundle"], captured["surface"]),
    }


@pytest.mark.asyncio
async def test_api_chat_intake_table_is_identical_to_golden(monkeypatch):
    runner = (
        _run_refactored
        if hasattr(chat_routes, "_api_chat_intake")
        else _run_pre_refactor
    )
    rows = []
    for name, kind, body, headers, opts in CASES:
        request = _request(body, headers)
        row = await runner(request, kind, name, monkeypatch, dict(opts))
        rows.append(json.loads(json.dumps(row, ensure_ascii=False)))
    if os.environ.get("PADIEM_REGEN_7814_API_CHAT") == "1":
        GOLDEN_PATH.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert rows == golden