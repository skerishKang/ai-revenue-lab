"""Malformed session replies cannot turn input material into durable output."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from test_7065_session_input_executor import _executor, _dispatch, SESSION


VALUE = "fixture-private-echo-value"


def reply(*, header=None, output=b"", **fields):
    head = {"v": 1, "ok": True, "code": None, "op": "input", "session": SESSION,
            "alive": True, "backend": "pipe", **(header or {})}
    return json.dumps({"status": "ok", "exit_code": 0, "request_id": "req_" + SESSION,
        "stdout_b64": base64.b64encode(json.dumps(head).encode() + b"\n" + output).decode(),
        "stderr_b64": base64.b64encode(VALUE.encode()).decode(), **fields}).encode()


@pytest.mark.parametrize("raw", [
    VALUE.encode(), json.dumps([VALUE]).encode(),
    json.dumps({"status": VALUE, "detail": VALUE}).encode(),
    json.dumps({"status": "error", "request_id": "req_" + SESSION,
                "error_code": "user_helper_refused", "detail": VALUE}).encode(),
    reply(stdout_b64=VALUE), reply(header={"v": 2}, output=VALUE.encode()),
    reply(header={"alive": VALUE}, output=VALUE.encode()),
    reply(header={"offset": VALUE}, output=VALUE.encode()),
    reply(header={"code": VALUE}, output=VALUE.encode()),
    reply(header={"session": "f" * 32}, output=VALUE.encode()),
    reply(header={"op": "read"}, output=VALUE.encode()),
    reply(request_id="req_" + "f" * 32, output=VALUE.encode()),
    reply(header={"prompt_kind": VALUE}, output=VALUE.encode()),
    reply(exit_code=VALUE, output=VALUE.encode()),
    reply(header={"detail": VALUE, "unknown": VALUE}, output="••••\n".encode()),
], ids=["raw", "array", "status", "error-detail", "base64", "version", "alive", "offset",
        "code", "foreign", "operation", "foreign-request", "hint", "exit-code", "unknown-fields"])
def test_secret_not_in_submission_recovery_repr_or_log(raw, tmp_path, caplog, capsys):
    submitted = []

    def transport(path, payload):
        submitted.append(payload)
        return 503, {"ok": False}

    executor, helper = _executor(pending_dir=tmp_path, transport=transport)
    helper.run_command = lambda **kwargs: SimpleNamespace(
        termination="exited", exit_code=0, output=raw, line_blocked=0, line_cleared=0)
    dispatch = _dispatch(text=VALUE, secret=True)
    outcome = executor.execute(dispatch)
    executor.submit(dispatch, outcome)
    observed = repr(dispatch) + repr(outcome) + json.dumps(submitted) + caplog.text + str(capsys.readouterr())
    for path in tmp_path.rglob("*"):
        if path.is_file():
            observed += path.read_bytes().decode("utf-8", "replace")
    assert VALUE not in observed
    assert base64.b64encode(VALUE.encode()).decode() not in observed


def test_v1_ended_reply_preserves_masked_remaining_output():
    executor, helper = _executor()
    raw = reply(header={"ok": False, "code": "pc_session_ended", "alive": False,
                        "ended": "exited", "exit_code": 0}, exit_code=1, output="••••\n".encode())
    helper.run_command = lambda **kwargs: SimpleNamespace(termination="exited", output=raw)
    outcome = executor.execute(_dispatch(text=VALUE, secret=True))
    assert outcome.exit_code == 1
    assert json.loads(outcome.body.split(b"\n", 1)[0])["code"] == "pc_session_ended"
    assert outcome.body.split(b"\n", 1)[1].decode() == "••••\n"


def test_pipe_trace_records_a_phase_without_reflecting_reply_status():
    executor, _ = _executor()
    from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor
    script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id="req_" + SESSION, shell="session", command="e30=", cwd=None,
        timeout_seconds=0, distro=None)
    assert "Trace 'reply_received'" in script
    assert "Trace ('reply '+[string]$frame.status)" not in script
    assert "Trace 'transport_failed'" in script
    assert "if($req.shell -eq 'session' -or $detail -notmatch" in script
