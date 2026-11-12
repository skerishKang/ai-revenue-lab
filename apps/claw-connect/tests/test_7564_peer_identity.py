"""Pipe identity decisions, restoration and admission order without OS privileges."""
from __future__ import annotations

import ast
import ctypes
import inspect
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import textwrap

import pytest

from claw_connect import user_helper_peer as peer
from claw_connect import user_helper_service as service
from claw_connect import user_session_helper as helper


SECRET = b"peer-identity-unit-test-secret"
CLAW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CLAW_ROOT.parents[1]


@pytest.fixture(autouse=True)
def _fake_system_executables(monkeypatch):
    """No pipeline decision depends on the host's executable locations."""
    monkeypatch.setattr(helper, "system_executable",
                        lambda name: "/fake-padiem-system32/" + name)
    monkeypatch.setattr(helper, "windows_powershell_executable",
                        lambda: "/fake-padiem-system32/WindowsPowerShell/v1.0/powershell.exe")


class FakeApi:
    def __init__(self, *, sid=peer.SYSTEM_SID, impersonated=True, token=123,
                 raises_at=None, exception=None, reverts=True):
        self.sid = sid
        self.impersonated = impersonated
        self.token = token
        self.raises_at = raises_at
        self.exception = exception or RuntimeError("private API detail")
        self.reverts = reverts
        self.events = []
        self.active = False

    def _call(self, name):
        self.events.append(name)
        if name == self.raises_at:
            raise self.exception

    def impersonate(self, handle):
        assert handle == 456
        self._call("impersonate")
        self.active = self.impersonated
        return self.impersonated

    def open_thread_token(self):
        assert self.active
        self._call("open_token")
        return self.token

    def token_user_sid(self, token):
        assert self.active and token == self.token
        self._call("token_user")
        return self.sid

    def revert(self):
        self._call("revert")
        if self.reverts:
            self.active = False
        return self.reverts

    def close_token(self, token):
        assert not self.active, "the token must be closed after restoration"
        assert token == self.token
        self._call("close_token")


@pytest.mark.parametrize(("sid", "expected"), [
    pytest.param("S-1-5-18", None, id="SYSTEM"),
    pytest.param("S-1-5-21-111-222-333-1001", peer.PEER_NOT_SYSTEM, id="ordinary-user"),
    pytest.param("S-1-5-21-111-222-333-500", peer.PEER_NOT_SYSTEM, id="administrator-user"),
    pytest.param("S-1-5-32-544", peer.PEER_NOT_SYSTEM, id="administrators-group-is-not-user"),
    pytest.param("S-1-5-19", peer.PEER_NOT_SYSTEM, id="LocalService"),
    pytest.param("S-1-5-20", peer.PEER_NOT_SYSTEM, id="NetworkService"),
    pytest.param("", peer.PEER_IDENTITY_UNAVAILABLE, id="empty-SID"),
    pytest.param(None, peer.PEER_IDENTITY_UNAVAILABLE, id="missing-SID"),
])
def test_only_system_token_user_is_admitted_and_every_result_restores(sid, expected):
    api = FakeApi(sid=sid)
    assert peer.verify_system_pipe_client(456, api=api) == expected
    assert api.events == ["impersonate", "open_token", "token_user", "revert", "close_token"]
    assert not api.active


@pytest.mark.parametrize(("options", "expected", "events"), [
    ({"impersonated": False}, peer.PEER_IMPERSONATION_FAILED, ["impersonate", "revert"]),
    ({"token": None}, peer.PEER_TOKEN_UNAVAILABLE, ["impersonate", "open_token", "revert"]),
    ({"raises_at": "impersonate"}, peer.PEER_IDENTITY_UNAVAILABLE, ["impersonate", "revert"]),
    ({"raises_at": "open_token"}, peer.PEER_IDENTITY_UNAVAILABLE,
     ["impersonate", "open_token", "revert"]),
    ({"raises_at": "token_user"}, peer.PEER_IDENTITY_UNAVAILABLE,
     ["impersonate", "open_token", "token_user", "revert", "close_token"]),
])
def test_api_failures_refuse_and_restore(options, expected, events):
    api = FakeApi(**options)
    assert peer.verify_system_pipe_client(456, api=api) == expected
    assert api.events == events
    assert not api.active


def test_nonordinary_exception_still_restores_before_it_propagates():
    api = FakeApi(raises_at="token_user", exception=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        peer.verify_system_pipe_client(456, api=api)
    assert api.events[-2:] == ["revert", "close_token"]
    assert not api.active


class ExitCalled(BaseException):
    pass


@pytest.mark.parametrize("revert_mode", ["false", "exception", "base_exception"])
@pytest.mark.parametrize("sid", [peer.SYSTEM_SID, "S-1-5-19"])
def test_revert_failure_exits_without_cleanup_or_return(monkeypatch, revert_mode, sid):
    api = FakeApi(sid=sid, reverts=False)
    if revert_mode != "false":
        api.raises_at = "revert"
        api.exception = RuntimeError("revert failed") if revert_mode == "exception" else KeyboardInterrupt()
    exits = []

    def exit_now(code):
        exits.append(code)
        raise ExitCalled

    monkeypatch.setattr(peer.os, "_exit", exit_now)
    with pytest.raises(ExitCalled):
        peer.verify_system_pipe_client(456, api=api)
    assert exits == [peer.REVERT_FAILURE_EXIT_CODE]
    assert api.events == ["impersonate", "open_token", "token_user", "revert"]
    assert api.active


def test_open_thread_token_uses_query_only_and_open_as_self():
    calls = []

    class Advapi:
        def OpenThreadToken(self, thread, access, open_as_self, output):
            calls.append((thread.value, access, open_as_self))
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 789
            return 1

    api = peer._WindowsPeerApi.__new__(peer._WindowsPeerApi)
    api.advapi = Advapi()
    assert api.open_thread_token().value == 789
    assert calls == [(ctypes.c_void_p(-2).value, 0x0008, True)]


def test_token_query_reads_token_user_not_group_membership(monkeypatch):
    calls = []
    sid_text = ctypes.create_unicode_buffer(peer.SYSTEM_SID)
    freed = []

    class Advapi:
        def GetTokenInformation(self, token, info_class, buffer, size, needed):
            calls.append((token, info_class, buffer is None))
            ctypes.cast(needed, ctypes.POINTER(ctypes.c_ulong))[0] = ctypes.sizeof(peer._SidAndAttributes)
            if buffer is None:
                assert size == 0
                return 0
            assert size == ctypes.sizeof(peer._SidAndAttributes)
            user = ctypes.cast(buffer, ctypes.POINTER(peer._SidAndAttributes)).contents
            user.sid = 901
            return 1

        def ConvertSidToStringSidW(self, sid, output):
            assert sid == 901
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.addressof(sid_text)
            return 1

    class Kernel:
        def LocalFree(self, pointer):
            freed.append(pointer.value)

    monkeypatch.setattr(peer.ctypes, "get_last_error", lambda: 122, raising=False)
    api = peer._WindowsPeerApi.__new__(peer._WindowsPeerApi)
    api.advapi, api.kernel = Advapi(), Kernel()
    assert api.token_user_sid(789) == peer.SYSTEM_SID
    assert calls == [(789, 1, True), (789, 1, False)]
    assert freed == [ctypes.addressof(sid_text)]


def signed_frame(number=1, *, nonce=None, shell="whoami"):
    payload = {
        "request_id": "req_%032x" % number, "nonce": "", "shell": shell,
        "command": "whoami" if shell == "whoami" else "e30=",
        "timeout_seconds": 0, "cwd": None, "distro": None,
    }
    request = helper.parse_request(payload)
    payload["nonce"] = nonce if nonce is not None else helper.request_nonce(SECRET, request)
    return service.encode_frame(payload)


class Connection:
    def __init__(self, frame, events=None):
        self.frame = frame
        self.offset = 0
        self.events = events if events is not None else []
        self.read_sizes = []
        self.writes = []
        self.closed = 0
        self._handle = 456

    def read_exact(self, size):
        self.events.append("header" if self.offset == 0 else "body")
        self.read_sizes.append(size)
        chunk = self.frame[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk

    def write_all(self, data):
        self.events.append("write")
        self.writes.append(data)

    def close(self):
        self.events.append("close")
        self.closed += 1


class Listener:
    def __init__(self, connections):
        self.connections = iter(connections)

    def accept(self, timeout_seconds):
        return next(self.connections, None)

    def close(self):
        pass


def test_header_identity_restoration_body_hmac_replay_and_runner_order(monkeypatch):
    events = []
    connection = Connection(signed_frame(), events)
    api = FakeApi()
    parse = service.parse_request
    verify = service.verify_nonce

    def verifier(current):
        events.append("verify_peer")
        result = peer.verify_system_pipe_client(current._handle, api=api)
        assert not api.active
        events.append("restored")
        return result

    def parse_request(payload):
        assert not api.active
        events.append("parse")
        return parse(payload)

    def verify_nonce(secret, request):
        assert not api.active
        events.append("hmac")
        return verify(secret, request)

    class Guard:
        def accept(self, request_id):
            assert not api.active
            events.append("replay")
            return True

    def runner(*args):
        assert not api.active
        events.append("runner")
        return 0, b"ok", b""

    monkeypatch.setattr(service, "parse_request", parse_request)
    monkeypatch.setattr(service, "verify_nonce", verify_nonce)
    assert service.handle_connection(connection, secret=SECRET, guard=Guard(),
                                     runner=runner, peer_verifier=verifier) == "served"
    assert events == ["header", "verify_peer", "restored", "body", "parse",
                      "hmac", "replay", "runner", "write", "close"]
    assert connection.read_sizes == [4, len(connection.frame) - 4]
    assert connection.closed == 1


@pytest.mark.parametrize("shell", ["whoami", "session"])
@pytest.mark.parametrize("failure", ["non_system", "exception", "unsafe_reason", "false_result"])
def test_refusal_reads_no_body_runs_nothing_and_logs_only_a_reason(monkeypatch, caplog, shell, failure):
    frame = signed_frame(shell=shell)
    connection = Connection(frame)

    def forbidden(*args, **kwargs):
        pytest.fail("request processing reached before peer admission")

    class Guard:
        accept = forbidden

    class Manager:
        handle_command = forbidden

    def verifier(current):
        assert current.offset == 4
        if failure == "exception":
            raise RuntimeError("private SID S-1-5-21-123 and command data")
        if failure == "unsafe_reason":
            return "private SID S-1-5-21-123 and command data"
        if failure == "false_result":
            return False
        return peer.PEER_NOT_SYSTEM

    monkeypatch.setattr(service, "parse_request", forbidden)
    monkeypatch.setattr(service, "verify_nonce", forbidden)
    assert service.handle_connection(connection, secret=SECRET, guard=Guard(),
                                     runner=forbidden, sessions=Manager(),
                                     peer_verifier=verifier) == "refused"
    assert connection.read_sizes == [4]
    assert connection.offset == 4 and connection.writes == [] and connection.closed == 1
    expected = peer.PEER_NOT_SYSTEM if failure == "non_system" else peer.PEER_IDENTITY_UNAVAILABLE
    assert [record.getMessage() for record in caplog.records] == [expected]


@pytest.mark.parametrize("error", [
    OSError("private transport error"),
    helper.UserHelperError(helper.USER_HELPER_TIMEOUT, "private timeout detail"),
])
def test_header_read_failure_closes_without_a_reply_or_identity_attempt(caplog, error):
    class BrokenHeader(Connection):
        def read_exact(self, size):
            self.read_sizes.append(size)
            raise error

    def forbidden(current):
        pytest.fail("identity attempt without a completed header read")

    connection = BrokenHeader(b"")
    assert service.handle_connection(connection, secret=SECRET, guard=helper.ReplayGuard(),
                                     peer_verifier=forbidden) == "refused"
    assert connection.read_sizes == [4] and connection.writes == [] and connection.closed == 1
    assert [record.getMessage() for record in caplog.records] == ["peer_header_unavailable"]


@pytest.mark.parametrize("length", [0, service.MAX_FRAME_BYTES + 1, 0xffffffff])
@pytest.mark.parametrize("admitted", [False, True])
def test_even_invalid_lengths_are_interpreted_after_peer_verification(length, admitted):
    connection = Connection(struct.pack(">I", length))

    def verifier(current):
        current.events.append("verify_peer")
        assert current.read_sizes == [4] and current.writes == []
        return None if admitted else peer.PEER_NOT_SYSTEM

    assert service.handle_connection(connection, secret=SECRET, guard=helper.ReplayGuard(),
                                     peer_verifier=verifier) == "refused"
    assert connection.events[:2] == ["header", "verify_peer"]
    assert connection.read_sizes == [4] and connection.closed == 1
    assert bool(connection.writes) is admitted


def test_peer_admission_keeps_hmac_and_replay_checks():
    guard = helper.ReplayGuard()
    calls = []

    def runner(*args):
        calls.append(args)
        return 0, b"ok", b""

    connections = [Connection(signed_frame(nonce="0" * 64)),
                   Connection(signed_frame()), Connection(signed_frame())]
    outcomes = [service.handle_connection(connection, secret=SECRET, guard=guard,
                                          runner=runner, peer_verifier=lambda current: None)
                for connection in connections]
    assert outcomes == ["refused", "served", "refused"]
    assert len(calls) == 1
    assert all(connection.closed == 1 for connection in connections)
    for connection in (connections[0], connections[2]):
        reply = json.loads(connection.writes[0][4:])
        assert reply["error_code"] == helper.USER_HELPER_REFUSED


@pytest.mark.parametrize("thread_limit", [0, 1])
def test_a_refusal_counts_once_and_the_next_connection_is_served(monkeypatch, thread_limit):
    monkeypatch.setattr(service, "MAX_CONNECTION_THREADS", thread_limit)
    rejected, accepted = Connection(signed_frame()), Connection(signed_frame(2))
    calls = []

    def runner(*args):
        calls.append(args)
        return 0, b"ok", b""

    stats = service.serve_pipe(
        device_id="unit-peer-identity", secret=SECRET,
        listener=Listener([rejected, accepted]), runner=runner, sessions=object(), max_requests=2,
        peer_verifier=lambda current: peer.PEER_NOT_SYSTEM if current is rejected else None,
    )
    assert (stats.served, stats.refused) == (1, 1)
    assert rejected.read_sizes == [4] and rejected.writes == []
    assert rejected.closed == accepted.closed == 1
    assert len(calls) == 1


def test_unavailable_os_fails_closed_and_only_explicit_code_injection_allows(monkeypatch):
    monkeypatch.setattr(peer.sys, "platform", "not-windows")
    assert peer.verify_system_pipe_client(456) == peer.PEER_IDENTITY_UNAVAILABLE
    rejected = Connection(signed_frame())
    assert service.handle_connection(rejected, secret=SECRET,
                                     guard=helper.ReplayGuard()) == "refused"
    assert rejected.read_sizes == [4] and rejected.writes == []
    accepted = Connection(signed_frame())
    assert service.handle_connection(accepted, secret=SECRET, guard=helper.ReplayGuard(),
                                     runner=lambda *args: (0, b"ok", b""),
                                     peer_verifier=lambda current: None) == "served"


def test_missing_handle_never_implicitly_admits_a_fake_connection():
    connection = Connection(signed_frame())
    del connection._handle
    assert service.handle_connection(connection, secret=SECRET,
                                     guard=helper.ReplayGuard()) == "refused"
    assert connection.read_sizes == [4] and connection.writes == [] and connection.closed == 1


def test_runtime_configuration_cannot_supply_the_peer_verifier(monkeypatch):
    for name in ("PADIEM_USER_HELPER_DISABLE_AUTH", "PADIEM_USER_HELPER_SKIP_PEER_CHECK",
                 "PADIEM_USER_HELPER_PEER_VERIFIER"):
        monkeypatch.setenv(name, "1")
    calls = []
    monkeypatch.setattr(service, "load_secret", lambda path: SECRET)
    monkeypatch.setattr(service, "serve_pipe",
                        lambda **kwargs: calls.append(kwargs) or service.ServeStats())
    assert service.main(["--device-id", "unit-peer", "--max-requests", "1"]) == 0
    assert calls == [{"device_id": "unit-peer", "secret": SECRET, "max_requests": 1}]
    with pytest.raises(SystemExit) as error:
        service.main(["--device-id", "unit-peer", "--disable-peer-check"])
    assert error.value.code == 2


def test_source_has_no_environment_cli_or_config_switch_for_peer_admission():
    for function in (service.handle_connection, service.serve_pipe):
        assert inspect.signature(function).parameters["peer_verifier"].default is None
    service_tree = ast.parse(inspect.getsource(service))
    main = next(node for node in service_tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    flags = [arg.value for node in ast.walk(main)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr == "add_argument"
             for arg in node.args if isinstance(arg, ast.Constant)]
    assert flags == ["--device-id", "--secret-file", "--max-requests"]
    production_calls = [node for node in ast.walk(main)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == "serve_pipe"]
    assert len(production_calls) == 1
    assert {kw.arg for kw in production_calls[0].keywords} == {"device_id", "secret", "max_requests"}
    protected = [ast.parse(inspect.getsource(peer))]
    protected.extend(ast.parse(inspect.getsource(function)) for function in (
        service.verify_system_peer, service.handle_connection, service.serve_pipe,
    ))
    for tree in protected:
        assert not any(isinstance(node, ast.Attribute) and node.attr in {
            "environ", "getenv", "argv", "parse_args", "get_config", "load_config",
        } for node in ast.walk(tree))
    entry_tree = ast.parse((CLAW_ROOT / "user_helper_entry.py").read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(entry_tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "helper_main"]
    assert len(calls) == 1 and not calls[0].args and not calls[0].keywords


@pytest.mark.parametrize(("thread_limit", "thread_name"), [
    (1, "padiem-helper-connection"), (0, "MainThread"),
])
def test_revert_failure_terminates_the_entire_helper_process(tmp_path, thread_limit, thread_name):
    """Exercise real os._exit from both service paths in an expendable process."""
    marker = tmp_path / "continued-after-revert-failure"
    script = textwrap.dedent("""
        import sys
        import threading
        from pathlib import Path
        from claw_connect import user_helper_peer as peer
        from claw_connect import user_helper_service as service

        marker = Path(sys.argv[1])
        def continued():
            marker.write_text('unexpected work', encoding='utf-8')
        class Api:
            def impersonate(self, handle): return True
            def open_thread_token(self): return 123
            def token_user_sid(self, token): return peer.SYSTEM_SID
            def revert(self): return False
            def close_token(self, token): continued()
        class Connection:
            _handle = 456
            def read_exact(self, size):
                print(threading.current_thread().name, flush=True)
                assert size == 4
                return b'\\x00\\x00\\x00\\x01'
            def write_all(self, data): continued()
            def close(self): continued()
        class Listener:
            def accept(self, timeout_seconds): return Connection()
            def close(self): continued()
        peer._WindowsPeerApi = Api
        service.MAX_CONNECTION_THREADS = int(sys.argv[2])
        service.serve_pipe(device_id='unit-fatal-peer', secret=b'unit-secret',
                           listener=Listener(), sessions=object(), max_requests=1)
        continued()
    """)
    environment = os.environ.copy()
    paths = [str(CLAW_ROOT), str(REPO_ROOT / "packages" / "padiem-ai-core"),
             str(REPO_ROOT / "packages" / "padiem-control-plane")]
    environment["PYTHONPATH"] = os.pathsep.join(paths + [environment.get("PYTHONPATH", "")])
    result = subprocess.run([sys.executable, "-c", script, str(marker), str(thread_limit)],
                            cwd=tmp_path, env=environment, capture_output=True, timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == peer.REVERT_FAILURE_EXIT_CODE, result.stderr.decode("utf-8", "replace")
    assert result.stdout.decode("utf-8").strip() == thread_name
    assert not marker.exists()
