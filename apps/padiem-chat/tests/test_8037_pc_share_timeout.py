"""#8037 — 공유 명령 20초 제한: Chat 스테이징·폴드 계약 (시간 주입, 원문 단언 없음).

느린 공유는 커넥터 시험에서 흉내 내고, 여기서는 서버가 내리는 판정만 고정한다:
- 승인된 공유 루트의 명령에만 공유 선언이 실리고, 로컬 드라이브 명령은 그대로다.
- 선언은 승인된 공유 주소만 담는다(철자 보존 #7978/#8041, 승인 단위 #8036).
- 폴드 응답은 스테이징이 선언한 공유만 커넥터에 넘긴다.
- 닫힌 pc_share_unavailable 본문은 완료된 행으로 닫히되 실패로 안내된다.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.pc_share_timeout import (
    PC_SHARE_COMMAND_TIMEOUT_SECONDS,
    PC_SHARE_UNAVAILABLE_CODE,
    PC_SHARE_UNAVAILABLE_MESSAGE_EN,
    PC_SHARE_UNAVAILABLE_MESSAGE_KO,
    share_command_prefix,
    share_roots_of,
    share_timeout_verdict_body,
)
from _support import pc_share_lane as lane

SHARE = "//fileserver/sharename"
SHARE_WIN = "\\\\fileserver\\sharename"
LOCAL_ROOT = "C:/Users/qa/문서"


def _declaration(command: str) -> list[str] | None:
    match = re.search(r"\$padiemShareTargets\s*=\s*@\((.*)\)", command)
    if match is None:
        return None
    return [
        base64.b64decode(blob, validate=True).decode("utf-8")
        for blob in re.findall(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)", match.group(1))
    ]


# -- the bound and the closed code --------------------------------------------


def test_the_share_bound_is_the_cto_decision():
    assert PC_SHARE_COMMAND_TIMEOUT_SECONDS == 20
    assert PC_SHARE_UNAVAILABLE_CODE == "pc_share_unavailable"


def test_the_verdict_body_carries_both_guidance_languages():
    body = json.loads(share_timeout_verdict_body())
    assert body["ok"] is False
    assert body["error"] == PC_SHARE_UNAVAILABLE_CODE
    assert body["message"] == PC_SHARE_UNAVAILABLE_MESSAGE_KO
    assert body["message_en"] == PC_SHARE_UNAVAILABLE_MESSAGE_EN
    assert "회사 네트워크" in body["message"]


# -- only approved share roots are declared ------------------------------------


def test_share_roots_of_keeps_only_share_units_in_their_own_spelling():
    roots = [
        {"path": SHARE}, {"path": LOCAL_ROOT}, {"path": "D:"},
        {"path": "\\\\fileserver\\sharename\\"},  # same unit, other spelling
        {"path": "//fileserver"},                 # a bare server is not a share
    ]
    assert share_roots_of(roots) == [SHARE_WIN]


def test_the_prefix_declares_the_share_and_nothing_for_a_local_drive():
    assert _declaration(share_command_prefix([{"path": SHARE}])) == [SHARE_WIN]
    assert share_command_prefix([{"path": LOCAL_ROOT}, {"path": "D:"}]) == ""
    assert share_command_prefix([]) == ""
    assert share_command_prefix(None) == ""


def test_the_declaration_keeps_a_korean_share_spelling_exact():
    root = "//파일서버/공유 문서"
    prefix = share_command_prefix([{"path": root}])
    assert _declaration(prefix) == ["\\\\파일서버\\공유 문서"]
    assert prefix.isascii()


# -- the engine dispatch leg stages the declaration ----------------------------


@pytest.mark.parametrize("op,path,extra", [
    ("list", "sharename/보고", {}),
    ("read_chunk", "sharename/보고/a.txt", {"offset": 0, "length": 64}),
    ("search", "sharename/보고", {"query": "보고", "search_mode": "name"}),
])
def test_a_share_file_call_stages_the_share_declaration(monkeypatch, op, path, extra):
    roots = [{"label": "sharename", "path": SHARE},
             {"label": "문서", "path": LOCAL_ROOT}]
    state, history = lane.engine_state(monkeypatch, roots)
    payload = {
        "subject_id": lane.SUBJECT, "run_id": lane.RUN, "device_id": lane.DEVICE,
        "op": op, "path": path, "tool_call_ref": lane.LIST_CALL, "mode": "dispatch",
        **extra,
    }
    status, body = lane.engine_dispatch(state, payload)
    assert status == 200, body
    row = history.rows[body["dispatch"]["dispatch_id"]]
    assert row["kind"] == "command"
    declared = _declaration(row["command_text"])
    assert declared and all(item.startswith(SHARE_WIN) for item in declared)
    assert row["share_roots"] == declared


@pytest.mark.parametrize("op,path,extra", [
    ("list", "문서/보고", {}),
    ("read_chunk", "문서/보고/a.txt", {"offset": 0, "length": 64}),
    ("search", "문서/보고", {"query": "보고", "search_mode": "name"}),
])
def test_a_local_drive_call_keeps_its_exact_old_command(monkeypatch, op, path, extra):
    roots = [{"label": "sharename", "path": SHARE},
             {"label": "문서", "path": LOCAL_ROOT}]
    state, history = lane.engine_state(monkeypatch, roots)
    payload = {
        "subject_id": lane.SUBJECT, "run_id": lane.RUN, "device_id": lane.DEVICE,
        "op": op, "path": path, "tool_call_ref": lane.LIST_CALL, "mode": "dispatch",
        **extra,
    }
    status, body = lane.engine_dispatch(state, payload)
    assert status == 200, body
    row = history.rows[body["dispatch"]["dispatch_id"]]
    assert _declaration(row["command_text"]) is None
    assert "share_roots" not in row


def test_a_search_over_every_root_declares_only_the_share_units(monkeypatch):
    roots = [{"label": "sharename", "path": SHARE},
             {"label": "문서", "path": LOCAL_ROOT}]
    state, history = lane.engine_state(monkeypatch, roots)
    payload = {
        "subject_id": lane.SUBJECT, "run_id": lane.RUN, "device_id": lane.DEVICE,
        "op": "search", "path": ".", "query": "보고", "search_mode": "content",
        "tool_call_ref": lane.LIST_CALL, "mode": "dispatch",
    }
    status, body = lane.engine_dispatch(state, payload)
    assert status == 200, body
    row = history.rows[body["dispatch"]["dispatch_id"]]
    assert _declaration(row["command_text"]) == [SHARE_WIN]
    assert row["share_roots"] == [SHARE_WIN]


def test_an_unregistered_share_is_still_refused_before_any_command(monkeypatch):
    roots = [{"label": "문서", "path": LOCAL_ROOT}]
    state, history = lane.engine_state(monkeypatch, roots)
    payload = {
        "subject_id": lane.SUBJECT, "run_id": lane.RUN, "device_id": lane.DEVICE,
        "op": "list", "path": "\\\\other\\share\\x",
        "tool_call_ref": lane.LIST_CALL, "mode": "dispatch",
    }
    status, body = lane.engine_dispatch(state, payload)
    assert status == 422
    assert history.rows == {}


# -- the external connector (MCP) path keeps the same authority ----------------


def test_the_mcp_path_still_rewrites_a_share_path_to_the_label(monkeypatch):
    result, recorder = lane.mcp_call(
        monkeypatch, "pc_list", {"path": SHARE_WIN + "\\보고"},
        roots=[{"name": "sharename", "path": SHARE}],
    )
    assert result["status"] == "completed"
    sent = json.loads(recorder.calls[0]["body"])
    assert sent["pc_gateway"]["arguments"]["path"] == "sharename/보고"


def test_the_mcp_path_still_refuses_an_unapproved_share(monkeypatch):
    result, recorder = lane.mcp_call(
        monkeypatch, "pc_list", {"path": "\\\\other\\share\\x"},
        roots=[{"name": "sharename", "path": SHARE}],
    )
    assert result["status"] == "failed"
    assert result["code"] == "pc_path_outside_registered_roots"
    assert recorder.calls == []


# -- the poll hands the executor exactly the staged declaration ----------------


def test_the_poll_echoes_the_staged_share_declaration():
    store = lane.PollStore(lane.poll_row(share_roots=[SHARE_WIN]))
    response = asyncio.run(routes.oracle_mesh_read_poll(lane.poll_request(store)))
    assert response.status_code == 200
    dispatch = json.loads(response.body)["dispatch"]
    assert dispatch["share_roots"] == [SHARE_WIN]
    assert store.claimed == [dispatch["dispatch_id"]]


def test_the_poll_without_a_declaration_keeps_the_exact_old_shape():
    store = lane.PollStore(lane.poll_row())
    response = asyncio.run(routes.oracle_mesh_read_poll(lane.poll_request(store)))
    dispatch = json.loads(response.body)["dispatch"]
    assert "share_roots" not in dispatch


def test_the_poll_never_hands_out_a_malformed_declaration():
    store = lane.PollStore(lane.poll_row(share_roots=["", 3]))
    response = asyncio.run(routes.oracle_mesh_read_poll(lane.poll_request(store)))
    dispatch = json.loads(response.body)["dispatch"]
    assert "share_roots" not in dispatch


# -- the closed verdict finishes the row and guides the owner ------------------


def _share_wire(output: str):
    raw = output.encode("utf-8")
    return {
        "termination": "no_exit_code", "exit_code": None,
        "content_utf8": output, "content_bytes": len(raw),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_the_share_verdict_closes_the_row_as_a_named_failure():
    dispatch = {"kind": "command", "command_id": "cmd-1",
                "command_text": "Get-ChildItem x"}
    resp, bundle = asyncio.run(routes._oracle_mesh_read_result_outcome(
        dispatch, None, _share_wire(share_timeout_verdict_body()),
    ))
    assert resp is None
    assert bundle["outcome"] == "done"
    assert bundle["status"] == "failed"
    assert bundle["summary"] == PC_SHARE_UNAVAILABLE_CODE
    assert PC_SHARE_UNAVAILABLE_MESSAGE_KO in bundle["content"]


def test_an_ordinary_listing_keeps_its_old_judgement():
    dispatch = {"kind": "command", "command_id": "cmd-1",
                "command_text": "Get-ChildItem x"}
    output = json.dumps({"offset": 0, "total": 0, "has_more": False, "items": []})
    resp, bundle = asyncio.run(routes._oracle_mesh_read_result_outcome(
        dispatch, None, _share_wire(output),
    ))
    assert resp is None
    assert bundle["outcome"] == "done"
    assert bundle["status"] == "completed"