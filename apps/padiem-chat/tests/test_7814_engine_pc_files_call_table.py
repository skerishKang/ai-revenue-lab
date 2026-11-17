"""#7814 T4 — `_engine_pc_files_call` 1/3 앞 구간 골든 표.

`_engine_pc_files_call_verify`로 옮긴 서명·본문 파싱·모드 검증·소유자/대상 확인
구간이 지키던 계약을 리팩터링 전 `main`의 실행 결과 그대로 고정한다. 보안 경계이므로
검사 순서와 실패 응답(상태·본문), 대역 호출 순서, 디스패치 생성 인자, 대기 이유를
함께 고정한다.

- 옮긴 구간의 반환 경로 전부를 하나씩 일으킨다.
- 정상 입력 2개(list/read)는 끝까지 돌려 응답·대역 호출 순서·디스패치 생성 인자·
  대기 이유를 고정한다. 시간 값은 범주로만 고정한다.

골든은 같은 방식으로 리팩터링 전 `main`에서 먼저 떴다
(`fixtures/engine_pc_files_call_7814_verify.json`). 값은 전부 합성값이다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app import oracle_mesh_read_return_routes as routes  # noqa: E402
from app.pc_dispatch_wait_window import last_wait_reason  # noqa: E402
import test_261109_pc_dispatch_workspace_seam as seam  # noqa: E402

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "engine_pc_files_call_7814_verify.json"
)


class RecordingHistory(seam._History):
    """seam历史에 호출 순서·디스패치 생성 인자 기록을 더한 저장소."""

    def __init__(self, *, run_workspace):
        super().__init__(run_workspace=run_workspace)
        self.calls: list[str] = []
        self.dispatch_args: dict | None = None

    async def get_claw_run(self, user_id, run_id):
        self.calls.append("get_claw_run")
        return await super().get_claw_run(user_id, run_id)

    async def get_pc_run_scope(self, **kwargs):
        self.calls.append("get_pc_run_scope")
        return await super().get_pc_run_scope(**kwargs)

    async def pin_pc_run_scope(self, **kwargs):
        self.calls.append("pin_pc_run_scope")
        return await super().pin_pc_run_scope(**kwargs)

    async def update_claw_run_status(self, *args, **kwargs):
        self.calls.append("update_claw_run_status")
        return None

    async def get_local_task_correlation(self, user_id, run_id):
        self.calls.append("get_local_task_correlation")
        return await super().get_local_task_correlation(user_id, run_id)

    async def create_oracle_mesh_dispatch(self, **kwargs):
        self.calls.append("create_oracle_mesh_dispatch")
        self.dispatch_args = kwargs
        return await super().create_oracle_mesh_dispatch(**kwargs)


async def _proof(*args, **kwargs):
    return b"unused", None


def _proof_raw(raw: bytes):
    async def proof(*args, **kwargs):
        return raw, None
    return proof


async def _proof_denied(*args, **kwargs):
    return None, routes._error(401, "claw_engine_proof_required")


async def _owner_denied(*args, **kwargs):
    return None, None, routes._error(401, "canonical_session_required")


async def _target_denied(*args, **kwargs):
    return None, routes._error(503, "oracle_mesh_unconfigured")


async def _target_none(*args, **kwargs):
    return None, None


def _claim(*args, **kwargs):
    return {"ops": ["list", "read", "write", "drives"]}, None


def _claim_all(*args, **kwargs):
    return {"ops": [
        "list", "read", "write", "edit", "move", "delete", "mkdir",
        "search_name", "search_content", "drives",
    ]}, None


def _claim_read_only(*args, **kwargs):
    return {"ops": ["read"]}, None


def _claim_denied(*args, **kwargs):
    return None, routes._error(401, "pc_scope_proof_invalid")


async def _no_workspace(*args, **kwargs):
    return None


def _normalize(value):
    """Volatile id/시간만 범주로 접고 나머지는 글자 그대로 고정한다."""
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    text = re.sub(r"dsp-\d+", "dsp-N", text)
    text = re.sub(r"oracle_mesh_cmd_[0-9a-f]{32}", "oracle_mesh_cmd_<HEX>", text)
    text = re.sub(r"oracle_mesh_req_[0-9a-f]{32}", "oracle_mesh_req_<HEX>", text)
    text = re.sub(r"oracle_mesh_rev_[0-9a-f]{32}", "oracle_mesh_rev_<HEX>", text)
    text = re.sub(r"\b[0-9a-f]{64}\b", "<HEX64>", text)
    text = re.sub(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z", "<TIME>", text)
    return json.loads(text)


def _job_payload(**overrides):
    payload = {
        "subject_id": seam.SUBJECT, "run_id": seam.RUN,
        "device_id": seam.DEVICE, "mode": "job_start",
        "operation": {"op": "list", "path": "."},
        "tool_call_ref": seam.LIST_CALL,
    }
    payload.update(overrides)
    return payload


def _context_payload(**overrides):
    payload = {
        "subject_id": seam.SUBJECT, "run_id": seam.RUN,
        "device_id": None, "mode": "context",
    }
    payload.update(overrides)
    return payload


def snapshot(case: str, monkeypatch) -> dict:
    history = RecordingHistory(run_workspace=seam.MEMORY_WORKSPACE)
    session = seam._session(tenant_id=seam.WORKSPACE)
    state = seam._state(monkeypatch, session, history, seam.MEMORY_WORKSPACE)
    payload = seam._payload()

    if case == "proof_denied":
        monkeypatch.setattr(routes, "_verify_engine_proof", _proof_denied)
    elif case == "scope_proof_denied":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim_denied)
    elif case == "invalid_body":
        monkeypatch.setattr(routes, "_verify_engine_proof", _proof_raw(b"{not json"))
    elif case == "non_dict_body":
        monkeypatch.setattr(routes, "_verify_engine_proof", _proof_raw(b"[]"))
    elif case == "invalid_mode":
        payload = seam._payload(mode="bogus")
    elif case == "field_mismatch":
        body = seam._payload()
        body.pop("path")
        payload = body
    elif case == "bad_subject":
        payload = seam._payload(subject_id="")
    elif case == "job_op_invalid":
        payload = _job_payload(operation={"op": "bogus", "path": "."})
    elif case == "job_fields_invalid":
        payload = _job_payload(operation={"op": "write"})
    elif case == "write_mode_invalid":
        payload = _job_payload(operation={
            "op": "write", "path": ".", "content": "x", "mode": "bogus",
        })
    elif case == "scope_required":
        payload = _job_payload()
    elif case == "device_invalid_new_mode":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim)
        payload = _job_payload(device_id=None)
    elif case == "output_range_invalid":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim)
        payload = {
            "subject_id": seam.SUBJECT, "run_id": seam.RUN,
            "device_id": seam.DEVICE, "mode": "job_output",
            "job_id": "dsp-1", "offset": -1, "length": 16,
        }
    elif case == "selected_device_invalid":
        payload = _context_payload(device_id="")
    elif case == "owner_denied":
        monkeypatch.setattr(routes, "_engine_pc_files_owner", _owner_denied)
    elif case == "history_unconfigured":
        del state.history_store
    elif case == "run_unavailable":
        async def raise_run(*args, **kwargs):
            raise RuntimeError("store down")
        monkeypatch.setattr(history, "get_claw_run", raise_run)
    elif case == "run_row_missing":
        async def no_run(*args, **kwargs):
            return None
        monkeypatch.setattr(history, "get_claw_run", no_run)
    elif case == "scope_store_unavailable":
        async def raise_scope(*args, **kwargs):
            raise RuntimeError("store down")
        monkeypatch.setattr(history, "get_pc_run_scope", raise_scope)
    elif case == "scope_frozen":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim)
        async def other_scope(*args, **kwargs):
            history.calls.append("get_pc_run_scope")
            return {"ops": ["read"]}
        monkeypatch.setattr(history, "get_pc_run_scope", other_scope)
    elif case == "target_denied":
        monkeypatch.setattr(routes, "_engine_pc_files_target", _target_denied)
    elif case == "no_pc_context":
        monkeypatch.setattr(routes, "_engine_pc_files_target", _target_none)
        payload = _context_payload()
    elif case == "no_pc_dispatch":
        monkeypatch.setattr(routes, "_engine_pc_files_target", _target_none)
    elif case == "normal_read":
        payload = seam._payload(
            op="read", path="notes.txt", tool_call_ref=seam.READ_CALL,
        )
    elif case == "normal_list":
        pass
    elif case == "dispatch_op_invalid":
        payload = seam._payload(op="bogus")
    elif case == "dispatch_scope_denied":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim_read_only)
    elif case == "dispatch_path_invalid":
        payload = seam._payload(path="../escape")
    elif case == "dispatch_call_ref_invalid":
        payload = seam._payload(tool_call_ref="bad ref!")
    elif case == "dispatch_workspace_unavailable":
        monkeypatch.setattr(routes, "_dispatch_workspace_id", _no_workspace)
    elif case == "dispatch_content_invalid":
        payload = seam._payload(op="write", path="notes.txt", content=123)
    elif case == "dispatch_append_type_invalid":
        payload = seam._payload(op="write", path="notes.txt", content="x", append="yes")
    elif case == "dispatch_edit_invalid":
        monkeypatch.setattr(routes, "_engine_pc_scope_claim", _claim_all)
        payload = _job_payload(operation={
            "op": "edit", "path": "notes.txt", "old_text": 123,
            "new_text": "x", "replace_all": False,
        })
    elif case == "dispatch_move_invalid":
        payload = seam._payload(op="move", path="a.txt", destination="../outside")
    elif case == "dispatch_read_no_relative":
        payload = seam._payload(op="read", path=".")
    elif case == "dispatch_read_chunk_range_invalid":
        payload = seam._payload(op="read_chunk", path="notes.txt", offset=-1, length=16)
    elif case == "dispatch_search_query_invalid":
        payload = seam._payload(op="search", path=".", query="", search_mode="name")
    elif case == "dispatch_search_mode_invalid":
        payload = seam._payload(op="search", path=".", query="x", search_mode="bogus")
    elif case == "dispatch_depth_invalid":
        payload = seam._payload(op="list", path=".", depth=9)
    elif case == "dispatch_recursive_type_invalid":
        payload = seam._payload(op="list", path=".", recursive="yes")
    elif case == "dispatch_recursive_unsupported":
        payload = seam._payload(op="list", path=".", recursive=True)
    elif case == "normal_write":
        payload = seam._payload(op="write", path="notes.txt", content="hello")
    elif case == "normal_move":
        payload = seam._payload(op="move", path="a.txt", destination="b.txt")
    elif case == "normal_search":
        payload = seam._payload(op="search", path=".", query="test", search_mode="name")
    elif case == "normal_read_chunk":
        payload = seam._payload(op="read_chunk", path="notes.txt", offset=0, length=16)
    else:
        raise AssertionError(case)

    status, body = seam._dispatch(state, payload)
    return _normalize({
        "status": status,
        "body": body,
        "calls": history.calls,
        "dispatch_args": history.dispatch_args,
        "wait_reason": last_wait_reason(),
    })


CASES = (
    "proof_denied", "scope_proof_denied", "invalid_body", "non_dict_body",
    "invalid_mode", "field_mismatch", "bad_subject", "job_op_invalid",
    "job_fields_invalid", "write_mode_invalid", "scope_required",
    "device_invalid_new_mode", "output_range_invalid", "selected_device_invalid",
    "owner_denied", "history_unconfigured", "run_unavailable", "run_row_missing",
    "scope_store_unavailable", "scope_frozen", "target_denied",
    "no_pc_context", "no_pc_dispatch", "normal_list", "normal_read",
    "dispatch_op_invalid", "dispatch_scope_denied", "dispatch_path_invalid",
    "dispatch_call_ref_invalid", "dispatch_workspace_unavailable",
    "dispatch_content_invalid", "dispatch_append_type_invalid",
    "dispatch_edit_invalid", "dispatch_move_invalid", "dispatch_read_no_relative",
    "dispatch_read_chunk_range_invalid", "dispatch_search_query_invalid",
    "dispatch_search_mode_invalid", "dispatch_depth_invalid",
    "dispatch_recursive_type_invalid", "dispatch_recursive_unsupported",
    "normal_write", "normal_move", "normal_search", "normal_read_chunk",
)


def test_golden_is_the_pre_refactor_verify_table():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert set(golden) == set(CASES)
    assert golden["proof_denied"]["body"]["error"]["code"] == "claw_engine_proof_required"
    assert golden["scope_proof_denied"]["body"]["error"]["code"] == "pc_scope_proof_invalid"
    assert golden["scope_required"]["body"]["error"]["code"] == "pc_scope_required"
    assert golden["no_pc_context"]["status"] == 200
    assert golden["no_pc_dispatch"]["status"] == 403
    assert golden["normal_list"]["status"] == 200
    assert golden["normal_read"]["body"]["dispatch"]["kind"] == "read"
    dispatch = golden["normal_list"]["dispatch_args"]
    assert dispatch["kind"] == "command"
    assert dispatch["expires_at"] == "<TIME>"
    assert golden["normal_list"]["wait_reason"] == "none"
    assert golden["dispatch_op_invalid"]["body"]["error"]["code"] == "oracle_mesh_file_op_invalid"
    assert golden["dispatch_scope_denied"]["body"]["error"]["code"] == "pc_scope_denied"
    assert golden["dispatch_workspace_unavailable"]["body"]["error"]["code"] == "oracle_mesh_workspace_unavailable"
    assert golden["dispatch_edit_invalid"]["body"]["error"]["code"] == "oracle_mesh_file_edit_invalid"
    assert golden["dispatch_recursive_unsupported"]["body"]["error"]["code"] == "oracle_mesh_file_recursive_unsupported"
    assert golden["normal_write"]["status"] == 200
    assert golden["normal_search"]["body"]["dispatch"]["kind"] == "command"
    assert golden["normal_read_chunk"]["body"]["dispatch"]["kind"] == "command"


@pytest.mark.parametrize("case", CASES)
def test_verify_snapshot_matches_the_pre_refactor_golden(case, monkeypatch):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[case]
    assert snapshot(case, monkeypatch) == golden
