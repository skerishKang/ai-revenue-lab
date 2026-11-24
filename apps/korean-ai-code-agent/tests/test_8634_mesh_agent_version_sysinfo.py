"""#8634 — the Mesh Agent build date comes from the server's node document.

No live MeshCentral server, PC command, device write or credential is used.
The request shape, the correlated reply, the shared format check, the one-hour
cache and the value-free failure codes are all fixed here.
"""
from __future__ import annotations

import base64
import json
import struct
from unittest.mock import Mock, patch

import pytest

from kagent.local_agent_mesh_helper_ready import HelperStatusReadFallback
from kagent.local_agent_meshcentral_process_port import MeshCentralProcessSocket, ps_frame
from kagent.local_agent_meshcentral_sysinfo_port import (
    SYSINFO_DENIED, SYSINFO_ERROR, SYSINFO_NODEID, SYSINFO_NO_REPLY,
    SYSINFO_REASON_CODES, SYSINFO_SHAPE, SYSINFO_TIMEOUT, SYSINFO_TRANSPORT,
    MeshCentralSysInfoPort, MeshCentralSysInfoReadFailure,
    MeshCentralSysInfoRefused, agent_version_from_sysinfo,
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
        {"action": "userinfo"},
        {"action": "event", "event": {}},
        sysinfo_answer(),
    ])
    answer = socket.sysinfo(frame)
    assert answer["action"] == "getsysinfo"
    fake, host, port, path, headers, timeout = opened[0]
    assert (host, port, path) == ("127.0.0.1", 4443, "/control.ashx")
    assert timeout > 0
    # The greeting is the authentication proof; no relay-cookie request is
    # sent and only the closed getsysinfo frame goes out on the wire.
    assert [json.loads(sent) for sent in fake.sent] == [frame]
    assert "op3rator-secret" not in json.dumps(headers)
    assert fake.closed


def test_sysinfo_opens_the_socket_exactly_like_the_existing_pc_command_path():
    frame = sysinfo_frame(NODE, TAG)
    command = ps_frame(NODE, "r1")

    command_socket, command_opened = _socket([
        {"action": "authcookie", "cookie": "c"},
        {"action": "msg", "type": "ps", "responseid": "r1", "value": "{}"},
    ])
    command_socket.ask(command)
    version_socket, version_opened = _socket([
        {"action": "serverinfo"},
        {"action": "userinfo"},
        sysinfo_answer(),
    ])
    version_socket.sysinfo(frame)

    _, chost, cport, cpath, cheaders, ctimeout = command_opened[0]
    _, vhost, vport, vpath, vheaders, vtimeout = version_opened[0]
    assert (vhost, vport, vpath, vtimeout) == (chost, cport, cpath, ctimeout)
    assert vheaders == cheaders
    assert vheaders["x-meshauth"].startswith(
        base64.b64encode(b"operator").decode("ascii") + ","
    )
    assert base64.b64encode(b"op3rator-secret").decode("ascii") in vheaders["x-meshauth"]
    assert "op3rator-secret" not in json.dumps(vheaders)


def test_server_greeting_order_confirms_authentication():
    for greeting in (
        [{"action": "serverinfo"}, {"action": "userinfo"}],
        [{"action": "userinfo"}, {"action": "serverinfo"}],
    ):
        socket, _ = _socket([*greeting, sysinfo_answer()])
        answer = socket.sysinfo(sysinfo_frame(NODE, TAG))
        assert answer["action"] == "getsysinfo"


def test_unrelated_frames_before_the_greeting_are_skipped():
    socket, _ = _socket([
        {"action": "ping"},
        {"action": "serverstats", "values": {}},
        {"action": "serverinfo"},
        sysinfo_answer(),
    ])
    assert socket.sysinfo(sysinfo_frame(NODE, TAG))["action"] == "getsysinfo"


def test_sysinfo_requires_authentication_and_refuses_every_other_frame():
    socket, opened = _socket([])
    with pytest.raises(Exception):
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert opened[0][0].closed
    # A relay cookie alone is not the server's authentication greeting. This
    # is the exact frame the pre-fix path waited for, so it is load-bearing.
    socket, _ = _socket([
        {"action": "authcookie", "cookie": "c", "rcookie": "r"},
        sysinfo_answer(),
    ])
    with pytest.raises(Exception):
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    socket, _ = _socket([{"action": "close", "cause": "noauth", "msg": "noauth"}])
    with pytest.raises(Exception):
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    socket, _ = _socket([])
    with pytest.raises(Exception):
        socket.sysinfo(ps_frame(NODE, "r1"))
    with pytest.raises(Exception):
        socket.ask(sysinfo_frame(NODE, TAG))


def test_sysinfo_answer_without_a_matching_tag_is_not_accepted():
    socket, _ = _socket([
        {"action": "serverinfo"},
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


# ---- #8634B: one value-free code per wire failure ---------------------------
WIRE_CODES = (SYSINFO_NODEID, SYSINFO_DENIED, SYSINFO_TRANSPORT,
              SYSINFO_TIMEOUT, SYSINFO_NO_REPLY, SYSINFO_SHAPE, SYSINFO_ERROR)


def test_each_wire_failure_has_its_own_bounded_code():
    assert len(set(WIRE_CODES)) == len(WIRE_CODES)
    assert set(WIRE_CODES) <= SYSINFO_REASON_CODES
    for code in WIRE_CODES:
        assert code.startswith("sysinfo_")
        assert NODE not in code and "secret" not in code and "127.0.0.1" not in code


@pytest.mark.parametrize("raised,code", [
    (MeshCentralSysInfoReadFailure(SYSINFO_DENIED), SYSINFO_DENIED),
    (MeshCentralSysInfoReadFailure(SYSINFO_SHAPE), SYSINFO_SHAPE),
    (TimeoutError("PRIVATE-HOST"), SYSINFO_TIMEOUT),
    (ConnectionRefusedError("PRIVATE-HOST"), SYSINFO_TRANSPORT),
    (RuntimeError("private credential on PRIVATE-HOST"), SYSINFO_ERROR),
])
def test_port_classifies_a_raised_failure_by_type_only(raised, code):
    port = MeshCentralSysInfoPort(send=Mock(side_effect=raised))
    assert port.read_commit_date(NODE) == (None, code)


def test_port_reports_uncanonical_node_without_raising_or_sending():
    port = MeshCentralSysInfoPort(send=Mock(side_effect=AssertionError("must not send")))
    assert port.read_commit_date("node//bad id") == (None, SYSINFO_NODEID)


def test_port_reports_no_correlated_reply():
    port = MeshCentralSysInfoPort(send=Mock(return_value=None))
    assert port.read_commit_date(NODE) == (None, SYSINFO_NO_REPLY)


@pytest.mark.parametrize("code", WIRE_CODES)
def test_helper_logs_each_wire_code_on_its_own_line(capsys, code):
    sysinfo = Mock(read_commit_date=Mock(side_effect=MeshCentralSysInfoReadFailure(code)))
    read_port = Mock(read_bytes=Mock(side_effect=FileNotFoundError()))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})),
        read_port=read_port, sysinfo_port=sysinfo,
    )
    fallback._complete_mesh_agent_version(NODE, NODE, dict(READY))
    logs = capsys.readouterr().out
    assert f"helper_ready_agent_version read={code}" in logs
    assert NODE not in logs and "private" not in logs.lower()


def _wire_socket(*, answers=(), recv_error=None, connect_error=None):
    class FakeSocket:
        def __init__(self):
            self.sent = []
            self.answers = list(answers)
            self.closed = False

        def send_text(self, text):
            self.sent.append(text)

        def recv(self, deadline):
            if recv_error is not None:
                raise recv_error
            if not self.answers:
                return None
            return 1, json.dumps(self.answers.pop(0)).encode("utf-8")

        def close(self):
            self.closed = True

    def connect(host, port, path, headers, timeout):
        if connect_error is not None:
            raise connect_error
        return FakeSocket()

    return MeshCentralProcessSocket(
        login_user="operator", password_provider=lambda: "op3rator-secret",
        websocket_factory=connect,
    )


def test_socket_reports_denied_when_the_server_greeting_never_arrives():
    socket = _wire_socket()
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_DENIED
    assert str(caught.value) == SYSINFO_DENIED
    assert "op3rator-secret" not in str(caught.value)


@pytest.mark.parametrize("refusal", [
    {"action": "close", "cause": "noauth", "msg": "noauth"},
    {"action": "authcookie", "cookie": "c", "rcookie": "r"},
])
def test_socket_reports_denied_for_a_refusal_or_only_a_relay_cookie(refusal):
    socket = _wire_socket(answers=[refusal, sysinfo_answer()])
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_DENIED


def test_socket_reports_denied_for_an_invalid_operator_credential():
    socket = MeshCentralProcessSocket(
        login_user="operator", password_provider=lambda: "bad\nsecret",
        websocket_factory=lambda *args: None,
    )
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_DENIED
    assert "secret" not in str(caught.value)


def test_socket_reports_transport_when_the_private_tunnel_cannot_open():
    socket = _wire_socket(connect_error=OSError("PRIVATE-HOST"))
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_TRANSPORT
    assert "PRIVATE-HOST" not in str(caught.value)


def test_socket_reports_timeout_when_the_recv_deadline_is_hit():
    socket = _wire_socket(recv_error=TimeoutError("PRIVATE-HOST"))
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_TIMEOUT
    assert "PRIVATE-HOST" not in str(caught.value)


@pytest.mark.parametrize("payload", [b"{not-json", b"[]", b'"text"'])
def test_socket_reports_shape_for_an_unusable_reply_frame(payload):
    frames = [(1, b'{"action":"serverinfo"}'), (1, payload)]

    class RawSocket:
        def __init__(self):
            self.closed = False

        def send_text(self, text):
            pass

        def recv(self, deadline):
            return frames.pop(0) if frames else None

        def close(self):
            self.closed = True

    socket = MeshCentralProcessSocket(
        login_user="operator", password_provider=lambda: "op3rator-secret",
        websocket_factory=lambda *args: RawSocket(),
    )
    with pytest.raises(MeshCentralSysInfoReadFailure) as caught:
        socket.sysinfo(sysinfo_frame(NODE, TAG))
    assert caught.value.code == SYSINFO_SHAPE
    assert payload.decode("utf-8", "replace") not in str(caught.value)



# ---- identical upstream noinfo replies (#8634 follow-up) ---------------------
def _upstream_noinfo(node=NODE, tag=TAG):
    return {"action": "getsysinfo", "nodeid": node, "tag": tag,
            "noinfo": True, "result": "Invalid device id"}


@pytest.mark.parametrize("node", [NODE, "synthetic-pc-one", "node/domain/synthetic-pc-one"])
def test_noinfo_with_same_rights_gate_passed_means_no_stored_info(node):
    resolved = node if node.startswith("node/") else NODE
    probe_tag = "padiem-sysinfo-probe"
    socket, opened = _socket([
        {"action": "serverinfo"}, _upstream_noinfo(resolved),
        {"action": "getnetworkinfo", "nodeid": "node//other", "netif": None, "netif2": None},
        {"action": "getnetworkinfo", "nodeid": resolved, "netif": None, "netif2": None},
    ])
    with patch("kagent.local_agent_meshcentral_sysinfo_port.new_sysinfo_tag",
               side_effect=[TAG, probe_tag]):
        port = MeshCentralSysInfoPort(send=socket.sysinfo)
        assert port.read_commit_date(node) == (None, "info_not_stored")
    fake = opened[0][0]
    assert [json.loads(s) for s in fake.sent] == [
        sysinfo_frame(node, TAG),
        {"action": "getnetworkinfo", "nodeid": resolved, "tag": probe_tag},
    ]
    assert fake.closed


def test_noinfo_with_same_rights_gate_denied_does_not_claim_missing_document():
    probe_tag = "padiem-sysinfo-probe"
    denied = {"action": "getnetworkinfo", "nodeid": NODE, "tag": probe_tag,
              "noinfo": True, "result": "Invalid device id"}
    socket, opened = _socket([{"action": "userinfo"}, _upstream_noinfo(),
                              {**denied, "tag": "another-tag"}, denied])
    with patch("kagent.local_agent_meshcentral_sysinfo_port.new_sysinfo_tag",
               side_effect=[TAG, probe_tag]):
        port = MeshCentralSysInfoPort(send=socket.sysinfo)
        assert port.read_commit_date(NODE) == (None, "info_node_unavailable")
    assert opened[0][0].closed


@pytest.mark.parametrize("extra", [
    [],
    [{"action": "getnetworkinfo", "nodeid": "node//other", "netif": {}, "netif2": {}}],
    [{"action": "getnetworkinfo", "nodeid": NODE, "tag": "wrong",
      "netif": None, "netif2": None}],
    [{"action": "getnetworkinfo", "nodeid": NODE, "netif": None}],
])
def test_unanswered_or_unmatched_probe_stays_inconclusive(extra):
    socket, _ = _socket([{"action": "serverinfo"}, _upstream_noinfo(), *extra])
    with patch("kagent.local_agent_meshcentral_sysinfo_port.new_sysinfo_tag",
               side_effect=[TAG, "padiem-sysinfo-probe"]):
        assert MeshCentralSysInfoPort(send=socket.sysinfo).read_commit_date(NODE) == (
            None, "info_unavailable")


def test_mismatched_sysinfo_node_never_triggers_probe():
    socket, opened = _socket([{"action": "serverinfo"}, _upstream_noinfo("node//other")])
    with patch("kagent.local_agent_meshcentral_sysinfo_port.new_sysinfo_tag", return_value=TAG):
        assert MeshCentralSysInfoPort(send=socket.sysinfo).read_commit_date(NODE) == (
            None, "info_unavailable")
    assert len(opened[0][0].sent) == 1


@pytest.mark.parametrize("code", ["info_not_stored", "info_node_unavailable"])
@pytest.mark.parametrize("binary_has_date", [True, False])
def test_classified_noinfo_preserves_binary_fallback_and_bounded_log(capsys, code, binary_has_date):
    sysinfo = Mock(read_commit_date=Mock(return_value=(None, code)))
    read = Mock(read_bytes=Mock(return_value=version_resource_exe() if binary_has_date else b""))
    fallback = HelperStatusReadFallback(
        post=Mock(return_value=(200, {"ok": True})), read_port=read, sysinfo_port=sysinfo,
    )
    state = dict(READY)
    fallback._complete_mesh_agent_version(NODE, NODE, state)
    assert read.read_bytes.call_count == (1 if binary_has_date else 2)
    assert state.get("mesh_agent_version") == (VALID if binary_has_date else None)
    logs = capsys.readouterr().out
    assert f"helper_ready_agent_version read={'observed' if binary_has_date else code}" in logs
    assert NODE not in logs
