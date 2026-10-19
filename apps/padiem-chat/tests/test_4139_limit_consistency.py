"""#4139 limit consistency and lossless output splitting.

What this file can detect that the existing lane tests cannot:

* a command, path or output that a *middle* stage rejects again after the first
  stage let it through — the caps that survived at the dispatch row, the request
  envelope and the message head;
* an output split whose parts do not concatenate back to the original bytes,
  invisible while every fixture output happens to end with a newline;
* a message head that eats the shared per-message budget, stranding a whole
  result on a storage refusal the caller reads as a transient failure.

The real dispatch row is used where the bound lives in the row (the SQLite
double built from the committed 047/048 migrations), and the real route wiring
elsewhere.
"""
from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from app import claw_general_routes as claw
from app import oracle_mesh_read_return_routes as routes
from app.history import HistoryError, MAX_HISTORY_MESSAGE_CHARS
from test_4139_mesh_command import (
    ACCOUNT, CONVERSATION, DEVICE, NODE, OWNER, RUN, SECRET, TENANT_WS, WORKSPACE,
    Request, _dispatch, _state, _submit, setup_auth,
)
from test_4139_mesh_original import (
    CONVERSATION as STORE_CONVERSATION,
    OWNER as STORE_OWNER,
    _dispatch_kwargs,
    fixture,
)

LONG_COMMAND = "Get-Content 'C:\\사용자\\보고서.txt'\n" * 400
READ_FIELDS = {
    "user_id": OWNER, "run_id": RUN, "command_id": "c", "tool_request_ref": "t",
    "request_id": "r", "revision_ref": "rev", "evidence_ref": None,
    "request_fingerprint": "f", "account_ref": ACCOUNT,
    "workspace_ref": WORKSPACE, "device_id": DEVICE, "binding_ref": None,
    "node_ref": NODE, "root_ref": "meshcentral_private_trial",
    "path_relative": "보고서.txt", "file_path": "C:\\사용자\\보고서.txt",
    "expires_at": "2099-01-01T00:00:00.000Z",
}


def _parts_of(content: str) -> str:
    """The output bytes one conversation message carries, markers removed."""
    return content.split(" 시작 ---\n", 1)[1].rsplit("\n--- 출력 끝 ---", 1)[0]


class Utf8Request:
    """One body in the shape the executor actually sends: UTF-8 JSON, escaped
    nothing. The lane's other double escapes, which inflates Korean text about
    sixfold and is precisely the artifact this test must not reproduce."""

    def __init__(self, data, state, *, secret=None):
        from types import SimpleNamespace

        self.app = SimpleNamespace(state=state)
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.headers = {
            "content-type": "application/json", "content-length": str(len(raw)),
        }
        if secret is not None:
            self.headers[routes.ORACLE_MESH_CHANNEL_HEADER] = secret
        self._data = raw

    async def body(self):
        return self._data


# ── 1. no middle stage re-applies a trial cap ───────────────────────────────
def test_recognition_accepts_a_multiline_korean_command_over_the_old_cap():
    accepted, command = claw._requested_local_command(
        "내 PC에서 실행해줘: `" + LONG_COMMAND.rstrip() + "`"
    )
    assert accepted is True
    assert "\n" in command and len(command) > 8192


def _stage_run(store, run_id: str) -> None:
    """A dispatch row belongs to an owned run, so the run is staged first."""
    asyncio.run(store.record_claw_run(
        user_id=STORE_OWNER, run_id=run_id, channel="web", action="txt_read",
        title="Claw: limit", status="pending", conversation_id=STORE_CONVERSATION,
        workspace_id="ws-1",
    ))


def test_dispatch_row_accepts_a_multiline_utf8_command_over_the_old_cap(tmp_path):
    store, _bucket = fixture(tmp_path)
    _stage_run(store, "run-limit-1")
    command = "Write-Output '보고서'\n" + ("Get-Item 'C:\\temp\\a.txt'\n" * 3_000)
    assert len(command) > 8192 and "\n" in command
    row = asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id="run-limit-1", command_text=command)
    ))
    assert row["command_text"] == command
    # The poll read is the leg that hands the command to the executor, so the
    # whole multi-line UTF-8 body has to survive it unchanged.
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["command_text"] == command


def test_dispatch_row_still_refuses_what_breaks_the_lane(tmp_path):
    """The refusals are structural, not a product length rule."""
    store, _bucket = fixture(tmp_path)
    _stage_run(store, "run-limit-2")
    for bad in ("", "a\x00b", "a\rb", "\x07 beep", "x" * 2_500_000):
        with pytest.raises(HistoryError):
            asyncio.run(store.create_oracle_mesh_dispatch(
                **_dispatch_kwargs(run_id="run-limit-2", command_text=bad)
            ))


def test_a_command_above_the_old_100k_statement_guess_is_stored(tmp_path):
    """D1's 100,000-byte ceiling is the SQL statement text, not a bound value.

    The command travels as a parameter, so the ceiling that binds it is the
    documented 2,000,000-byte string/row size. A 220 KB command is ordinary
    input and must reach the executor leg unchanged.
    """
    store, _bucket = fixture(tmp_path)
    _stage_run(store, "run-limit-3")
    command = "Get-Content 'C:\\a.txt'\n" * 10_000
    assert 100_000 < len(command.encode("utf-8")) < 2_000_000
    asyncio.run(store.create_oracle_mesh_dispatch(
        **_dispatch_kwargs(run_id="run-limit-3", command_text=command)
    ))
    handed = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert handed["command_text"] == command


def test_a_command_larger_than_the_row_bound_is_refused_by_name(monkeypatch):
    """Refusal happens at the storage ceiling, named, and nothing is written."""
    setup_auth(monkeypatch)
    state = _state()
    status, body, _ = _dispatch(state, command="x" * 150_000)
    assert status == 200, body
    status, body, _ = _dispatch(state, command="x" * 2_100_000)
    assert status == 413
    assert body["error"]["code"] == "oracle_mesh_dispatch_too_large"


def test_a_long_korean_path_survives_the_map_and_the_validator():
    long_relative = "보고서/" + "하위/" * 4_000 + "최종 보고서.txt"
    assert len(long_relative) > 8192
    assert routes._text_value(long_relative) == long_relative

    mapping = [{
        "account_ref": "account-oracle-1", "device_id": "device-oracle-1",
        "node_ref": NODE, "root_ref": "meshcentral_private_trial",
        "path_relative": long_relative,
        "file_path": "C:\\사용자\\" + long_relative.replace("/", "\\"),
    }]
    source = routes.build_oracle_mesh_return_source(mapping, SECRET, "mesh")
    assert source is not None
    assert source._rows[0]["path_relative"] == long_relative


def test_a_path_over_the_documented_windows_ceiling_is_refused():
    assert routes._text_value("a" * (routes._MAX_PATH_VALUE_CHARS + 1)) is None
    assert routes._text_value("a" * routes._MAX_PATH_VALUE_CHARS) == (
        "a" * routes._MAX_PATH_VALUE_CHARS
    )


def test_a_request_body_larger_than_the_old_trial_cap_is_read():
    """A read request carries a path, so it cannot ride an 8 KiB cap."""
    payload = {
        "device_id": DEVICE, "run_id": RUN,
        "root_ref": "meshcentral_private_trial",
        "path_relative": "보고서/" + "하위/" * 4_000 + "a.txt",
        "confirmed": True,
    }
    assert len(json.dumps(payload).encode("utf-8")) > 8192
    wire = asyncio.run(
        routes._read_body(Request(payload, _state()), routes._REQUEST_KEYS)
    )
    assert wire is not None and wire["path_relative"] == payload["path_relative"]


# ── 2. the split is lossless and the head cannot eat the output ─────────────
@pytest.mark.parametrize("limit", [7_400, 8_000, 64])
@pytest.mark.parametrize("shape", [
    "\n" + "a" * 7_401,
    "a\n\n\nb",
    "\n\n\n" + "x" * 8_000,
    "a\r\n\r\nb\r\n" + "c" * 8_000,
    "z" * 30_000,
    "hello\n",
    "가\n나\n\n다\r\n" * 500,
    "",
    "\n",
    "q" * 65,
])
def test_parts_concatenate_to_the_output_byte_for_byte(shape, limit):
    parts = routes._command_output_parts(shape, limit)
    assert all(len(part) <= limit for part in parts)
    assert "".join(parts) == shape


def test_a_head_with_no_room_fails_fast_instead_of_looping():
    """Slicing against a zero bound would never finish; it is a caller bug."""
    with pytest.raises(ValueError):
        routes._command_output_parts("abc\n" * 10, 0)
    with pytest.raises(ValueError):
        routes._command_output_parts("abc", -1)


def test_output_part_budget_shrinks_with_the_head_it_ships_with():
    narrow = routes._command_part_budget(["PC 파일 읽기 결과"])
    wide = routes._command_part_budget(["x" * 100] * 20)
    assert 0 < wide < narrow < MAX_HISTORY_MESSAGE_CHARS


def test_a_large_command_echo_cannot_strand_a_large_output(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state, command=LONG_COMMAND)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = "".join(
        "line-%04d " % index + "가나다" * 60 + "\n" for index in range(1_200)
    )
    status, payload, _ = _submit(
        state, row, termination="exited", exit_code=0, body=body.encode("utf-8"),
    )
    assert status == 200, payload
    appended = state.history_store.appended
    assert len(appended) > 1
    assert all(len(item["content"]) <= MAX_HISTORY_MESSAGE_CHARS for item in appended)
    assert routes._COMMAND_ECHO_MARK in appended[0]["content"]
    rebuilt = "".join(_parts_of(item["content"]) for item in appended)
    assert rebuilt == body
    assert hashlib.sha256(rebuilt.encode("utf-8")).hexdigest() == row["result_sha256"]


def test_over_budget_preview_fits_one_message_whatever_the_command(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state, command=LONG_COMMAND)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    body = "\n".join("LINE-%06d-" % index + "x" * 7_380 for index in range(300)) + "\n"
    status, payload, _ = _submit(
        state, row, termination="exited", exit_code=0, body=body.encode("utf-8"),
    )
    assert status == 200, payload
    assert len(state.history_store.appended) == 1
    content = state.history_store.appended[0]["content"]
    assert len(content) <= MAX_HISTORY_MESSAGE_CHARS
    assert "비공개 원문 저장소" in content
    assert state.history_store.originals[row["dispatch_id"]] == body.encode("utf-8")


def test_a_read_lane_document_splits_without_losing_a_byte(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    row = asyncio.run(state.history_store.create_oracle_mesh_dispatch(**READ_FIELDS))
    text = ("한글 문서 라인\n\n" * 5_000) + "끝"
    status, payload, _ = _submit(
        state, row, termination="exited", exit_code=0, body=text.encode("utf-8"),
    )
    assert status == 200, payload
    appended = state.history_store.appended
    assert len(appended) > 1
    assert all(len(item["content"]) <= MAX_HISTORY_MESSAGE_CHARS for item in appended)
    assert "".join(_parts_of(item["content"]) for item in appended) == text


def test_a_large_korean_output_fits_the_envelope_the_wire_actually_carries(
    monkeypatch,
):
    """The wire carries UTF-8 JSON, so a Korean body is not inflated 6x.

    With escaped JSON a body well under the 6 MB result envelope is refused as
    too large, the executor reads the 400 as permanent, and the result is
    quarantined instead of delivered.
    """
    setup_auth(monkeypatch)
    state = _state()
    _, created, _ = _dispatch(state)
    row = state.history_store.rows[created["dispatch"]["dispatch_id"]]
    text = "리포트 행\n" * 350_000  # 4.9 MB of UTF-8 content
    body = text.encode("utf-8")
    assert len(body) < routes._MAX_RESULT_BODY_BYTES

    nonce = "n" * 32
    state.history_store.rows[row["dispatch_id"]]["nonce_sha256"] = (
        hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    )
    payload = {
        "dispatch_id": row["dispatch_id"], "nonce": nonce,
        "termination": "exited", "exit_code": 0,
        "content_utf8": text,
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "content_bytes": len(body),
    }
    wire_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(wire_bytes) < routes._MAX_RESULT_BODY_BYTES
    assert len(json.dumps(payload).encode("utf-8")) > routes._MAX_RESULT_BODY_BYTES

    response = asyncio.run(routes.oracle_mesh_read_result(
        Utf8Request(payload, state, secret=SECRET)
    ))
    assert response.status_code == 200, response.body
    assert state.history_store.originals or len(state.history_store.appended) > 1


def test_a_read_lane_document_over_the_row_guard_is_stored_whole(monkeypatch):
    setup_auth(monkeypatch)
    state = _state()
    row = asyncio.run(state.history_store.create_oracle_mesh_dispatch(**READ_FIELDS))
    # Wide enough to cross the per-run message guard while staying inside the
    # result envelope the wire actually carries.
    text = "\n".join("doc-%06d-" % index + "x" * 7_300 for index in range(300)) + "\n"
    status, payload, _ = _submit(
        state, row, termination="exited", exit_code=0, body=text.encode("utf-8"),
    )
    assert status == 200, payload
    assert len(state.history_store.appended) == 1
    content = state.history_store.appended[0]["content"]
    assert len(content) <= MAX_HISTORY_MESSAGE_CHARS
    assert state.history_store.originals[row["dispatch_id"]] == text.encode("utf-8")
