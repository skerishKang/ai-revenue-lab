"""#8634 — the Mesh Agent build date comes from the server's node document.

No live MeshCentral server, PC command, device write or credential is used.
The request shape, the correlated reply, the shared format check, the one-hour
cache and the value-free failure codes are all fixed here.
"""
from __future__ import annotations

import json
import struct
from unittest.mock import Mock, patch

import pytest

from kagent.local_agent_mesh_helper_ready import HelperStatusReadFallback
from kagent.local_agent_meshcentral_process_port import MeshCentralProcessSocket, ps_frame
from kagent.local_agent_meshcentral_sysinfo_port import (
    MeshCentralSysInfoPort, MeshCentralSysInfoRefused, agent_version_from_sysinfo,
    new_sysinfo_tag, normalize_agent_commit_date, sysinfo_frame,
)
from kagent.local_agent_mesh_process_wiring import process_lane_kwargs
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor
from padiem_ai_core.pc_helper_ready import (
    HELPER_READY_KEYS, validate_helper_ready, validate_mesh_agent_version,
)

NODE = "node//synthetic-pc-one"
TAG = "padiem-sysinfo-0123456789abcdef"
VALID = "2026-02-16T00:43:44.000Z"
READY = dict.fromkeys(HELPER_READY_KEYS)
READY["helper_build"] = "9f2acb5916c0"


def version_resource_exe():
    """A bounded VS_VERSIONINFO stand-in for the legacy executable path."""
    key = "VS_VERSION_INFO".encode("utf-16-le") + b"\x00\x00"
    text = "2026-Feb-15 16:43:44-0800".encode("utf-16-le") + b"\x00\x00"
    body = key + b"\x00" * 8 + text
    return b"MZ" + b"\x00" * 100 + struct.pack("<HHH", 6 + len(body), 52, 0) + body


def sysinfo_answer(commit_date="2026-02-15T16:43:44-08:00", tag=TAG):
    """A stored node document with unrelated private fields we must drop."""
    return {
        "action": "getsysinfo", "nodeid": NODE, "tag": tag,
        "hardware": {
            "agentvers": {"commitDate": commit_date, "private": "private-version"},
            "windows": {"volumes": {"C:": {"recoveryPassword": "private-recovery"}}},
        },
        "node": {"name": "private-device-name"},
        "rights": 1048576,
    }


# ---- the request ------------------------------------------------------------
def test_getsysinfo_frame_is_a_server_read_and_nothing_else():
    assert sysinfo_frame(NODE, TAG) == {
        "action": "getsysinfo", "nodeid": NODE, "tag": TAG, "nodeinfo": True,
    }
    assert new_sysinfo_tag().startswith("padiem-sysinfo-")


@pytest.mark.parametrize("node", ["", "node//pc/../other", "pc with space", 123, None])
def test_frame_refuses_anything_that_is_not_a_device_identity(node):
    with pytest.raises(MeshCentralSysInfoRefused):
        sysinfo_frame(node, TAG)


@pytest.mark.parametrize("tag", ["", "x", "other-prefix-1234", TAG + " x", TAG + "x" * 120])
def test_frame_refuses_an_unbounded_correlation_tag(tag):
    with pytest.raises(MeshCentralSysInfoRefused):
        sysinfo_frame(NODE, tag)


# ---- the reply and the shared format check ----------------------------------
def test_only_the_stored_commit_date_survives_the_reply():
    assert agent_version_from_sysinfo(sysinfo_answer(), TAG) == (VALID, "observed")


@pytest.mark.parametrize("raw,expected", [
    (VALID, VALID),
    ("2026-02-15T16:43:44-08:00", VALID),
    ("2026-Feb-15 16:43:44-0800", VALID),
    ("2026-02-15T16:43:44.123456Z", "2026-02-15T16:43:44.123Z"),
])
def test_known_forms_convert_into_the_shared_bounded_stamp(raw, expected):
    value = normalize_agent_commit_date(raw)
    assert value == expected
    assert validate_mesh_agent_version(value) == value
    assert validate_helper_ready({**READY, "mesh_agent_version": value})["mesh_agent_version"] == value


@pytest.mark.parametrize("raw", [
    None, 123, "", "not a date", "2026-02-15T16:43:44",
    "C:\\Program Files\\PADIEM\\MeshAgent.exe", "node//private-pc",
    "2026-13-45T99:99:99Z", "2026-Feb-15 16:43:44-0800 extra",
])
def test_everything_else_is_refused_without_a_value(raw):
    assert normalize_agent_commit_date(raw) is None
    assert validate_mesh_agent_version(raw) is None


@pytest.mark.parametrize("answer,reason", [
    (None, "no_answer"),
    ([], "invalid_answer"),
    ({"action": "other", "tag": TAG}, "wrong_action"),
    (sysinfo_answer(tag="another-tag"), "wrong_tag"),
    ({"action": "getsysinfo", "tag": TAG, "noinfo": True}, "info_unavailable"),
    ({"action": "getsysinfo", "tag": TAG, "result": "Invalid device id"}, "info_unavailable"),
    ({"action": "getsysinfo", "tag": TAG}, "no_hardware"),
    ({"action": "getsysinfo", "tag": TAG, "hardware": {}}, "no_agentvers"),
    ({"action": "getsysinfo", "tag": TAG, "hardware": {"agentvers": {}}}, "no_commit_date"),
    (sysinfo_answer(commit_date="private text"), "format_mismatch"),
])
def test_failure_reasons_are_codes_without_values(answer, reason):
    assert agent_version_from_sysinfo(answer, TAG) == (None, reason)


# ---- the authenticated socket ----------------------------------------------
def _socket(answers):
    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.answers = list(answers)
            self.closed = False

        def send_text(self, text):
            self.sent.append(text)

        def recv(self, deadline):
            if not self.answers:
                return None
            return 1, json.dumps(self.answers.pop(0)).encode("utf-8")

        def close(self):
            self.closed = True

    opened = []

    def connect(host, port, path, headers, timeout):
        fake = FakeSocket()
        opened.append((fake, host, port, path, headers, timeout))
        return fake

    socket = MeshCentralProcessSocket(
        login_user="operator", password_provider=lambda: "op3rator-secret",
        websocket_factory=connect,
    )
    return socket, opened


def test_sysinfo_uses_the_same_authenticated_control_socket():
    frame = sysinfo_frame(NODE, TAG)
    socket, opened = _socket([
        {"action": "serverinfo"},
        {"action": "authcookie", "cookie": "c"},
        {"action": "event", "event": {}},
        sysinfo_answer(),
    ])
    answer = socket.sysinfo(frame)
    assert answer["action"] == "getsysinfo"
    fake, host, port, path, headers, timeout = opened[0]
    assert (host, port, path) == ("127.0.0.1", 4443, "/control.ashx")
    assert timeout > 0
    assert json.loads(fake.sent[0]) == {"action": "authcookie"}
    assert json.loads(fake.sent[1]) == frame
    assert "op3rator-secret" not in json.dumps(headers)
    assert fake.closed


def test_sysinfo_requires_authentication_and_refuses_every_other_frame():
    socket, opened = _socket([{"action": "serverinfo"}])
    with pytest.raises(Exception):
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert opened[0][0].closed
    socket, _ = _socket([])
    with pytest.raises(Exception):
        socket.sysinfo(ps_frame(NODE, "r1"))
    with pytest.raises(Exception):
        socket.ask(sysinfo_frame(NODE, TAG))


def test_sysinfo_answer_without_a_matching_tag_is_not_accepted():
    socket, _ = _socket([
        {"action": "authcookie"},
        sysinfo_answer(tag="another-tag"),
    ])
    assert socket.sysinfo(sysinfo_frame(NODE, TAG)) is None


# ---- the port, the cache and the fallback -----------------------------------
def test_port_sends_one_frame_and_keeps_only_the_value():
    sent = []

    def send(frame):
        sent.append(frame)
        return sysinfo_answer(tag=frame["tag"])

    port = MeshCentralSysInfoPort(send=send)
    assert port.read_commit_date(NODE) == (VALID, "observed")
    assert len(sent) == 1
    assert sent[0] == {"action": "getsysinfo", "nodeid": NODE,
                       "tag": sent[0]["tag"], "nodeinfo": True}
    with pytest.raises(ValueError):
        MeshCentralSysInfoPort(send=None)


def test_a_successful_skip_of_the_executable_path_is_cached_for_an_hour(capsys):
    sysinfo = Mock(read_commit_date=Mock(return_value=(VALID, "observed")))
    read_port = Mock(read_bytes=Mock(side_effect=AssertionError("must not read the binary")))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})),
        read_port=read_port, sysinfo_port=sysinfo,
    )
    state = dict(READY)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    assert state["mesh_agent_version"] == VALID
    sysinfo.read_commit_date.assert_called_once_with(NODE)
    read_port.read_bytes.assert_not_called()
    logs = capsys.readouterr().out
    assert logs.count("helper_ready_agent_version read=observed") == 1
    assert "read=cached" not in logs
    assert VALID not in logs and NODE not in logs


def test_a_refused_server_read_keeps_the_old_executable_path():
    sysinfo = Mock(read_commit_date=Mock(return_value=(None, "info_unavailable")))
    read_port = Mock(read_bytes=Mock(return_value=version_resource_exe()))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})),
        read_port=read_port, sysinfo_port=sysinfo,
    )
    state = dict(READY)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    assert state["mesh_agent_version"] == VALID
    read_port.read_bytes.assert_called_once()


def test_when_both_sources_fail_one_value_free_code_is_logged(capsys):
    sysinfo = Mock(read_commit_date=Mock(return_value=(None, "info_unavailable")))
    read_port = Mock(read_bytes=Mock(side_effect=FileNotFoundError("PRIVATE-PATH")))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})),
        read_port=read_port, sysinfo_port=sysinfo,
    )
    state = dict(READY)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    logs = capsys.readouterr().out
    assert logs.count("helper_ready_agent_version read=info_unavailable") == 1
    assert "PRIVATE-PATH" not in logs and "private" not in logs
    assert "mesh_agent_version" not in state or state.get("mesh_agent_version") is None


def test_a_socket_exception_becomes_a_stage_code(capsys):
    sysinfo = Mock(read_commit_date=Mock(side_effect=RuntimeError("private credential")))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})),
        read_port=Mock(read_bytes=Mock(side_effect=FileNotFoundError())),
        sysinfo_port=sysinfo,
    )
    fallback._complete_mesh_agent_version(NODE, NODE, dict(READY))
    logs = capsys.readouterr().out
    assert "helper_ready_agent_version read=sysinfo_error" in logs
    assert "private credential" not in logs


# ---- deployment composition -------------------------------------------------
def test_the_wiring_borrows_the_existing_socket_and_login_keys_keep_the_fallback():
    kwargs = process_lane_kwargs("operator", lambda: "op3rator-secret",
                                 "wss://127.0.0.1:4443", None)
    assert kwargs["sysinfo_port"] is not None
    assert process_lane_kwargs("operator", lambda: "op3rator-secret",
                               "wss://127.0.0.1:4443", "/run/secrets/login-key")["sysinfo_port"] is None


def test_the_executor_hands_the_sysinfo_port_to_helper_readiness():
    sysinfo = object()
    executor = OracleMeshExecutor(
        chat_origin="https://chat.example.test",
        channel_secret="synthetic-channel-secret",
        queue_origin="http://127.0.0.1:8797",
        read_port=Mock(), command_port=Mock(_sysinfo_port=sysinfo),
    )
    with patch("kagent.local_agent_mesh_helper_ready.attach_helper_ready") as attach:
        executor.start_helper_ready_reporting(Mock(), {"ORACLE_MESH_HELPER_READY_REPORT": "1"})
    assert attach.call_args.kwargs["sysinfo_port"] is sysinfo
