"""Real temporary pipes and thread-token restoration on Windows.

The acceptance-path test substitutes only the SID returned by an actual OS
token query. It proves real impersonation/reversion, not a real SYSTEM client.
No service, scheduled task, installed helper, or command process is used.
"""
from __future__ import annotations

import ctypes
import struct
import sys
import threading
import time
import uuid

import pytest

from claw_connect import user_helper_peer as peer
from claw_connect import user_helper_service as service
from claw_connect import user_session_delegation as delegation
from claw_connect import user_session_helper as helper


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows token and pipe APIs")
SECRET = b"temporary-peer-restoration-test-secret"


def _thread_token_state():
    """Observe token presence without putting a SID or account name in a failure."""
    api = peer._WindowsPeerApi()
    token = api.open_thread_token()
    if token:
        api.close_token(token)
        return "thread_token_present"
    assert ctypes.get_last_error() == 1008, "OpenThreadToken failed without ERROR_NO_TOKEN"
    return None


def _require_non_system_process():
    api = peer._WindowsPeerApi()
    api.advapi.OpenProcessToken.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_void_p),
    ]
    api.advapi.OpenProcessToken.restype = ctypes.c_int
    token = ctypes.c_void_p()
    assert api.advapi.OpenProcessToken(ctypes.c_void_p(-1), 0x0008, ctypes.byref(token))
    try:
        is_system = api.token_user_sid(token) == peer.SYSTEM_SID
    finally:
        api.close_token(token)
    if is_system:
        pytest.skip("this refusal test requires a non-SYSTEM test process")


def _frame():
    request = helper.HelperRequest(
        request_id="req_" + uuid.uuid4().hex, nonce="", shell="whoami",
        command="whoami", timeout_seconds=30,
    )
    return service.encode_frame({
        "request_id": request.request_id,
        "nonce": helper.request_nonce(SECRET, request),
        "shell": request.shell, "command": request.command,
        "cwd": request.cwd, "distro": request.distro,
        "timeout_seconds": request.timeout_seconds,
    })


def _open_client(device_id, identification):
    path = helper.pipe_path(device_id)
    if not identification:
        return delegation.open_pipe_connection(path)
    kernel = service._kernel32()
    kernel.WaitNamedPipeW(path, 2000)
    handle = kernel.CreateFileW(
        path, 0x80000000 | 0x40000000, 0, None, 3,
        0x00100000 | 0x00010000,  # SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION
        None,
    )
    if service._is_invalid_handle(handle):
        raise OSError(ctypes.get_last_error(), "the temporary test pipe did not open")
    return service.WindowsPipeConnection(handle)


class _ObservedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.read_sizes = []
        self.read_bytes = []
        self.read_tokens = []
        self.writes = []
        self.close_count = 0
        self.close_token = "not_closed"
        self.closed = threading.Event()

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def read_exact_bounded(self, size):
        self.read_sizes.append(size)
        self.read_tokens.append(_thread_token_state())
        data = self.connection.read_exact_bounded(size)
        self.read_bytes.append(len(data))
        return data

    def write_all(self, data):
        self.writes.append(data)
        self.connection.write_all(data)

    def close(self):
        self.close_count += 1
        self.close_token = _thread_token_state()
        self.connection.close()
        self.closed.set()


class _ObservedListener(service.WindowsPipeListener):
    def __init__(self, device_id):
        self.connections = []
        self.release_counts = []
        super().__init__(device_id)

    def accept(self, timeout_seconds):
        connection = super().accept(timeout_seconds)
        if connection is None:
            return None
        observed = _ObservedConnection(connection)
        self.connections.append(observed)
        return observed

    def _release_instance(self, handle):
        before = self._live
        super()._release_instance(handle)
        self.release_counts.append((before, self._live))


def _start_server(listener, device_id, runner, **options):
    stop = threading.Event()
    result = {}
    errors = []

    def serve():
        try:
            result["stats"] = service.serve_pipe(
                device_id=device_id, secret=SECRET, listener=listener,
                runner=runner, max_requests=2, should_stop=stop.is_set, **options,
            )
        except BaseException as exc:
            errors.append(type(exc).__name__)

    thread = threading.Thread(target=serve, daemon=True, name="peer-test-accept")
    thread.start()
    return thread, stop, result, errors


def _finish_server(thread, stop, listener, device_id):
    stop.set()
    if thread.is_alive():
        # Wake only this test's pending accept; a disconnected client cannot
        # execute a command, and the normal read timeout bounds any worker.
        try:
            delegation.open_pipe_connection(helper.pipe_path(device_id)).close()
        except (OSError, helper.UserHelperError):
            pass
    thread.join(timeout=12)
    try:
        assert not thread.is_alive(), "the temporary helper thread did not stop"
    finally:
        listener.close()


def _assert_closed_without_reply(client):
    deadline = time.monotonic() + service.REQUEST_READ_TIMEOUT_SECONDS / 2
    while time.monotonic() < deadline:
        assert client._available() == 0, "the refused connection received a frame"
        if client.peer_closed():
            return
        time.sleep(0.01)
    pytest.fail("the peer check waited for a request body")


def _assert_connection_cleanup(listener):
    assert len(listener.connections) == 2
    assert all(connection.closed.wait(2) for connection in listener.connections)
    assert [connection.close_count for connection in listener.connections] == [1, 1]
    assert [connection.close_token for connection in listener.connections] == [None, None]
    assert listener.release_counts == [(2, 1), (2, 1)]
    assert listener._live == 1, "only the pending listener instance should remain"


@pytest.mark.parametrize("thread_slots", [0, 8], ids=["accept-thread", "connection-worker"])
@pytest.mark.parametrize("identification", [False, True], ids=["default-sqos", "identification-sqos"])
def test_non_system_peer_is_refused_after_header_and_listener_recovers(
        monkeypatch, caplog, thread_slots, identification):
    _require_non_system_process()
    monkeypatch.setattr(service, "MAX_CONNECTION_THREADS", thread_slots)
    observations = []
    original_verifier = service.verify_system_peer

    def observe_default_verifier(connection):
        before = _thread_token_state()
        reason = original_verifier(connection)
        after = _thread_token_state()
        observations.append((before, after, reason, threading.get_ident()))
        return reason

    # Preserve the production check and leave peer_verifier unset: the loop's
    # default must actually call the OS verifier on each accepted connection.
    monkeypatch.setattr(service, "verify_system_peer", observe_default_verifier)
    runner_calls = []

    def runner(*args):
        runner_calls.append(args)
        return 0, b"unexpected", b""

    device_id = "test-peer-" + uuid.uuid4().hex
    listener = _ObservedListener(device_id)
    thread, stop, result, errors = _start_server(listener, device_id, runner)
    try:
        for header in (_frame()[:4], struct.pack(">I", 0xFFFFFFFF)):
            client = _open_client(device_id, identification)
            try:
                client.write_all(header)
                _assert_closed_without_reply(client)
            finally:
                client.close()
            assert listener.connections[-1].closed.wait(2)
            assert listener._live == 1
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not errors
        assert result["stats"].served == 0
        assert result["stats"].refused == 2
        assert runner_calls == []
        assert len(observations) == 2
        assert [item[:3] for item in observations] == [(None, None, peer.PEER_NOT_SYSTEM)] * 2
        assert all((item[3] == thread.ident) == (thread_slots == 0) for item in observations)
        assert [connection.read_sizes for connection in listener.connections] == [[4], [4]]
        assert [connection.read_bytes for connection in listener.connections] == [[4], [4]]
        assert [connection.writes for connection in listener.connections] == [[], []]
        messages = [record.getMessage() for record in caplog.records if record.name == service.__name__]
        assert messages == [peer.PEER_NOT_SYSTEM, peer.PEER_NOT_SYSTEM]
        _assert_connection_cleanup(listener)
    finally:
        _finish_server(thread, stop, listener, device_id)
    assert listener._live == 0
    assert listener.release_counts[-1] == (1, 0)


@pytest.mark.parametrize("thread_slots", [0, 8], ids=["accept-thread", "connection-worker"])
@pytest.mark.parametrize("identification", [False, True], ids=["default-sqos", "identification-sqos"])
def test_real_impersonation_restores_thread_after_injected_system_sid(
        monkeypatch, thread_slots, identification):
    """The SID verdict is fake; impersonation, token query, and revert are real."""
    _require_non_system_process()
    monkeypatch.setattr(service, "MAX_CONNECTION_THREADS", thread_slots)
    actual_non_system_reads = []
    observations = []

    class SidForRestorationProbe(peer._WindowsPeerApi):
        def token_user_sid(self, token):
            actual = super().token_user_sid(token)
            actual_non_system_reads.append(bool(actual) and actual != peer.SYSTEM_SID)
            return peer.SYSTEM_SID

    def verify_restoration(connection):
        before = _thread_token_state()
        reason = peer.verify_system_pipe_client(connection._handle, api=SidForRestorationProbe())
        after = _thread_token_state()
        observations.append((before, after, reason, threading.get_ident()))
        return reason

    runner_states = []

    def runner(argv, cwd, timeout_seconds):
        runner_states.append(_thread_token_state())
        return 0, b"fake-runner-only", b""

    device_id = "test-peer-restore-" + uuid.uuid4().hex
    listener = _ObservedListener(device_id)
    thread, stop, result, errors = _start_server(
        listener, device_id, runner, peer_verifier=verify_restoration,
    )
    try:
        for _ in range(2):
            frame = _frame()
            client = _open_client(device_id, identification)
            try:
                client.write_all(frame)
                reply = service.read_frame(client.read_exact_bounded)
                assert reply["status"] == "ok"
                assert reply["exit_code"] == 0
            finally:
                client.close()
            assert listener.connections[-1].closed.wait(2)
            assert listener.connections[-1].read_sizes == [4, len(frame) - 4]
            assert listener.connections[-1].read_tokens == [None, None]
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert not errors
        assert result["stats"].served == 2
        assert result["stats"].refused == 0
        assert actual_non_system_reads == [True, True]
        assert runner_states == [None, None]
        assert len(observations) == 2
        assert [item[:3] for item in observations] == [(None, None, None)] * 2
        assert all((item[3] == thread.ident) == (thread_slots == 0) for item in observations)
        _assert_connection_cleanup(listener)
    finally:
        _finish_server(thread, stop, listener, device_id)
    assert listener._live == 0
    assert listener.release_counts[-1] == (1, 0)
