"""The built single-file helper opens its pipe and rejects non-SYSTEM peers.

This test is deliberately about the artifact, not the source module: the CI
builds `padiem-user-helper.exe` and points `PADIEM_HELPER_EXE` at it. The test
then starts that EXE as a separate process and connects to a temporary named
pipe as the ordinary test user. The EXE must reject the peer after the fixed
header, without waiting for a body, and remain available for the next peer.

The artifact receipt and GUI subsystem checks still exercise the shipped EXE.
Successful SYSTEM requests and actual child-console behavior need a separate
installed-PC check; the entrypoint's source-level console guard stays covered.
No code injection or authentication-bypass option reaches the EXE process.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KAGENT_SRC = ROOT.parent / "korean-ai-code-agent" / "src"
for path in (str(ROOT), str(KAGENT_SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from claw_connect import user_helper_service as service  # noqa: E402
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor  # noqa: E402
from claw_connect import user_session_delegation as delegation  # noqa: E402
from claw_connect import user_session_helper as helper  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the helper pipe and its window probe exist on Windows only",
)

_HELPER_EXE = os.environ.get("PADIEM_HELPER_EXE", "").strip()
SECRET = b"single-file-helper-7108-round-trip-secret"


def _pe_subsystem(path: Path) -> int:
    """Read the PE optional-header subsystem without a Windows SDK."""
    data = path.read_bytes()
    assert data[:2] == b"MZ", "not a PE image"
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_offset:pe_offset + 4] == b"PE\0\0", "missing PE signature"
    # Subsystem is at optional-header offset 68 for PE32 and PE32+.
    return struct.unpack_from("<H", data, pe_offset + 24 + 68)[0]


def _start_helper(exe: Path, secret_file: Path, device_id: str) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(exe),
            "--device-id", device_id,
            "--secret-file", str(secret_file),
            "--max-requests", "2",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _connect_when_ready(proc: subprocess.Popen, device_id: str,
                        timeout_seconds: float = 30.0):
    pipe_path = helper.pipe_path(device_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return delegation.open_pipe_connection(pipe_path)
        except (FileNotFoundError, OSError):
            if proc.poll() is not None:
                out, err = proc.communicate(timeout=10)
                pytest.fail(
                    "the helper exited before its pipe appeared: "
                    f"returncode={proc.returncode} stdout={out!r} stderr={err!r}"
                )
            time.sleep(0.1)
    pytest.fail("the helper pipe did not appear within the connect window")


def _marker_command(marker: Path) -> str:
    path = str(marker).replace("'", "''")
    return f"[IO.File]::WriteAllText('{path}', 'unexpected execution')"


def _signed_frame(command: str) -> bytes:
    request = helper.HelperRequest(
        request_id="req_" + uuid.uuid4().hex, nonce="", shell="powershell",
        command=command, timeout_seconds=0,
    )
    return service.encode_frame({
        "request_id": request.request_id,
        "nonce": helper.request_nonce(SECRET, request),
        "shell": request.shell,
        "cwd": request.cwd,
        "command": request.command,
        "timeout_seconds": request.timeout_seconds,
        "distro": request.distro,
    })


def _assert_peer_closed_without_reply(conn) -> None:
    # A header-only peer must be refused before the ordinary incomplete-body
    # timeout. Polling avoids a synchronous ReadFile hanging this artifact test.
    deadline = time.monotonic() + service.REQUEST_READ_TIMEOUT_SECONDS / 2
    while time.monotonic() < deadline:
        assert conn._available() == 0, "an unverified peer received a reply"
        if conn.peer_closed():
            return
        time.sleep(0.01)
    pytest.fail("the EXE did not refuse the peer before waiting for its body")


def _send_header_and_expect_refusal(proc, device_id: str, frame: bytes) -> None:
    conn = _connect_when_ready(proc, device_id)
    try:
        conn.write_all(frame[:4])
        _assert_peer_closed_without_reply(conn)
    finally:
        conn.close()
    assert proc.poll() is None, "the EXE ended after its first refused connection"


def _assert_clean_exit(proc) -> None:
    proc_out, proc_err = proc.communicate(timeout=15)
    assert proc.returncode == 0, (proc.returncode, proc_out, proc_err)
    # Windowed PyInstaller builds may direct these streams to os.devnull.
    if proc_out:
        assert b"served=0 refused=2" in proc_out, (proc_out, proc_err)


def _stop_helper(proc) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=30)


@pytest.mark.skipif(not _HELPER_EXE, reason="PADIEM_HELPER_EXE is not configured")
def test_built_helper_rejects_user_peers_and_keeps_its_pipe_available(tmp_path):
    exe = Path(_HELPER_EXE)
    assert exe.is_file(), f"built helper is missing: {exe}"

    expected_sha = os.environ.get("PADIEM_HELPER_SHA256", "").strip()
    if expected_sha:
        actual_sha = hashlib.sha256(exe.read_bytes()).hexdigest()
        assert actual_sha.lower() == expected_sha.lower(), "helper SHA-256 drifted"
    expected_bytes = os.environ.get("PADIEM_HELPER_BYTES", "").strip()
    if expected_bytes:
        assert exe.stat().st_size == int(expected_bytes), "helper size drifted"

    # PyInstaller's console=False sets the GUI subsystem. A console EXE here
    # would mean the build ignored the spec and could show a window.
    assert _pe_subsystem(exe) == 2, "the helper EXE is not a windowed build"

    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")

    device = "helper7108$" + uuid.uuid4().hex
    marker = tmp_path / "must-not-run.txt"
    frame = _signed_frame(_marker_command(marker))
    proc = _start_helper(exe, secret_file, device)
    try:
        _send_header_and_expect_refusal(proc, device, frame)
        assert not marker.exists()

        conn = _connect_when_ready(proc, device)
        try:
            # Even a complete, correctly authenticated request cannot admit an
            # ordinary user's token. One write avoids a body-write/close race.
            conn.write_all(frame)
            _assert_peer_closed_without_reply(conn)
        finally:
            conn.close()
        _assert_clean_exit(proc)
        assert not marker.exists(), "the refused peer's command was executed"
    finally:
        _stop_helper(proc)


def test_entrypoint_hides_every_child_console(monkeypatch):
    import user_helper_entry

    captured = {}

    class FakeProcess:
        pass

    def fake_popen(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(user_helper_entry, "_ORIGINAL_POPEN", fake_popen)
    child = user_helper_entry._popen_without_window(["cmd.exe", "/c", "echo padiem"])

    assert isinstance(child, FakeProcess)
    assert captured["args"] == (["cmd.exe", "/c", "echo padiem"],)
    assert captured["kwargs"]["creationflags"] & getattr(
        subprocess, "CREATE_NO_WINDOW", 0x08000000
    )


@pytest.mark.skipif(not _HELPER_EXE, reason="PADIEM_HELPER_EXE is not configured")
def test_task_arguments_reach_the_built_helper_and_user_client_is_refused(tmp_path):
    """The task argument format reaches the real EXE without registering a task."""
    exe = Path(_HELPER_EXE)
    assert exe.is_file(), f"built helper is missing: {exe}"

    device = "helper7108$" + uuid.uuid4().hex
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    marker = tmp_path / "task-client-must-not-run.txt"
    command = _marker_command(marker)
    task_args = f'--device-id "{device}" --secret-file "{secret_file}"'
    proc = _start_helper(exe, secret_file, device)
    try:
        _send_header_and_expect_refusal(proc, device, _signed_frame(command))
        script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_" + uuid.uuid4().hex,
            shell="powershell",
            command=command,
            cwd=None,
            timeout_seconds=30,
            distro=None,
            task_arguments=task_args,
        )
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        done = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
             "Bypass", "-EncodedCommand", encoded],
            capture_output=True, timeout=90, check=False,
        )
        text = done.stdout.decode("utf-8", "replace").strip()
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        assert text.startswith("user_session_unavailable: "), text
        # Reaching max_requests proves that this second client connected to the
        # correct pipe, rather than reporting an unrelated missing-pipe error.
        _assert_clean_exit(proc)
        assert not marker.exists(), "the refused client command was executed"
    finally:
        _stop_helper(proc)
