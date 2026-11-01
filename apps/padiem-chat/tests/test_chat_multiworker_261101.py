"""Host worker preparation: shared state, nonblocking I/O and startup fences."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from app.local_r2 import LocalDiskR2, ThreadedLocalDiskR2

FIXTURE = Path(__file__).parent / "fixtures/chat_multiworker_app_261101.py"


def _mountinfo(tmp_path, filesystem):
    path = tmp_path / "mountinfo"
    path.write_text(f"1 0 0:1 / / rw - {filesystem} synthetic rw\n")
    return path


def test_worker_count_defaults_to_one_and_accepts_two_or_three():
    from app.local_server import worker_count
    assert worker_count({}) == 1
    assert worker_count({"PADIEM_CHAT_WORKERS": "2"}) == 2
    assert worker_count({"PADIEM_CHAT_WORKERS": "3"}) == 3


@pytest.mark.parametrize("invalid", ["0", "-1", "one", "1.5"])
def test_invalid_worker_count_is_rejected(invalid):
    from app.local_server import worker_count
    with pytest.raises((ValueError, RuntimeError)):
        worker_count({"PADIEM_CHAT_WORKERS": invalid})


@pytest.mark.parametrize("filesystem", ["9p", "nfs", "nfs4", "cifs", "virtiofs", "fuse.sshfs", "unknown"])
def test_multiple_workers_refuse_network_or_unverified_sqlite_filesystem(tmp_path, filesystem):
    from app.local_server import validate_multiworker_storage
    mountinfo = _mountinfo(tmp_path, filesystem)
    with pytest.raises(RuntimeError, match="multiworker_local_filesystem_required"):
        validate_multiworker_storage(tmp_path, 2, mountinfo_path=mountinfo)
    validate_multiworker_storage(tmp_path, 1, mountinfo_path=mountinfo)


def test_nested_mount_and_escaped_mount_point_are_checked(tmp_path):
    from app.local_server import validate_multiworker_storage
    storage = tmp_path / "nested data"
    storage.mkdir()
    encoded = str(storage).replace(" ", r"\040")
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - ext4 local rw\n"
        f"2 1 0:2 / {encoded} rw - 9p remote rw\n")
    with pytest.raises(RuntimeError, match="multiworker_local_filesystem_required"):
        validate_multiworker_storage(storage, 3, mountinfo_path=mountinfo)


def test_storage_symlink_cannot_hide_network_database(tmp_path):
    from app.local_server import validate_multiworker_storage
    remote = tmp_path / "remote"
    remote.mkdir()
    alias = tmp_path / "local-looking"
    alias.symlink_to(remote, target_is_directory=True)
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 / / rw - ext4 local rw\n"
                        f"2 1 0:2 / {remote} rw - 9p remote rw\n")
    with pytest.raises(RuntimeError, match="multiworker_local_filesystem_required"):
        validate_multiworker_storage(alias / "chat.sqlite3", 2, mountinfo_path=mountinfo)


def test_worker_configuration_checks_edge_replay_database_too(tmp_path):
    from app.local_server import validate_worker_configuration
    remote = tmp_path / "remote"
    remote.mkdir()
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - ext4 local rw\n"
        f"2 1 0:2 / {remote} rw - 9p remote rw\n")
    environment = {
        "PADIEM_CHAT_WORKERS": "2", "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path / "local"),
        "PADIEM_CHAT_SESSION_SECRET": "synthetic-shared-session-material-1234",
        "PADIEM_COM2_EDGE_REPLAY_DB": str(remote / "replay.sqlite3"),
        # The storage contract is the owner's escape-hatch path now: the default
        # answer to any count above one is the single-process refusal.
        "PADIEM_CHAT_ALLOW_MULTI_WORKERS": "1",
    }
    with pytest.raises(RuntimeError, match="multiworker_local_filesystem_required"):
        validate_worker_configuration(environment, mountinfo_path=mountinfo)


def test_more_than_one_worker_is_blocked_by_default(tmp_path):
    """11-02: two real workers ran on COM2 and the single-process contracts
    (#6563 edge, #6604 tus, #6610 replay) turned healthy requests into 403s.
    The launcher refuses any count above one without the owner's switch."""
    from app.local_server import validate_worker_configuration
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 / / rw - ext4 local rw\n")
    for workers in ("2", "3"):
        environment = {
            "PADIEM_CHAT_WORKERS": workers,
            "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
            "PADIEM_CHAT_SESSION_SECRET": "synthetic-shared-session-material-1234",
        }
        with pytest.raises(RuntimeError, match="multiworker_single_process_contract"):
            validate_worker_configuration(environment, mountinfo_path=mountinfo)
    # The owner's switch is the only way past it, and the switch alone is not
    # enough: with no data directory configured the storage contract still
    # refuses, on every platform.
    environment["PADIEM_CHAT_ALLOW_MULTI_WORKERS"] = "1"
    environment["PADIEM_CHAT_LOCAL_DATA_DIR"] = ""
    with pytest.raises(RuntimeError, match="multiworker_local_filesystem_required"):
        validate_worker_configuration(environment, mountinfo_path=mountinfo)


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="the multi-worker storage contract is a Linux check")
def test_the_owner_switch_reaches_the_storage_contract(tmp_path):
    from app.local_server import validate_worker_configuration
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text("1 0 0:1 / / rw - ext4 local rw\n")
    environment = {
        "PADIEM_CHAT_WORKERS": "3",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "PADIEM_CHAT_SESSION_SECRET": "synthetic-shared-session-material-1234",
        "PADIEM_CHAT_ALLOW_MULTI_WORKERS": "1",
    }
    assert validate_worker_configuration(environment, mountinfo_path=mountinfo) == 3


def test_single_worker_never_needs_the_escape_hatch():
    from app.local_server import validate_worker_configuration
    assert validate_worker_configuration({"PADIEM_CHAT_WORKERS": "1"}) == 1
    assert validate_worker_configuration({}) == 1


def test_launcher_prints_the_single_process_reason_and_exits_two(tmp_path, monkeypatch, capsys):
    from app import local_server
    import uvicorn
    monkeypatch.setenv("PADIEM_CHAT_WORKERS", "2")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "synthetic-shared-session-material-1234")
    monkeypatch.setattr(local_server, "validate_multiworker_storage",
                        lambda *args, **kwargs: pytest.fail("blocked before storage"))
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("must not start"))
    assert local_server.main([]) == 2
    err = capsys.readouterr().err.strip()
    assert err == ("CHAT_WORKERS=REFUSED code=multiworker_single_process_contract"
                   " reason=프로세스 1개 전제 잠금: edge·tus·replay"
                   " — 교차 프로세스화 전에는 1만 허용")


@pytest.mark.parametrize("filesystem", ["ext4", "xfs", "btrfs", "tmpfs", "overlay"])
def test_multiple_workers_accept_reviewed_local_filesystems(tmp_path, filesystem):
    from app.local_server import validate_multiworker_storage
    validate_multiworker_storage(tmp_path, 3, mountinfo_path=_mountinfo(tmp_path, filesystem))


def test_launcher_passes_configured_workers_to_import_string_factory(tmp_path, monkeypatch):
    from app import local_server
    import uvicorn
    called = []
    monkeypatch.setenv("PADIEM_CHAT_WORKERS", "3")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "synthetic-shared-session-material-1234")
    monkeypatch.setenv("PADIEM_CHAT_ALLOW_MULTI_WORKERS", "1")
    monkeypatch.setattr(local_server, "validate_multiworker_storage", lambda *args, **kwargs: None)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: called.append((args, kwargs)))
    local_server.main(["--host", "127.0.0.1", "--port", "8798", "--no-server-header"])
    args, kwargs = called[0]
    assert args == ("app.local_cpython:build_app",)
    assert kwargs["workers"] == 3 and kwargs["factory"] is True
    assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 8798
    assert kwargs["server_header"] is False


def test_multiworker_launcher_requires_one_preconfigured_session_secret(tmp_path, monkeypatch, capsys):
    from app import local_server
    import uvicorn
    monkeypatch.setenv("PADIEM_CHAT_WORKERS", "2")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PADIEM_CHAT_SESSION_SECRET", raising=False)
    monkeypatch.setenv("PADIEM_CHAT_ALLOW_MULTI_WORKERS", "1")
    monkeypatch.setattr(local_server, "validate_multiworker_storage", lambda *args, **kwargs: None)
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: pytest.fail("must not start"))
    assert local_server.main([]) == 2
    assert capsys.readouterr().err.strip() == (
        "CHAT_WORKERS=REFUSED code=multiworker_shared_session_secret_required")


def test_launcher_does_not_print_unexpected_configuration_exception(monkeypatch, capsys):
    from app import local_server
    def fail():
        raise RuntimeError("synthetic-private-configuration-detail")
    monkeypatch.setattr(local_server, "validate_worker_configuration", fail)
    assert local_server.main([]) == 2
    assert capsys.readouterr().err.strip() == (
        "CHAT_WORKERS=REFUSED code=chat_worker_configuration_unavailable")


def _environment():
    environment = dict(os.environ)
    # All subprocess traffic is synthetic and loopback; never inherit a proxy.
    for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        environment.pop(key, None)
    return environment


def _wait_until(predicate, seconds=30):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("synthetic subprocess did not become ready")


def test_three_process_startup_applies_each_migration_once(tmp_path):
    database = tmp_path / "chat.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.close()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text(
        "SELECT test_pause(); CREATE TABLE sample (id INTEGER PRIMARY KEY);\n")
    (migrations / "002.sql").write_text("ALTER TABLE sample ADD COLUMN value TEXT;\n")
    start = tmp_path / "start"
    ready = [tmp_path / f"ready-{index}" for index in range(3)]
    processes = [subprocess.Popen(
        [sys.executable, str(FIXTURE), str(database), str(migrations), str(marker), str(start)],
        env=_environment(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    ) for marker in ready]
    try:
        _wait_until(lambda: all(marker.exists() for marker in ready))
        start.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout)["applied"])
        assert sorted(results) == [0, 0, 2]
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT count(*) FROM padiem_local_migration_ledger").fetchone()[0] == 2
            assert [row[1] for row in connection.execute("PRAGMA table_info(sample)")] == ["id", "value"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


@pytest.mark.parametrize("workers", [2, 3])
def test_workers_share_sqlite_and_serve_requests_while_sse_waits(tmp_path, workers):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001.sql").write_text(
        "CREATE TABLE worker_probe (id TEXT PRIMARY KEY, value INTEGER NOT NULL);\n"
        "INSERT INTO worker_probe VALUES ('count',0),('release',0);\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    environment = _environment()
    environment["PADIEM_TEST_WORKER_DB"] = str(tmp_path / "chat.sqlite3")
    environment["PADIEM_TEST_WORKER_MIGRATIONS"] = str(migrations)
    environment["PYTHONPATH"] = os.pathsep.join([str(FIXTURE.parent), environment.get("PYTHONPATH", "")])
    process = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "chat_multiworker_app_261101:create_app", "--factory",
        "--host", "127.0.0.1", "--port", str(port), "--workers", str(workers),
        "--no-access-log", "--log-level", "error",
    ], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    base = f"http://127.0.0.1:{port}"
    started = threading.Event()
    frames, errors = [], []

    def available():
        try:
            return httpx.get(base + "/count", timeout=1, trust_env=False).status_code == 200
        except httpx.HTTPError:
            return False

    def read_stream():
        try:
            with httpx.Client(timeout=20, trust_env=False) as client:
                with client.stream("GET", base + "/stream") as response:
                    for line in response.iter_lines():
                        if line:
                            frames.append(line)
                            if line == "data: started":
                                started.set()
        except Exception as exc:
            errors.append(type(exc).__name__)

    stream_thread = None
    try:
        _wait_until(available)
        stream_thread = threading.Thread(target=read_stream)
        stream_thread.start()
        assert started.wait(5)

        def increment(_):
            response = httpx.post(base + "/count", timeout=5, trust_env=False)
            assert response.status_code == 200
            return response.json()

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(increment, range(60)))
        assert sorted(item["count"] for item in results) == list(range(1, 61))
        assert len({item["pid"] for item in results}) == workers
        assert stream_thread.is_alive() and frames == ["data: started"]
        assert httpx.get(base + "/count", timeout=5, trust_env=False).json()["count"] == 60
        assert httpx.post(base + "/release", timeout=5, trust_env=False).status_code == 200
        stream_thread.join(5)
        assert not stream_thread.is_alive() and not errors
        assert frames == ["data: started", "data: finished"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if stream_thread is not None:
            stream_thread.join(5)


def test_disk_replace_keeps_old_object_visible_until_complete(tmp_path, monkeypatch):
    from app import local_r2
    bucket = LocalDiskR2(tmp_path)
    bucket.put("object.txt", b"old")
    real_replace = local_r2.os.replace
    observed = []

    def inspect_replace(source, destination):
        observed.append((bucket.get("object.txt").body, Path(source).read_bytes()))
        return real_replace(source, destination)

    monkeypatch.setattr(local_r2.os, "replace", inspect_replace)
    bucket.put("object.txt", b"new-complete-object")
    assert observed == [(b"old", b"new-complete-object")]
    assert bucket.get("object.txt").body == b"new-complete-object"
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_host_object_operations_run_outside_event_loop(tmp_path, monkeypatch):
    caller = threading.get_ident()
    threads = []
    bucket = ThreadedLocalDiskR2(tmp_path)
    for method in ("put", "get", "delete"):
        original = getattr(LocalDiskR2, method)
        def observe(self, *args, _original=original, **kwargs):
            threads.append(threading.get_ident())
            return _original(self, *args, **kwargs)
        monkeypatch.setattr(LocalDiskR2, method, observe)
    await bucket.put("object.txt", b"content")
    assert (await bucket.get("object.txt")).body == b"content"
    await bucket.delete("object.txt")
    assert threads and all(thread != caller for thread in threads)


@pytest.mark.asyncio
async def test_edge_verifier_runs_offthread_and_retains_timing():
    from app.com2_edge_middleware import EdgeProofMiddleware
    from app.request_timing import start_timing, reset_timing
    caller = threading.get_ident()
    threads, sent = [], []
    class Verifier:
        def verify(self, **kwargs):
            threads.append(threading.get_ident())
            return True
    async def downstream(scope, receive, send):
        assert scope["com2_edge_verified_verifier"] is verifier
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    async def receive():
        return {"type": "http.request", "body": b""}
    async def send(message):
        sent.append(message)
    verifier = Verifier()
    middleware = EdgeProofMiddleware(downstream, verifier=verifier)
    scope = {"type": "http", "method": "GET", "path": "/api/claw/devices", "headers": [
        (name, b"synthetic") for name in (b"x-padiem-edge-at", b"x-padiem-edge-id",
                                         b"x-padiem-edge-tls", b"x-padiem-edge-proof")]}
    timing, token = start_timing()
    try:
        await middleware(scope, receive, send)
        assert timing.snapshot()["edge"] > 0
    finally:
        reset_timing(token)
    assert threads and threads[0] != caller
    assert sent[0]["status"] == 200
