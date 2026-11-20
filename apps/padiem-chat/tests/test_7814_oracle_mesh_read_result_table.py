"""#7814 T4 — `oracle_mesh_read_result` 1/3 앞 구간 골든 표.

`_oracle_mesh_read_result_verify`로 옮긴 서명·nonce·lease·디스패치 조회 구간이
지키던 계약을 리팩터링 전 `main`의 실행 결과 그대로 고정한다. 보안 경계이므로
검사 순서와 실패 응답(상태·본문), 로그 줄 순서를 함께 고정한다.

- 옮긴 구간의 반환 경로 전부를 하나씩 일으킨다.
- 검사가 2개 이상 걸리는 입력 2개로 어느 쪽이 먼저 나는지 고정한다.
- 정상 입력 2개는 끝까지 돌려 소비·적재·종료 행과 stage 로그 순서를 고정한다.
  시간 값은 범주로만 고정한다.

골든은 같은 방식으로 리팩터링 전 `main`에서 먼저 떴다
(`fixtures/oracle_mesh_read_result_7814_verify.json`). 값은 전부 합성값이다.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.history import HistoryForbidden
from test_oracle_mesh_read_return import Request, call, result_body

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "fixtures" / "oracle_mesh_read_result_7814_verify.json"
)
# 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
SECRET = secrets.token_urlsafe(32)
DISPATCH = "dsp-" + "a" * 28
NONCE = "nonce-fixture-0123456789"
TEXT = "PADIEM MESHCENTRAL SINGLE-PC TXT TEST\nEND_OF_FILE\n"
SHA = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
LOG_NAME = "app.oracle_mesh_read_return_routes"


class FakeHistory:
    def __init__(self, *, consume=None, store_fail=None, append_fail=None,
                 append_value=True):
        self.consume_override = consume
        self.store_fail = store_fail
        self.append_fail = append_fail
        self.append_value = append_value
        self.calls: list[str] = []

    def _record(self, name):
        self.calls.append(name)

    async def consume_oracle_mesh_dispatch(self, **kwargs):
        self._record("consume")
        if self.consume_override is None:
            return {
                "dispatch_id": DISPATCH, "run_id": "run-oracle-1",
                "user_id": "product-user-1",
                "claim": "first", "kind": "read", "command_id": "cmd-1",
                "revision_ref": "rev-1", "command_text": "read file",
            }
        if isinstance(self.consume_override, Exception):
            raise self.consume_override
        return self.consume_override

    async def finish_oracle_mesh_dispatch(self, **kwargs):
        self._record("finish")
        return True

    async def mark_oracle_mesh_store_failed(self, **kwargs):
        self._record("failed")
        return True

    async def record_oracle_mesh_first_result(self, **kwargs):
        self._record("first_result")
        return True

    async def store_oracle_mesh_original(self, **kwargs):
        self._record("original")
        if self.store_fail is not None:
            raise self.store_fail
        return b"ok"

    async def get_claw_run(self, *args, **kwargs):
        self._record("get_run")
        return {"run_id": "run-oracle-1", "conversation_id": "chat_" + "a" * 32,
                "workspace_id": "ws-1", "status": "waiting"}

    async def append_local_task_result(self, **kwargs):
        self._record("append")
        if self.append_fail is not None:
            raise self.append_fail
        return self.append_value


class NoMethodHistory(FakeHistory):
    append_local_task_result = None


class NoDispatchHistory(FakeHistory):
    async def consume_oracle_mesh_dispatch(self, **kwargs):
        self._record("consume")
        return None


def _state(history):
    return SimpleNamespace(
        history_store=history,
        oracle_mesh_return_source=SimpleNamespace(),
        control_plane_identity_authority=SimpleNamespace(),
        mesh_device_presence_store=None,
    )


def _log_lines(records):
    """Only the pc_result stage lines, with volatile ids dropped."""
    out = []
    for record in records:
        msg = record.getMessage()
        if "pc_result stage=" not in msg and "stage=received" not in msg:
            continue
        parts = [token for token in msg.split()
                 if not token.startswith("run_hash=") and not token.startswith("dispatch_id=")
                 and not token.startswith("request_id=") and not token.endswith("ms")]
        out.append(parts)
    return out


def snapshot(case: str, monkeypatch, caplog) -> dict:
    body = result_body(DISPATCH, NONCE)
    history = FakeHistory()
    secret = SECRET
    source_present = True
    proof_ok = True

    if case == "invalid_body":
        body = {"not": "a result"}
        # force the body reader to refuse
        monkeypatch.setattr(routes, "_read_result_body", _bad_body)
    elif case == "bad_dispatch_id":
        body = result_body("", NONCE)
    elif case == "bad_nonce":
        body = result_body(DISPATCH, "")
    elif case == "bad_node_ref":
        body = result_body(DISPATCH, NONCE, node_ref="bad\nref")
    elif case == "bad_termination":
        body = result_body(DISPATCH, NONCE, termination="bogus")
    elif case == "exit_code_missing":
        body = result_body(DISPATCH, NONCE, exit_code=None)
    elif case == "exit_code_type":
        body = result_body(DISPATCH, NONCE, exit_code="0")
    elif case == "mesh_unconfigured":
        source_present = False
        monkeypatch.setattr(routes, "_channel_source", lambda request: None)
    elif case == "channel_rejected":
        secret = "wrong-channel-secret"
        proof_ok = False
    elif case == "store_unconfigured":
        history = NoMethodHistory()
    elif case == "consume_unavailable":
        history = FakeHistory(consume=RuntimeError("store down"))
    elif case == "dispatch_rejected":
        history = NoDispatchHistory()
    elif case == "claim_unavailable":
        history = FakeHistory(consume={"claim": "unexpected", "kind": "read",
                                       "dispatch_id": DISPATCH, "run_id": "run-oracle-1"})
    elif case == "order_body_before_channel":
        body = result_body(DISPATCH, "")
        secret = "wrong-channel-secret"
    elif case == "order_channel_before_consume":
        secret = "wrong-channel-secret"
        proof_ok = False
        history = FakeHistory(consume=RuntimeError("store down"))
    elif case in ("command_store_forbidden", "command_store_unavailable"):
        cmd_dispatch = {
            "dispatch_id": DISPATCH, "run_id": "run-oracle-1",
            "user_id": "product-user-1", "claim": "first", "kind": "command",
            "command_id": "cmd-1", "revision_ref": "rev-1",
            "command_text": "dir", "termination": "exited",
        }
        fail = (HistoryForbidden("forbidden") if case == "command_store_forbidden"
                else RuntimeError("store down"))
        history = FakeHistory(consume=cmd_dispatch, store_fail=fail)
    elif case == "not_appended":
        history = FakeHistory(append_value=False)
    elif case in ("normal_read", "normal_empty"):
        if case == "normal_empty":
            body = result_body(DISPATCH, NONCE, content_utf8="",
                               content_sha256=hashlib.sha256(b"").hexdigest(),
                               content_bytes=0, termination="exited", exit_code=0)
    else:
        raise AssertionError(case)

    if source_present and case not in ("mesh_unconfigured",):
        monkeypatch.setattr(routes, "_channel_source", lambda request: object())
    monkeypatch.setattr(routes, "_channel_proof", lambda request, source: proof_ok)

    caplog.set_level(__import__("logging").INFO, logger=LOG_NAME)
    caplog.clear()
    request = Request(body, _state(history), secret=secret)
    status, payload, _ = call(routes.oracle_mesh_read_result, request)
    return {
        "status": status,
        "body": payload,
        "history_calls": history.calls,
        "logs": _log_lines(caplog.records),
    }


async def _bad_body(request):
    return None


CASES = (
    "invalid_body", "bad_dispatch_id", "bad_nonce", "bad_node_ref",
    "bad_termination", "exit_code_missing", "exit_code_type",
    "mesh_unconfigured", "channel_rejected", "store_unconfigured",
    "consume_unavailable", "dispatch_rejected", "claim_unavailable",
    "order_body_before_channel", "order_channel_before_consume",
    "command_store_forbidden", "command_store_unavailable", "not_appended",
    "normal_read", "normal_empty",
)


def test_golden_is_the_pre_refactor_verify_table():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert set(golden) == set(CASES)
    assert golden["mesh_unconfigured"]["body"]["error"]["code"] == "oracle_mesh_unconfigured"
    assert golden["channel_rejected"]["body"]["error"]["code"] == "oracle_mesh_channel_rejected"
    assert golden["dispatch_rejected"]["status"] == 409
    assert golden["command_store_forbidden"]["body"]["error"]["code"] == "oracle_mesh_conversation_forbidden"
    assert golden["command_store_unavailable"]["body"]["error"]["code"] == "oracle_mesh_original_unavailable"
    assert any("stage=received" in " ".join(line) for line in golden["normal_read"]["logs"])
    assert any("stage=not_appended" in " ".join(line) for line in golden["not_appended"]["logs"])
    assert any("stage=queue_finished" in " ".join(line) for line in golden["normal_read"]["logs"])


@pytest.mark.parametrize("case", CASES)
def test_verify_snapshot_matches_the_pre_refactor_golden(case, monkeypatch, caplog):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[case]
    assert snapshot(case, monkeypatch, caplog) == golden
