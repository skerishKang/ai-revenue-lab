"""R7-4 claw_general_execute 1단계 증거 시험 (#7814).

리팩터 전후 동일을 고정한다: 입력 검증·권한 구간이 일으키는 모든
거부·오류 경로와 정상 진입 묶음이 리팩터 전 origin/main(27e6dcb)에서
생성한 골든 표와 같다. 단계 하나의 거부 상태 코드나 문구를 바꾸면
이 시험이 실패한다. 실제 운영 값·비밀값은 쓰지 않는다(가짜 값만).
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import claw_general_routes as routes

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_general_intake_table_golden.json"
)

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


class _FakeRequest:
    def __init__(self, *, body: bytes, content_type: str = "application/json",
                 runtime_mode: str = "mock"):
        self._body = body
        self.headers = {"content-type": content_type}
        self.app = SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(runtime_mode=runtime_mode, auth_mode="off"),
            history_store=None,
        ))

    async def body(self) -> bytes:
        return self._body


def _json_body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _messages(text: str = "hello fake") -> dict:
    return {"messages": [{"role": "user", "content": text}]}


# (이름, 종류, 요청 본문, content-type, runtime_mode, max_bytes 패치)
CASES = [
    ("비로그인", "error", _json_body(_messages()), "application/json", "b14", None),
    ("미디어_형식", "error", _json_body(_messages()), "text/plain", "mock", None),
    ("본문_크기", "error", b"x" * 100, "application/json", "mock", 10),
    ("빈_본문", "error", b"", "application/json", "mock", None),
    ("깨진_JSON", "error", b"{", "application/json", "mock", None),
    ("깨진_이진_프레임", "error", b"garbage-body", "application/octet-stream", "mock", None),
    ("객체_아님", "error", _json_body([1, 2]), "application/json", "mock", None),
    ("메시지_없음", "error", _json_body({"messages": []}), "application/json", "mock", None),
    ("메시지_형식_오류", "error", _json_body({"messages": [{"role": "user"}]}), "application/json", "mock", None),
    ("빈_텍스트", "error", _json_body({"messages": [{"role": "user", "content": "   "}]}), "application/json", "mock", None),
    ("첨부_형식_오류", "error", _json_body({**_messages(), "attachments": "oops"}), "application/json", "mock", None),
    ("이미지_첨부", "error", _json_body({**_messages(), "attachments": [IMAGE_ATTACHMENT]}), "application/json", "mock", None),
    ("정상_진입", "success", _json_body(_messages("hello fake")), "application/json", "mock", None),
    (
        "문서_첨부_진입",
        "success",
        _json_body({**_messages("요약해줘 fake"), "attachments": [DOCUMENT_ATTACHMENT]}),
        "application/json", "mock", None,
    ),
    (
        "여러_턴_진입",
        "success",
        _json_body({"messages": [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "last fake"},
        ]}),
        "application/json", "mock", None,
    ),
    # 겹친 오류: 먼저 나오는 오류가 그대로인지
    ("겹침_비로그인_미디어", "error", _json_body(_messages()), "text/plain", "b14", None),
    ("겹침_미디어_빈본문", "error", b"", "text/plain", "mock", None),
    ("겹침_깨진JSON_메시지없음", "error", b"{", "application/json", "mock", None),
    (
        "겹침_빈메시지_첨부오류",
        "error",
        _json_body({"messages": [], "attachments": "oops"}),
        "application/json", "mock", None,
    ),
    (
        "겹침_첨부오류_이미지",
        "error",
        _json_body({**_messages(), "attachments": ["oops", IMAGE_ATTACHMENT]}),
        "application/json", "mock", None,
    ),
    (
        "겹침_객체아님_메시지없음",
        "error",
        _json_body(["not", "a", "dict"]),
        "application/json", "mock", None,
    ),
]


def _response_table(response) -> dict:
    return {
        "status": response.status_code,
        "body": json.loads(response.body.decode("utf-8")),
        "headers": [list(item) for item in sorted(response.headers.items())],
    }


def _bundle_table(bundle: dict) -> dict:
    conflict = bundle["attachment_conflict"]
    return {
        "turn_started_type": type(bundle["turn_started"]).__name__,
        "data": bundle["data"],
        "user_text": bundle["user_text"],
        "document_context": bundle["document_context"],
        "attachment_conflict": None if conflict is None else _response_table(conflict),
    }


def _run_case(name: str, kind: str, body: bytes, content_type: str,
              runtime_mode: str, max_bytes, monkeypatch) -> dict:
    original_max = routes.MAX_CLAW_GENERAL_BODY_BYTES
    if max_bytes is not None:
        routes.MAX_CLAW_GENERAL_BODY_BYTES = max_bytes
    try:
        request = _FakeRequest(
            body=body, content_type=content_type, runtime_mode=runtime_mode)
        error, bundle = asyncio.run(routes._claw_general_intake(request))
    finally:
        routes.MAX_CLAW_GENERAL_BODY_BYTES = original_max
    if kind == "error":
        assert error is not None and bundle is None
        return {"case": name, "kind": kind, "response": _response_table(error)}
    assert error is None and bundle is not None
    return {"case": name, "kind": kind, "bundle": _bundle_table(bundle)}


def test_claw_general_intake_table_is_identical_to_golden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = [
        _run_case(name, kind, body, content_type, runtime_mode, max_bytes, monkeypatch)
        for name, kind, body, content_type, runtime_mode, max_bytes in CASES
    ]
    assert rows == golden
