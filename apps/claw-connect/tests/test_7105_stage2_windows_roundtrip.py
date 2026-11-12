"""#7105 stage 2 — one real Windows round trip across the whole user lane.

This is the test the earlier fake-only list was missing: the pipe is the real
named pipe, the loop is the real ``serve_pipe``, the client is the real
PowerShell script the executor sends, and the child the helper starts is a real
``powershell.exe``/``cmd.exe`` process. Nothing about the HMAC, the 4-byte
length prefix or the two-sided frame is simulated.

The transport tests inject an accepting peer verifier because their clients
run as the test user. The SYSTEM-only peer check is exercised without injection
by the final test, only on an elevated GitHub Actions Windows runner.

A CI runner has no registered
``PadiemUserSessionHelper`` scheduled task, so most tests pass the exact string
the installer writes (device id and secret path) instead of reading it from the
task. The final test registers temporary tasks and runs the real client as
SYSTEM, reading the helper arguments from the registered task XML. The secret
bytes, the material, the nonce the client
computes and the nonce the helper verifies are all real.

Windows only, and it runs on the ``windows-latest`` job of
``.github/workflows/claw-connect-contract-tests.yml``.
"""
from __future__ import annotations

import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import uuid
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
DEVICE = "dev_" + uuid.uuid4().hex
TASK_DEVICE = "dev_$D62t1_" + uuid.uuid4().hex


def _task_args(secret_file: Path, device_id: str = DEVICE) -> str:
    return f'--device-id "{device_id}" --secret-file "{secret_file}"'


def _run_client_raw(*, request_id: str, shell: str, command: str,
                    secret_file: Path, timeout_seconds: int = 30,
                    task_arguments: str | None = None, task_path: str = "\\",
                    task_name: str = "",
                    registered_task: bool = False) -> tuple[str, float, subprocess.CompletedProcess]:
    """Send one request with the shipped PowerShell client, return raw output."""
    # #7564: the client reads the secret only from the installer's folder under
    # ProgramData. This harness points ProgramData at the test's own tmp_path
    # (the upper-case key: os.environ stores Windows variable names upper-case,
    # and a mixed-case assignment would put TWO ProgramData entries in the child
    # block) and stages the secret exactly where the installer would, so the
    # shipped client under test runs its real boundary checks against a sandbox.
    (secret_file.parent / "Padiem").mkdir(exist_ok=True)
    staged = secret_file.parent / "Padiem" / secret_file.name
    staged.write_bytes(secret_file.read_bytes())
    if task_arguments is None and not registered_task:
        task_arguments = _task_args(staged)
    elif task_arguments is not None:
        task_arguments = task_arguments.replace(str(secret_file), str(staged))
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
        env={**os.environ, "PROGRAMDATA": str(secret_file.parent)},
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
                               max_requests=4, peer_verifier=lambda connection: None)
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
        #    wsl is an unsupported shell since #7188 R4 ④ (owner ban on WSL);
        #    the real-pipe refusal path is what this still proves.
        refused = _run_client(request_id="req_" + "4" * 32, shell="wsl",
                              command="systemctl restart padiem-chat",
                              secret_file=secret_file)
        assert refused["status"] == "error", refused
        assert refused["error_code"] == helper.USER_HELPER_REFUSED
        assert _stdout(refused) == ""
    finally:
        server.join(timeout=90)
        listener.close()

    assert not failures, failures
    assert not server.is_alive(), "the helper never served all four requests"


def _assert_client_failure(text: str, completed: subprocess.CompletedProcess, code: str = "user_session_unavailable") -> None:
    """One failed request, as the shipped client now reports it (#7182b).

    The client does not ``exit`` on failure any more. The SYSTEM lane runs this
    same script inside ``& { ... } 2>&1 | Out-String`` and prints the reply
    envelope and the ``__PADIEM_EXIT__`` sentinel only after that block returns,
    so an ``exit`` deleted the sentinel and turned every outcome - a success as
    much as this refusal - into "no reply" in the transcript.

    What must still hold is the thing the lane reads: the refusal with its code
    arrives on standard output, and the process ending successfully is not a
    claim that the command succeeded.
    """
    assert text.startswith(code + ": "), text
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")


def test_pipe_absent_fails_within_the_connect_window(tmp_path):
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")

    text, elapsed, completed = _run_client_raw(
        request_id="req_" + "a" * 32, shell="powershell", command="whoami",
        secret_file=secret_file,
    )
    _assert_client_failure(text, completed)
    # Connect(5000) is the bound; the process must be gone well before the
    # helper could ever answer a request it never received.
    assert elapsed < 12, elapsed


def test_secret_file_missing_fails_before_any_pipe_wait(tmp_path):
    text, elapsed, completed = _run_client_raw(
        request_id="req_" + "b" * 32, shell="powershell", command="whoami",
        secret_file=tmp_path / "absent.secret",
    )
    _assert_client_failure(text, completed)
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
        # #7199: a silent helper is now named by the client as a timeout, not as an absent pipe.
        _assert_client_failure(text, completed, code="user_helper_timeout")
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
                               max_requests=1, peer_verifier=lambda connection: None)
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
                               max_requests=1, peer_verifier=lambda connection: None)
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
                               max_requests=1, peer_verifier=lambda connection: None)
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
                               max_requests=2, peer_verifier=lambda connection: None)
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


def _require_system_task_ci() -> None:
    """Never register or run SYSTEM tasks on a developer workstation."""
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        pytest.skip("the real SYSTEM client runs only in Windows GitHub Actions")
    if not ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip("the real SYSTEM client requires an elevated CI runner")


def _register_task_with_arguments(task_name: str, arguments: str, *,
                                  xml_dir: Path, system_client: bool = False) -> None:
    _require_system_task_ci()
    from xml.sax.saxutils import escape

    powershell = helper.windows_powershell_executable()
    schtasks = helper.system_executable("schtasks.exe")
    assert powershell and schtasks, "Windows system executable paths are unavailable"
    xml_path = xml_dir / f"{task_name}.xml"
    principal = (
        "<UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel>"
        if system_client else
        "<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>"
    )
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>temporary user-helper CI pipe test</Description></RegistrationInfo>
  <Triggers />
  <Principals><Principal id="Author">{principal}</Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>false</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>false</Hidden><RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun><ExecutionTimeLimit>PT2M</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec><Command>{escape(powershell)}</Command><Arguments>{escape(arguments)}</Arguments></Exec></Actions>
</Task>"""
    xml_path.write_text(xml, encoding="utf-16")
    try:
        create_command = [schtasks, "/Create", "/TN", task_name,
                          "/XML", str(xml_path), "/F"]
        if system_client:
            # ServiceAccount is a task API logon type, not a valid XML
            # LogonType value. /RU SYSTEM selects that service account.
            create_command.extend(["/RU", "SYSTEM"])
        done = subprocess.run(
            create_command,
            capture_output=True, text=True, errors="replace", timeout=60, check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
    finally:
        xml_path.unlink(missing_ok=True)


def test_real_registered_task_arguments_drive_the_pipe_name(tmp_path):
    """A real SYSTEM client reads task XML and passes the default OS peer check."""
    _require_system_task_ci()
    schtasks = helper.system_executable("schtasks.exe")
    assert schtasks, "the Windows task scheduler executable is unavailable"
    secret_file = tmp_path / "user-helper.secret"
    secret_file.write_bytes(SECRET + b"\n")
    task_name = "PadiemUserSessionHelperTest" + uuid.uuid4().hex
    client_task_name = "PadiemUserSessionClientTest" + uuid.uuid4().hex
    task_args = _task_args(secret_file, TASK_DEVICE)
    client_path = tmp_path / "system-client.ps1"
    result_path = tmp_path / "system-client-result.json"
    pending_result_path = tmp_path / "system-client-result.pending"
    client_script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id="req_" + uuid.uuid4().hex, shell="powershell",
        command=("Write-Output 'task-args-ok'; "
                 "Write-Output ('helper-is-system=' + "
                 "[Security.Principal.WindowsIdentity]::GetCurrent().IsSystem)"),
        cwd=None, timeout_seconds=30, distro=None,
        task_path="\\", task_name=task_name,
    )
    # Capture the actual client's identity, not the identity registering its
    # task. Publish the result atomically so Python never reads partial JSON.
    ps_result_path = str(result_path).replace("'", "''")
    ps_pending_path = str(pending_result_path).replace("'", "''")
    client_path.write_text(
        "$ErrorActionPreference='Stop'\n"
        "$result=@{client_is_system=[Security.Principal.WindowsIdentity]::GetCurrent().IsSystem; output=''; error=$null}\n"
        "try {\n$output = & {\n" + client_script + "\n}\n"
        "$result.output=($output | Out-String).Trim()\n"
        "} catch { $result.error=$_.Exception.GetType().FullName } finally {\n"
        f"[IO.File]::WriteAllText('{ps_pending_path}', ($result | ConvertTo-Json -Compress -Depth 8), (New-Object Text.UTF8Encoding($false)))\n"
        f"[IO.File]::Move('{ps_pending_path}', '{ps_result_path}')\n"
        "}\n",
        encoding="utf-8-sig",
    )
    failures: list[BaseException] = []
    stats: list[service.ServeStats] = []
    registered_tasks: list[str] = []
    stop = threading.Event()
    listener = None
    server = None

    def _serve() -> None:
        try:
            # No peer_verifier injection: this is the genuine SYSTEM path.
            stats.append(service.serve_pipe(
                device_id=TASK_DEVICE, secret=SECRET, listener=listener,
                max_requests=1, should_stop=stop.is_set,
            ))
        except BaseException as exc:  # noqa: BLE001
            failures.append(exc)

    try:
        # The first task is metadata only; it is never started. The shipped
        # SYSTEM client reads its real registered XML and deployment arguments.
        registered_tasks.append(task_name)
        _register_task_with_arguments(task_name, task_args, xml_dir=tmp_path)
        listener = service.WindowsPipeListener(TASK_DEVICE)
        server = threading.Thread(target=_serve, daemon=True)
        server.start()
        registered_tasks.append(client_task_name)
        _register_task_with_arguments(
            client_task_name,
            '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File '
            f'"{client_path}"',
            xml_dir=tmp_path, system_client=True,
        )
        started = subprocess.run(
            [schtasks, "/Run", "/TN", client_task_name],
            capture_output=True, text=True, errors="replace", timeout=30, check=False,
        )
        assert started.returncode == 0, started.stdout + started.stderr
        deadline = time.monotonic() + 90
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert result_path.exists(), "the SYSTEM pipe client did not publish its result"
        result = json.loads(result_path.read_text(encoding="utf-8-sig"))
        assert result["client_is_system"] is True
        assert result["error"] is None, result["error"]
        reply = json.loads(result["output"])
        assert reply["status"] == "ok", reply
        assert reply["exit_code"] == 0, reply
        assert "task-args-ok" in _stdout(reply)
        assert "helper-is-system=False" in _stdout(reply)
    finally:
        stop.set()
        cleanup_failures = []
        # End only our UUID-named client, including timeout/failure paths.
        if client_task_name in registered_tasks:
            try:
                subprocess.run(
                    [schtasks, "/End", "/TN", client_task_name],
                    capture_output=True, timeout=30, check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup_failures.append(type(exc).__name__)
        if server is not None:
            server.join(timeout=15)
        if listener is not None:
            listener.close()
        for registered_name in reversed(registered_tasks):
            try:
                deleted = subprocess.run(
                    [schtasks, "/Delete", "/TN", registered_name, "/F"],
                    capture_output=True, text=True, errors="replace", timeout=30, check=False,
                )
                if deleted.returncode:
                    cleanup_failures.append(deleted.stdout + deleted.stderr)
            except (OSError, subprocess.SubprocessError) as exc:
                cleanup_failures.append(type(exc).__name__)
        assert not cleanup_failures, cleanup_failures
    assert not failures, failures
    assert server is not None and not server.is_alive(), "the helper did not finish"
    assert len(stats) == 1 and stats[0].served == 1 and stats[0].refused == 0
