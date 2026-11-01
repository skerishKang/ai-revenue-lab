"""Actual Mesh executor scheduling, with only the PC/network ports substituted."""
import threading
import time
from types import SimpleNamespace

import pytest

from claw_connect.background_jobs import RemoteBackgroundJobs
from kagent.local_agent_oracle_mesh_executor import (
    CANCEL_PATH, LEASE_RENEW_PATH, POLL_PATH, RESULT_PATH,
    OracleMeshChannelRefused, OracleMeshExecutor,
)


def dispatch(number=1, *, node="node-a", owner="sub_alice", kind="command"):
    return {
        "dispatch_id": "dispatch-%s" % number, "nonce": "nonce-%s" % number,
        "node_ref": node, "file_path": "readme.txt", "command_id": "command-%s" % number,
        "run_id": "run-a", "kind": kind, "command_text": "approved-file-operation",
        "background": True, "owner_ref": owner,
    }


class Channel:
    def __init__(self, rows):
        self.rows = list(rows)
        self.results = []
        self.renewed = threading.Event()
        self.cancel = False
        self.fail_result_once = False

    def __call__(self, path, payload):
        if path == POLL_PATH:
            return 200, {"ok": True, "dispatch": self.rows.pop(0) if self.rows else None}
        if path == LEASE_RENEW_PATH:
            self.renewed.set()
            return 200, {"ok": True}
        if path == CANCEL_PATH:
            return 200, {"ok": True, "cancelled": self.cancel}
        if path == RESULT_PATH:
            self.results.append(dict(payload))
            if self.fail_result_once:
                self.fail_result_once = False
                return 503, {"ok": False}
            return 200, {"ok": True}
        return 200, {"ok": True, "working": False}


class CommandPort:
    def __init__(self):
        self.called = threading.Event()
        self.release = threading.Event()
        self.calls = []

    def run_command(self, **kwargs):
        self.calls.append(kwargs)
        self.called.set()
        while not self.release.wait(.005):
            if kwargs["cancel_probe"]():
                return SimpleNamespace(termination="cancelled", exit_code=None, output=b"stopped")
        return SimpleNamespace(termination="exited", exit_code=0, output=b"complete result")


class ReadPort:
    def __init__(self):
        self.calls = []

    def read_bytes(self, **kwargs):
        self.calls.append(kwargs)
        return b"approved read"


def executor(tmp_path, channel, command=None, read=None):
    return OracleMeshExecutor(
        chat_origin="https://chat.example", channel_secret="synthetic-test-channel-credential",
        transport=channel, read_port=read or ReadPort(), command_port=command or CommandPort(),
        pending_dir=str(tmp_path),
    )


def ready(manager, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        results = manager.pending_results()
        if results:
            return results
        time.sleep(.005)
    raise AssertionError("background execution did not finish")


def test_real_executor_returns_while_command_runs_keeps_lease_and_retries_same_output(tmp_path, monkeypatch):
    monkeypatch.setattr("kagent.local_agent_oracle_mesh_executor.RENEW_INTERVAL_SECONDS", .01)
    channel, command = Channel([dispatch()]), CommandPort()
    runtime = executor(tmp_path, channel, command)
    started = runtime.run_once()
    assert started == {"ok": True, "background": True, "job_id": "dispatch-1", "state": "running"}
    assert command.called.wait(1)
    assert channel.renewed.wait(1), "background command must retain its queue lease"
    assert runtime.active_dispatch_ids() == ("dispatch-1",)
    # Another poll round can complete while the selected PC command is still waiting.
    assert runtime.run_once() is None
    assert len(command.calls) == 1
    assert command.calls[0]["timeout_seconds"] is None
    command.release.set()
    ready(runtime._background_manager())
    assert not runtime.active_dispatch_ids()
    channel.fail_result_once = True
    failed = runtime.run_once()
    assert failed["resend_pending"] is True
    assert runtime.run_once()["ok"] is True
    assert len(command.calls) == 1
    assert channel.results[0] == channel.results[1]
    assert channel.results[0]["content_utf8"] == "complete result"
    assert runtime._background_manager().pending_results() == []


def test_same_pc_serializes_while_other_pc_progresses_and_owner_stop_is_preserved(tmp_path):
    channel, command = Channel([dispatch(1), dispatch(2), dispatch(3, node="node-b")]), CommandPort()
    runtime = executor(tmp_path, channel, command)
    runtime.run_once()
    assert command.called.wait(1)
    runtime.run_once()
    runtime.run_once()
    end = time.monotonic() + 1
    while len(command.calls) < 2 and time.monotonic() < end:
        time.sleep(.005)
    assert {call["dispatch_id"] for call in command.calls} == {"dispatch-1", "dispatch-3"}
    assert set(runtime.active_dispatch_ids()) == {"dispatch-1", "dispatch-3"}
    channel.cancel = True
    end = time.monotonic() + 2
    while len(runtime._background_manager().pending_results()) < 3 and time.monotonic() < end:
        time.sleep(.005)
    outcomes = runtime._background_manager().pending_results()
    assert len(outcomes) == 3
    assert all(record["termination"] == "cancelled" for record, _ in outcomes)
    assert not runtime.active_dispatch_ids()


def test_background_read_uses_existing_read_port_without_command_fallback(tmp_path):
    channel, command, read = Channel([dispatch(kind="read")]), CommandPort(), ReadPort()
    runtime = executor(tmp_path, channel, command, read)
    assert runtime.run_once()["job_id"] == "dispatch-1"
    ready(runtime._background_manager())
    assert runtime.run_once()["ok"] is True
    assert channel.results[0]["content_utf8"] == "approved read"
    assert read.calls == [{"node_ref": "node-a", "file_path": "readme.txt"}]
    assert command.calls == []


@pytest.mark.parametrize("change", [
    {"background": "true"}, {"owner_ref": None}, {"background": True, "kind": "desktop"},
])
def test_untrusted_background_shape_is_refused_before_execution(tmp_path, change):
    row = {**dispatch(), **change}
    channel, command = Channel([row]), CommandPort()
    runtime = executor(tmp_path, channel, command)
    with pytest.raises(OracleMeshChannelRefused):
        runtime.run_once()
    assert not command.calls


def test_remote_receipts_are_owner_scoped_and_restart_never_replays(tmp_path):
    calls = []
    def run(payload, *, cancel_probe):
        calls.append(payload["dispatch_id"])
        return {"termination": "exited", "exit_code": 0, "body": "기록".encode("utf-8")}
    manager = RemoteBackgroundJobs(tmp_path, runner=run)
    owner = '["sub_alice","node-a","run-a"]'
    other = '["sub_bob","node-a","run-a"]'
    manager.start(dispatch(), owner=owner)
    ready(manager)
    assert manager.output("dispatch-1", 0, 100, owner=owner) == "기록"
    assert manager.list(other) == []
    for read in [
        lambda: manager.status("dispatch-1", owner=other),
        lambda: manager.output("dispatch-1", 0, 100, owner=other),
        lambda: manager.kill("dispatch-1", owner=other),
    ]:
        with pytest.raises(KeyError):
            read()
    restored = RemoteBackgroundJobs(tmp_path, runner=run)
    assert restored.pending_results()[0][1] == "기록".encode("utf-8")
    assert restored.start({**dispatch(), "nonce": "reclaimed-nonce"}, owner=owner)["state"] == "done"
    assert calls == ["dispatch-1"]
    assert restored.pending_results()[0][0]["dispatch"]["nonce"] == "reclaimed-nonce"


def test_interrupted_remote_receipt_is_failed_and_never_reexecuted(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def run(payload, *, cancel_probe):
        calls.append(payload["dispatch_id"])
        entered.set()
        release.wait(2)
        return {"termination": "exited", "exit_code": 0, "body": b"done"}
    manager = RemoteBackgroundJobs(tmp_path, runner=run)
    manager.start(dispatch(), owner="owner")
    assert entered.wait(1)
    # Simulate restart from a durable running receipt; no process is spawned again.
    restored = RemoteBackgroundJobs(tmp_path, runner=run)
    assert restored.status("dispatch-1", owner="owner")["state"] == "failed"
    assert restored.start(dispatch(), owner="owner")["state"] == "failed"
    assert calls == ["dispatch-1"]
    release.set()


def test_local_job_kill_requests_existing_remote_cancellation_probe(tmp_path):
    entered = threading.Event()
    def run(payload, *, cancel_probe):
        entered.set()
        end = time.monotonic() + 2
        while not cancel_probe() and time.monotonic() < end:
            time.sleep(.005)
        return {"termination": "cancelled", "exit_code": None, "body": b""}
    manager = RemoteBackgroundJobs(tmp_path, runner=run)
    manager.start(dispatch(), owner="owner")
    assert entered.wait(1)
    assert manager.kill("dispatch-1", owner="owner") is True
    assert ready(manager)[0][0]["state"] == "killed"
    assert manager.kill("dispatch-1", owner="owner") is False
