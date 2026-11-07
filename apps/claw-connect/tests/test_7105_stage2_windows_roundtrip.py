"""#7105 stage 2 — one real Windows round trip across the whole user lane.

This is the test the earlier fake-only list was missing: the pipe is the real
named pipe, the loop is the real ``serve_pipe``, the client is the real
PowerShell script the executor sends, and the child the helper starts is a real
``powershell.exe``/``cmd.exe`` process. Nothing about the HMAC, the 4-byte
length prefix or the two-sided frame is simulated.

The injected value is the task argument string. A CI runner has no registered
``PadiemUserSessionHelper`` scheduled task, so most tests pass the exact string
the installer writes (device id and secret path) instead of reading it from the
task. One test registers a real task and reads its arguments back through
``Get-ScheduledTask``. The secret bytes, the material, the nonce the client
computes and the nonce the helper verifies are all real.

Windows only, and it runs on the ``windows-latest`` job of
``.github/workflows/claw-connect-contract-tests.yml``.
"""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CLAW_CONNECT = ROOT / "apps" / "claw-connect"
KAGENT_SRC = ROOT / "apps" / "korean-ai-code-agent" / "src"
# The CI lane installs the shared Core, a workstation may not have it installed.
# Adding it from source keeps this test runnable both ways, from one tree.
SHARED_PACKAGES = [ROOT / "packages" / "padiem-ai-core", ROOT / "packages" / "padiem-control-plane"]
for path in (str(CLAW_CONNECT), str(KAGENT_SRC), *[str(item) for item in SHARED_PACKAGES]):
    if path not in sys.path:
        sys.path.insert(0, path)

from claw_connect import user_helper_service as service  # noqa: E402
from claw_connect import user_session_helper as helper  # noqa: E402
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="the helper pipe and its PowerShell client exist on Windows only",
)

SECRET = b"deployment-secret-for-the-7105-round-trip"
DEVICE = "dev_" + "d" * 32
TASK_DEVICE = "dev_$D62t1"


def _task_args(secret_file: Path, device_id: str = DEVICE) -> str:
    return f'--device-id "{device_id}" --secret-file "{secret_file}"'


def _run_client_raw(*, request_id: str, shell: str, command: str,
                    secret_file: Path, timeout_seconds: int = 30,
                    task_arguments: str | None = None, task_path: str = "\\",
                    task_name: str = "",
                    registered_task: bool = False) -> tuple[str, float, subprocess.CompletedProcess]:
    """Send one request with the shipped PowerShell client, return raw output."""
    if task_arguments is None and not registered_task:
        task_arguments = _task_args(secret_file)
    script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id=request_id, shell=shell, command=command,
        cwd=None, timeout_seconds=timeout_seconds, distro=None,
        task_arguments=task_arguments, task_path=task_path, task_name=task_name,
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    started = time.monotonic()
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-EncodedCommand", encoded],
        capture_output=True, timeout=90, check=False,
    )
    elapsed = time.monotonic() - started
    text = completed.stdout.decode("utf-8", "replace").strip()
    assert text, completed.stderr.decode("utf-8", "replace")
    return text, elapsed, completed


def _run_client(*, request_id: str, shell: str, command: str,
                secret_file: Path, timeout_seconds: int = 30,
                task_arguments: str | None = None, task_path: str = "\\",
                task_name: str = "", registered_task: bool = False) -> dict:
    """Send one request with the shipped PowerShell client, return its reply."""
    text, _elapsed, _completed = _run_client_raw(
        request_id=request_id, shell=shell, command=command,
        secret_file=secret_file, timeout_seconds=timeout_seconds,
        task_arguments=task_arguments, task_path=task_path,
        task_name=task_name, registered_task=registered_task,
    )
    reply = json.loads(text)
    assert isinstance(reply, dict)
    return reply


def _stdout(reply: dict) -> str:
    return base64.b64decode(reply["stdout_b64"]).decode("utf-8")


def test_real_pipe_round_trip_runs_powershell_and_cmd_as_the_helper_user(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")

    listener = service.WindowsPipeListener(DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=DEVICE, secret=SECRET, listener=listener,
                               max_requests=4)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    try:
        # 1. A real powershell.exe child started by the helper, as this user.
        shell_ok = _run_client(request_id="req_" + "1" * 32, shell="powershell",
                               command="Write-Output 'user-lane-ok'",
                               secret_file=secret_file)
        assert shell_ok["status"] == "ok", shell_ok
        assert shell_ok["exit_code"] == 0
        assert "user-lane-ok" in _stdout(shell_ok)

        # 2. A real cmd.exe child on the same lane.
        cmd_ok = _run_client(request_id="req_" + "2" * 32, shell="cmd",
                             command="echo user-lane-cmd",
                             secret_file=secret_file)
        assert cmd_ok["status"] == "ok", cmd_ok
        assert cmd_ok["exit_code"] == 0
        assert "user-lane-cmd" in _stdout(cmd_ok)

        # 3. The exit code is the child's own, never the helper's own success.
        exit_ok = _run_client(request_id="req_" + "3" * 32, shell="powershell",
                              command="cmd /c exit 7",
                              secret_file=secret_file)
        assert exit_ok["status"] == "ok", exit_ok
        assert exit_ok["exit_code"] == 7

        # 4. A refusal crosses the same real pipe as a refusal, with no process.
        refused = _run_client(request_id="req_" + "4" * 32, shell="wsl",
                              command="systemctl restart padiem-chat",
                              secret_file=secret_file)
        assert refused["status"] == "error", refused
        assert refused["error_code"] == helper.USER_HELPER_NOT_READ_ONLY
        assert _stdout(refused) == ""
    finally:
        server.join(timeout=90)
        listener.close()

    assert not failures, failures
    assert not server.is_alive(), "the helper never served all four requests"


def test_pipe_absent_fails_within_the_connect_window(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")

    text, elapsed, completed = _run_client_raw(
        request_id="req_" + "a" * 32, shell="powershell", command="whoami",
        secret_file=secret_file,
    )
    assert "user_session_unavailable" in text, text
    assert completed.returncode != 0
    # Connect(5000) is the bound; the process must be gone well before the
    # helper could ever answer a request it never received.
    assert elapsed < 12, elapsed


def test_secret_file_missing_fails_before_any_pipe_wait(tmp_path):
    text, elapsed, completed = _run_client_raw(
        request_id="req_" + "b" * 32, shell="powershell", command="whoami",
        secret_file=tmp_path / "absent.secret",
    )
    assert "user_session_unavailable" in text, text
    assert completed.returncode != 0
    assert elapsed < 8, elapsed


def test_helper_accepts_and_never_answers_fails_within_the_read_window(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    listener = service.WindowsPipeListener(DEVICE)
    held: list[object] = []

    def _silent() -> None:
        connection = listener.accept(10)
        if connection is not None:
            held.append(connection)
            time.sleep(30)

    silent = threading.Thread(target=_silent, daemon=True)
    silent.start()
    try:
        text, elapsed, completed = _run_client_raw(
            request_id="req_" + "c" * 32, shell="powershell", command="whoami",
            secret_file=secret_file,
        )
        assert "user_session_unavailable" in text, text
        assert completed.returncode != 0
        # The helper accepted the connection but sent no start frame: the 15s
        # per-frame read window is what ends this, not a command deadline.
        assert 10 <= elapsed < 25, elapsed
    finally:
        for connection in held:
            connection.close()
        listener.close()


def test_a_long_command_is_kept_alive_by_heartbeats(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    listener = service.WindowsPipeListener(DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=DEVICE, secret=SECRET, listener=listener,
                               max_requests=1)
        except BaseException as exc:  # noqa: BLE001 - asserted below
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    try:
        reply = _run_client(
            request_id="req_" + "d" * 32, shell="powershell",
            command="Start-Sleep -Seconds 7; Write-Output 'late-answer'",
            secret_file=secret_file,
        )
        assert reply["status"] == "ok", reply
        assert "late-answer" in _stdout(reply)
    finally:
        server.join(timeout=90)
        listener.close()
    assert not failures, failures


def test_a_large_output_is_returned_whole(tmp_path):
    """#7107: 300 KiB crosses the pipe as chunks, not as a 256 KiB cut."""
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    listener = service.WindowsPipeListener(DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=DEVICE, secret=SECRET, listener=listener,
                               max_requests=1)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    try:
        reply = _run_client(
            request_id="req_" + "e" * 32, shell="powershell",
            command="[Console]::Out.Write(('x' * 300000))",
            secret_file=secret_file,
        )
        assert reply["status"] == "ok", reply
        assert reply.get("truncated") is False
        assert len(_stdout(reply)) == 300_000
    finally:
        server.join(timeout=90)
        listener.close()
    assert not failures, failures


def test_a_command_past_the_old_thirty_second_limit_completes(tmp_path):
    """#7107: the old 30s helper deadline would have failed this command."""
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    listener = service.WindowsPipeListener(DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=DEVICE, secret=SECRET, listener=listener,
                               max_requests=1)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    try:
        reply = _run_client(
            request_id="req_" + "d" * 32, shell="powershell",
            command="Start-Sleep -Seconds 32; Write-Output 'past-30'",
            secret_file=secret_file,
        )
        assert reply["status"] == "ok", reply
        assert "past-30" in _stdout(reply)
    finally:
        server.join(timeout=120)
        listener.close()
    assert not failures, failures


def test_a_dead_client_stops_the_user_child_and_frees_the_helper(tmp_path):
    """#7107: killing the SYSTEM client ends the user child, not an orphan."""
    marker = tmp_path / "after-stop.txt"
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    listener = service.WindowsPipeListener(DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=DEVICE, secret=SECRET, listener=listener,
                               max_requests=2)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id="req_" + "f" * 32, shell="powershell",
        command=("Start-Sleep -Seconds 20; Set-Content -LiteralPath "
                 f"'{marker}' -Value done"),
        cwd=None, timeout_seconds=0, distro=None,
        task_arguments=_task_args(secret_file),
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    client = subprocess.Popen(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-EncodedCommand", encoded],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        time.sleep(3)
        client.kill()
        client.wait(timeout=10)
        # The heartbeat write fails on the next 5s pulse; the helper then kills
        # the user child. The 20s marker must never appear.
        time.sleep(7)
        assert not marker.exists(), "the user child survived the dead client"
        reply = _run_client(
            request_id="req_" + "a" * 31 + "b", shell="powershell",
            command="Write-Output 'after-stop'", secret_file=secret_file,
        )
        assert reply["status"] == "ok", reply
        assert "after-stop" in _stdout(reply)
    finally:
        if client.poll() is None:
            client.kill()
        server.join(timeout=30)
        listener.close()
    assert not failures, failures


def _register_task_with_arguments(task_name: str, arguments: str) -> None:
    import uuid
    from xml.sax.saxutils import escape

    xml_path = Path(tempfile.gettempdir()) / f"{task_name}-{uuid.uuid4().hex}.xml"
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>temporary #7108 PR-3 arguments test</Description></RegistrationInfo>
  <Triggers><TimeTrigger><StartBoundary>2030-01-01T00:00:00</StartBoundary><Enabled>false</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT1H</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec><Command>powershell.exe</Command><Arguments>{escape(arguments)}</Arguments></Exec></Actions>
</Task>"""
    xml_path.write_text(xml, encoding="utf-16")
    try:
        done = subprocess.run(
            ["schtasks.exe", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
            capture_output=True, text=True, errors="replace", timeout=60, check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
    finally:
        xml_path.unlink(missing_ok=True)


def test_real_registered_task_arguments_drive_the_pipe_name(tmp_path):
    """The production path: Get-ScheduledTask -> --device-id -> SHA-256 -> pipe."""
    import uuid

    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    task_name = "PadiemUserSessionHelperTest" + uuid.uuid4().hex[:8]
    task_args = _task_args(secret_file, TASK_DEVICE)
    _register_task_with_arguments(task_name, task_args)
    listener = service.WindowsPipeListener(TASK_DEVICE)
    failures: list[BaseException] = []

    def _serve() -> None:
        try:
            service.serve_pipe(device_id=TASK_DEVICE, secret=SECRET, listener=listener,
                               max_requests=1)
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    server = threading.Thread(target=_serve, daemon=True)
    server.start()
    try:
        reply = _run_client(
            request_id="req_" + "9" * 32, shell="powershell",
            command="Write-Output 'task-args-ok'",
            secret_file=secret_file, task_path="\\", task_name=task_name,
            registered_task=True,
        )
        assert reply["status"] == "ok", reply
        assert "task-args-ok" in _stdout(reply)
    finally:
        server.join(timeout=90)
        listener.close()
        subprocess.run(["schtasks.exe", "/Delete", "/TN", task_name, "/F"],
                       capture_output=True, text=True, timeout=60, check=False)
    assert not failures, failures
