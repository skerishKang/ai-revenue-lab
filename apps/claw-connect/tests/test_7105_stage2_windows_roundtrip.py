"""#7105 stage 2 — one real Windows round trip across the whole user lane.

This is the test the earlier fake-only list was missing: the pipe is the real
named pipe, the loop is the real ``serve_pipe``, the client is the real
PowerShell script the executor sends, and the child the helper starts is a real
``powershell.exe``/``cmd.exe`` process. Nothing about the HMAC, the 4-byte
length prefix or the two-sided frame is simulated.

The one injected value is the secret file path. A CI runner has no registered
``PadiemUserSessionHelper`` scheduled task, so the client is pointed at a file
this test wrote instead of reading the path from the task's arguments. The
secret bytes, the material, the nonce the client computes and the nonce the
helper verifies are all real. No production caller passes that argument.

Windows only, and it runs on the ``windows-latest`` job of
``.github/workflows/claw-connect-contract-tests.yml``.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
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


def _run_client(*, request_id: str, shell: str, command: str,
                secret_file: Path, timeout_seconds: int = 30) -> dict:
    """Send one request with the shipped PowerShell client, return its reply."""
    script = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        device_id=DEVICE, request_id=request_id, shell=shell, command=command,
        cwd=None, timeout_seconds=timeout_seconds, distro=None,
        secret_file=str(secret_file),
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-EncodedCommand", encoded],
        capture_output=True, timeout=90, check=False,
    )
    text = completed.stdout.decode("utf-8", "replace").strip()
    assert text, completed.stderr.decode("utf-8", "replace")
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
