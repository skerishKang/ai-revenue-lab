"""#7108 PR-1 — the built single-file helper speaks the real pipe.

This test is deliberately about the artifact, not the source module: the CI
builds `padiem-user-helper.exe` and points `PADIEM_HELPER_EXE` at it. The test
then starts that EXE as a separate process, connects to its Windows named pipe,
sends a real HMAC-framed request, and reads the streamed frames back.

It also checks the two halves of "no console window":

* the EXE's PE subsystem is GUI (2), so the helper itself has no console; and
* the helper's child ``powershell.exe`` reports ``GetConsoleWindow() == 0``,
  proving the entrypoint's ``CREATE_NO_WINDOW`` seam reached the child.

The helper source is not imported into the server process for this test. The
only values taken from it are the wire contract helpers (pipe name, nonce,
framing), so the test proves the shipped artifact speaks that same contract.
"""
from __future__ import annotations

import base64
import hashlib
import json
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
# A raw device id with '$' exercises the same hashed-pipe rule the executor
# uses; the EXE receives it as one argv element, so no shell expands it.
DEVICE = "helper7108$" + uuid.uuid4().hex

_CONSOLE_PROBE = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class PadiemConsoleProbe {
    [DllImport("kernel32.dll")]
    public static extern IntPtr GetConsoleWindow();
}
'@
$user = (& whoami).Trim()
$console = if ([PadiemConsoleProbe]::GetConsoleWindow() -eq [IntPtr]::Zero) { 'hidden' } else { 'visible' }
Write-Output ("padiem-whoami=" + $user)
Write-Output ("padiem-console=" + $console)
""".strip()


def _pe_subsystem(path: Path) -> int:
    """Read the PE optional-header subsystem without a Windows SDK."""
    data = path.read_bytes()
    assert data[:2] == b"MZ", "not a PE image"
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_offset:pe_offset + 4] == b"PE\0\0", "missing PE signature"
    # Subsystem is at optional-header offset 68 for PE32 and PE32+.
    return struct.unpack_from("<H", data, pe_offset + 24 + 68)[0]


def _start_helper(exe: Path, secret_file: Path, device_id: str = DEVICE) -> subprocess.Popen:
    return subprocess.Popen(
        [
            str(exe),
            "--device-id", device_id,
            "--secret-file", str(secret_file),
            "--max-requests", "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _connect_when_ready(proc: subprocess.Popen, timeout_seconds: float = 30.0):
    pipe_path = helper.pipe_path(DEVICE)
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


def _read_final(conn) -> tuple[dict, bytes, bytes]:
    stdout = bytearray()
    stderr = bytearray()
    while True:
        frame = service.read_frame(conn.read_exact)
        status = frame.get("status")
        if status in {"started", "running"}:
            continue
        if status == "stdout":
            stdout.extend(base64.b64decode(frame["data_b64"]))
            continue
        if status == "stderr":
            stderr.extend(base64.b64decode(frame["data_b64"]))
            continue
        return frame, bytes(stdout), bytes(stderr)


@pytest.mark.skipif(not _HELPER_EXE, reason="PADIEM_HELPER_EXE is not configured")
def test_built_helper_serves_the_real_pipe_without_a_console(tmp_path):
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

    proc = _start_helper(exe, secret_file)
    conn = None
    proc_out = b""
    proc_err = b""
    try:
        conn = _connect_when_ready(proc)
        unsigned = helper.HelperRequest(
            request_id="req_" + uuid.uuid4().hex,
            nonce="",
            shell="powershell",
            command=_CONSOLE_PROBE,
            timeout_seconds=0,
        )
        request = helper.HelperRequest(
            request_id=unsigned.request_id,
            nonce=helper.request_nonce(SECRET, unsigned),
            shell=unsigned.shell,
            command=unsigned.command,
            timeout_seconds=unsigned.timeout_seconds,
            cwd=unsigned.cwd,
            distro=unsigned.distro,
        )
        conn.write_all(service.encode_frame({
            "request_id": request.request_id,
            "nonce": request.nonce,
            "shell": request.shell,
            "cwd": request.cwd,
            "command": request.command,
            "timeout_seconds": request.timeout_seconds,
            "distro": request.distro,
        }))

        final, stdout, stderr = _read_final(conn)
        text = stdout.decode("utf-8", "replace")
        assert final.get("status") == "ok", (final, stderr.decode("utf-8", "replace"))
        assert final.get("exit_code") == 0
        assert "padiem-whoami=" in text, text
        username = os.environ.get("USERNAME", "")
        if username:
            assert username.lower() in text.lower(), text
        assert "padiem-console=hidden" in text, text
    finally:
        if conn is not None:
            conn.close()
        if proc.poll() is None:
            # The helper has already sent the final frame; let its own
            # max_requests=1 loop exit instead of racing a kill against it.
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc_out, proc_err = proc.communicate(timeout=30)

    assert proc.returncode == 0, (proc.returncode, proc_out, proc_err)
    # The helper's counter line goes to stdout only when it has a usable
    # stream; the pipe result above is the gate, so this is not required.
    if proc_out:
        assert b"served=1" in proc_out, (proc_out, proc_err)


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


def _wait_for_pipe(device_id: str, proc: subprocess.Popen, timeout_seconds: float = 2.0) -> None:
    """Give PyInstaller's onefile bootstrap a moment without opening the pipe.

    Test-Path on a named pipe can consume the listener's only instance, so the
    client's own Connect(5000) is the actual readiness probe.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            out, err = proc.communicate(timeout=10)
            pytest.fail(f"the helper exited before its pipe appeared: {proc.returncode} {out!r} {err!r}")
        time.sleep(0.1)


@pytest.mark.skipif(not _HELPER_EXE, reason="PADIEM_HELPER_EXE is not configured")
def test_registered_task_arguments_reach_the_built_helper(tmp_path):
    """The real EXE, the real scheduled-task argument string, the real client."""
    exe = Path(_HELPER_EXE)
    assert exe.is_file(), f"built helper is missing: {exe}"

    device = "helper7108$" + uuid.uuid4().hex
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    task_args = f'--device-id "{device}" --secret-file "{secret_file}"'
    proc = _start_helper(exe, secret_file, device)
    try:
        _wait_for_pipe(device, proc)
        script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_" + uuid.uuid4().hex,
            shell="powershell",
            command="Write-Output 'exe-task-args-ok'",
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
        assert text, done.stderr.decode("utf-8", "replace")
        reply = json.loads(text)
        assert reply["status"] == "ok", reply
        stdout = base64.b64decode(reply["stdout_b64"]).decode("utf-8", "replace")
        assert "exe-task-args-ok" in stdout
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=30)
