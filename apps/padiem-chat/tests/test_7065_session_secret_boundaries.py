"""Secret capability, projection and failure boundaries use synthetic values."""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import pytest

from app import mcp_gateway_session as sessions
from app.chat_pc_errors import ChatPCDriveError
from test_7065_pc_session_tools import rig, call, start
from test_7065_session_transport_audit import enable
from test_mcp_gateway_transport import gateway, post


@pytest.mark.parametrize("missing", [True, False])
def test_secret_capability_requires_the_live_owned_session_before_deposit(rig, missing):
    job = start(rig)["job_id"]
    rig[2].features.append("secret_mask")
    if missing:
        del rig[2].alive[job[4:]]
    else:
        rig[2].alive[job[4:]] = False
    result = call(rig, "pc_shell_input", {"job_id": job, "text": "fixture-private", "secret": True})
    assert result["code"] == ("pc_session_not_found" if missing else "pc_session_ended")
    assert not rig[3].values and not rig[3].takes
    assert [op["op"] for op in rig[2].operations] == ["start", "status"]


@pytest.mark.parametrize("hints, valid", [
    ({"prompt_kind": "secret", "waiting_hint": "input"}, True),
    ({"prompt_kind": "fixture-private"}, False),
    ({"waiting_hint": ["input"]}, False),
])
def test_only_closed_prompt_hints_reach_the_caller(hints, valid):
    header = {"v": 1, "ok": True, "op": "read", "session": "a" * 32, **hints}
    result = sessions.project_session_reply(json.dumps(header) + "\nPassword: ",
                                           op="read", session_id="a" * 32)
    assert (result["status"] == "completed") is valid
    if valid:
        assert all(result[key] == value for key, value in hints.items())
    else:
        assert result["code"] == "pc_session_bad_reply"
        assert "fixture-private" not in repr(result)


@pytest.mark.parametrize("wrapped", [False, True])
def test_input_exception_message_and_cause_never_reach_response_audit_or_log(gateway, caplog, wrapped):
    enable(gateway)
    value = "fixture-private-value"

    async def fail(*args, **kwargs):
        if wrapped:
            raise ChatPCDriveError(value, value, cause=value) from RuntimeError(value)
        raise RuntimeError(value)

    gateway.app.state.mcp_gateway_executor = fail
    with caplog.at_level(logging.INFO):
        response = post(gateway, "tools/call", params={"name": "pc_shell_input",
            "arguments": {"job_id": "dsp_" + "a" * 32, "text": value, "secret": True}})
    observed = response.text + repr(gateway.store.records) + repr(gateway.store.approvals) + caplog.text
    assert value not in observed
    assert base64.b64encode(value.encode()).decode() not in observed
    assert gateway.store.approvals == []


def test_actual_helper_masks_before_server_original_storage_and_offset_reads(rig, monkeypatch, tmp_path, caplog):
    root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(root / "apps" / "claw-connect"))
    from claw_connect.user_session_manager import SessionManager
    from claw_connect.user_session_helper import HelperRequest

    class Echo:
        name = "pipe"

        def __init__(self, argv, cwd, *, on_output, on_exit, **kwargs):
            self.output, self.exit = on_output, on_exit
            on_output("Password: ")

        def supports_key(self, key):
            return True

        def send_text(self, text, enter):
            for char in text:
                self.output(char)
            self.output("\n" if enter else "")

        def terminate(self):
            self.exit(0)

    manager = SessionManager(argv_builder=lambda *a, **k: ["unused"],
        backends={"pipe": Echo}, reaper_interval=None, settle_ms=0)

    def handle(operation, dispatch):
        return manager.handle(operation, request_id="req_" + dispatch[4:], cwd=str(tmp_path)).to_body().decode()

    monkeypatch.setattr(rig[2], "handle", handle)
    value = "fixture-private-한글"
    try:
        with caplog.at_level(logging.INFO):
            opened = start(rig)
            result = call(rig, "pc_shell_input", {"job_id": opened["job_id"], "text": value, "secret": True})
            reread = call(rig, "pc_shell_read", {"job_id": opened["job_id"], "offset": 0})
        assert "••••" in result["output"]
        assert opened["prompt_kind"] == "secret"
        assert value not in reread["output"]
        encoded = base64.b64encode(value.encode()).decode()
        request = HelperRequest("req_" + "a" * 32, "fixture-nonce", "session", encoded, 0)
        observed = (repr(rig[1].staged) + repr(rig[1].originals) + repr(rig[1].runs)
                    + repr(result) + repr(reread) + repr(manager._sessions) + repr(request) + caplog.text)
        assert value not in observed and encoded not in observed
        assert "fixture-nonce" not in repr(request)
        assert not rig[3].values
    finally:
        manager.shutdown()
