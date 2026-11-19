"""#8037 — 공유 불가 판정은 닫힌 코드 pc_share_unavailable 로 안내된다.

커넥터가 20초 제한으로 닫은 공유 명령의 본문은 목록·검색·구간 읽기 어느
투구에서도 같은 닫힌 코드로 표면화되고, 사용자 안내(ko·en)가 따라간다.
로컬 드라이브의 정상 결과와 일반 실패는 기존 판정 그대로다.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import (
    PC_LIST_FILES_TOOL_ID,
    PC_READ_CHUNK_TOOL_ID,
    PC_SEARCH_CONTENT_TOOL_ID,
    PC_SEARCH_FILES_TOOL_ID,
    ToolHandlerError,
    _pc_chunk_projection,
    _pc_refusal,
    _pc_search_projection,
)

OWNER = ("sub_" + "a" * 32, "run_8037", "b54-padiem-claw", "device-1")
SECRET = "s" * 32
DISPATCH_ID = "dsp_" + "c" * 32

VERDICT = json.dumps({
    "ok": False, "error": "pc_share_unavailable",
    "message": "네트워크 공유 폴더에 연결할 수 없어요. 회사 네트워크에 연결돼 있는지 확인해 주세요.",
    "message_en": "Can't reach the network share folder. Please check that you're connected to your company network.",
}, ensure_ascii=False)


class _Request:
    def __init__(self, url, *, method, headers, body):
        self.url = url
        self.method = method
        self.headers = headers
        self.body = body
        self.js_object = self


class _Response:
    def __init__(self, payload):
        self.status = 200
        self._payload = payload

    async def text(self):
        return json.dumps(self._payload, ensure_ascii=False)


class _ShareClosedService:
    """dispatch → received → done(닫힌 공유 본문) 순서로 답하는 대역."""

    def __init__(self, output=VERDICT):
        self.output = output
        self.modes = []

    async def fetch(self, request):
        payload = json.loads(request.body)
        mode = payload["mode"]
        self.modes.append(mode)
        if mode == "dispatch":
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": OWNER[1], "kind": "command",
            }})
        if mode == "command_status":
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": OWNER[1], "kind": "command",
                "state": "done",
            }})
        if mode == "result":
            return _Response({"ok": True, "dispatch": {
                "dispatch_id": DISPATCH_ID, "run_id": OWNER[1], "kind": "command",
                "state": "done", "output": self.output,
                "termination": "no_exit_code", "exit_code": None,
            }})
        raise AssertionError("unexpected mode " + mode)


@pytest.fixture(autouse=True)
def _no_real_waiting(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)


def _run(handler, arguments):
    token = driver._PC_QUERY_OWNER.set(OWNER)
    try:
        return asyncio.run(handler(arguments))
    finally:
        driver._PC_QUERY_OWNER.reset(token)


def _list_handler(service):
    return driver._pc_observing_handler(
        driver._make_pc_file_handler(
            tool_id=PC_LIST_FILES_TOOL_ID, op="list", service=service,
            request_factory=_Request, secret=SECRET,
        ),
        tool_id=PC_LIST_FILES_TOOL_ID,
    )


def _search_handler(service, tool_id, mode):
    return driver._pc_observing_handler(
        driver._make_pc_search_handler(
            tool_id=tool_id, search_mode=mode, service=service,
            request_factory=_Request, secret=SECRET,
        ),
        tool_id=tool_id,
    )


def _chunk_handler(service):
    return driver._pc_observing_handler(
        driver._make_pc_read_chunk_handler(
            service=service, request_factory=_Request, secret=SECRET,
        ),
        tool_id=PC_READ_CHUNK_TOOL_ID,
    )


# -- the closed code and its guidance ------------------------------------------


def test_the_closed_code_carries_the_korean_and_english_guidance():
    refusal = _pc_refusal("pc_share_unavailable")
    assert refusal["ok"] is False
    assert refusal["stage"] == "pc_share_unavailable"
    assert "네트워크 공유 폴더에 연결할 수 없어요" in refusal["hint"]
    assert "회사 네트워크에 연결돼 있는지 확인해 주세요" in refusal["hint"]
    assert "company network" in refusal["hint"]


# -- every read/list/search tool surfaces the same closed code ------------------


def test_a_share_closed_listing_answers_the_closed_code():
    result = _run(_list_handler(_ShareClosedService()), {"path": "."})
    assert result["ok"] is False
    assert result["stage"] == "pc_share_unavailable"
    assert "회사 네트워크" in result["hint"]


@pytest.mark.parametrize("tool_id,mode", [
    (PC_SEARCH_FILES_TOOL_ID, "name"),
    (PC_SEARCH_CONTENT_TOOL_ID, "content"),
])
def test_a_share_closed_search_answers_the_closed_code(tool_id, mode):
    result = _run(_search_handler(_ShareClosedService(), tool_id, mode),
                  {"query": "보고"})
    assert result["ok"] is False
    assert result["stage"] == "pc_share_unavailable"


def test_a_share_closed_range_read_answers_the_closed_code():
    result = _run(_chunk_handler(_ShareClosedService()),
                  {"path": "보고/a.txt", "offset": 0})
    assert result["ok"] is False
    assert result["stage"] == "pc_share_unavailable"


# -- the projections keep every other judgement unchanged -----------------------


def test_the_search_projection_maps_only_the_exact_closed_shape():
    with pytest.raises(ToolHandlerError) as caught:
        _pc_search_projection(VERDICT, query="보고", mode="name")
    assert caught.value.code == "pc_share_unavailable"
    # 같은 ok=false 라도 다른 코드는 기존 판정(모양 오류) 그대로다.
    with pytest.raises(ToolHandlerError) as other:
        _pc_search_projection(json.dumps({"ok": False, "error": "other"}),
                              query="보고", mode="name")
    assert other.value.code == "pc_search_output_invalid"


def test_the_chunk_projection_maps_only_the_exact_closed_shape():
    with pytest.raises(ToolHandlerError) as caught:
        _pc_chunk_projection(VERDICT, offset=0, length=64)
    assert caught.value.code == "pc_share_unavailable"
    with pytest.raises(ToolHandlerError) as other:
        _pc_chunk_projection(json.dumps({"ok": False, "error": "not_a_file"}),
                             offset=0, length=64)
    assert other.value.code == "pc_chunk_not_a_file"


def test_a_local_listing_keeps_its_normal_projection():
    service = _ShareClosedService(output=json.dumps({
        "offset": 0, "total": 1, "has_more": False,
        "items": [{"Name": "a.txt", "Length": 3, "PSIsContainer": False,
                   "Modified": "2026-11-19T00:00:00Z"}],
    }))
    result = _run(_list_handler(service), {"path": "."})
    assert result["ok"] is True
    assert result["entry_count"] == 1


def test_an_ordinary_execution_failure_keeps_its_old_code():
    class _FailedService(_ShareClosedService):
        async def fetch(self, request):
            payload = json.loads(request.body)
            if payload["mode"] == "command_status":
                self.modes.append("command_status")
                return _Response({"ok": True, "dispatch": {
                    "dispatch_id": DISPATCH_ID, "run_id": OWNER[1],
                    "kind": "command", "state": "failed",
                }})
            return await super().fetch(request)

    result = _run(_list_handler(_FailedService()), {"path": "."})
    assert result["ok"] is False
    assert result["stage"] == "pc_files_execution_failed"