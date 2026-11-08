"""#7076c framing contract: executor PS client material/nonce matches #7076/#7065 helper."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CC = ROOT / "apps" / "claw-connect"
if str(CC) not in sys.path:
    sys.path.insert(0, str(CC))
from claw_connect import user_session_helper as helper
from claw_connect import user_helper_service as service

# import only the module bits we need by loading executor class statically? easier: import with full path deps present
sys.path.insert(0, str(ROOT / "apps" / "korean-ai-code-agent" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "padiem-ai-core"))
from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor, USER_SESSION_UNAVAILABLE

SECRET = b"deployment-secret-for-tests"
DEVICE = "dev_" + "c" * 32
MESH_DEVICE = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
REQ_ID = "req_" + "a" * 32


def _task_args(device_id: str, secret_file: str = r"C:\Padiem\helper.secret") -> str:
    return f'--device-id "{device_id}" --secret-file "{secret_file}"'


def test_executor_ps_embeds_exact_helper_request_material():
    cmd = "whoami"
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        task_arguments=_task_args(DEVICE), request_id=REQ_ID, shell="whoami", command=cmd,
        cwd=None, timeout_seconds=30, distro=None,
    )
    req = helper.HelperRequest(request_id=REQ_ID, nonce="n", shell="whoami",
                               command=cmd, timeout_seconds=30)
    expected_mat_b64 = base64.b64encode(req.material()).decode("ascii")
    assert expected_mat_b64 in ps
    assert SECRET.hex() not in ps
    assert SECRET.decode() not in ps
    assert "[Array]::Reverse($len)" in ps or "Reverse($len)" in ps
    assert "NamedPipeClientStream" in ps
    assert "padiem-user-helper-dev_" in ps
    assert "SHA256" in ps
    assert helper.pipe_name(DEVICE) not in ps
    assert "Get-ScheduledTask" not in ps  # task_arguments is the test seam
    assert "--secret-file" in ps
    # the injected task arguments carry the path; the production lookup is below


def test_ps_client_bounds_every_pipe_step():
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        task_arguments=_task_args(DEVICE), request_id=REQ_ID, shell="powershell", command="whoami",
        cwd=None, timeout_seconds=30, distro=None,
    )
    assert "$client.Connect(5000)" in ps
    assert "$w.Wait(5000)" in ps
    # #7184c: 15s is the default frame window, clamped to the bound around it.
    assert "$__wait=15000" in ps
    assert "if(-not $t.Wait($__wait)){ Timeout }" in ps
    # #7196: each wait names its own stage when it expires.
    assert "user_helper_timeout: frame read deadline expired" in ps
    assert "user_helper_timeout: first-frame deadline expired" in ps
    assert "user_helper_timeout: overall deadline expired" in ps
    assert "helper write timeout" in ps


def test_ps_client_accumulates_streamed_chunks_without_a_256_kib_cut():
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        task_arguments=_task_args(DEVICE), request_id=REQ_ID, shell="powershell", command="whoami",
        cwd=None, timeout_seconds=0, distro=None,
    )
    assert "$stdout.AddRange" in ps
    assert "$stderr.AddRange" in ps
    assert "data_b64" in ps
    assert "[Convert]::ToBase64String($stdout.ToArray())" in ps
    assert "2097152" in ps


def test_golden_meshcentral_raw_device_id_yields_same_pipe_name_and_no_ps_dollar_expansion():
    expected = helper.pipe_name(MESH_DEVICE)
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        task_arguments=_task_args(MESH_DEVICE), request_id=REQ_ID, shell="whoami", command="whoami",
        cwd=None, timeout_seconds=30, distro=None,
    )
    # helper and executor must target identical pipe; raw id contains '$' but PS embeds only hashed literal
    from kagent.local_agent_oracle_mesh_executor import user_helper_pipe_name
    assert user_helper_pipe_name(MESH_DEVICE) == expected
    assert expected not in ps
    assert MESH_DEVICE not in ps
    assert "$D62t1" not in ps
    assert "$digest.Substring(0,32)" in ps


def test_production_client_reads_the_registered_task_and_hashes_on_the_pc():
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id=REQ_ID, shell="whoami", command="whoami",
        cwd=None, timeout_seconds=30, distro=None,
    )
    # #7196: the installer registers the task under the folder ``\Padiem\``, which on
    # disk is the file %SystemRoot%\System32\Tasks\Padiem\PadiemUserSessionHelper.
    # SYSTEM reads that file's <Arguments> directly, so there is no Get-ScheduledTask
    # COM call (which had no timeout of its own) anywhere in the client.
    assert "Get-ScheduledTask" not in ps
    assert "System32\\Tasks\\Padiem\\PadiemUserSessionHelper" in ps
    assert "$__tx.Load($txp)" in ps
    assert "$__tx.Task.Actions.Exec" in ps
    assert "--device-id" in ps
    assert "--secret-file" in ps
    assert "padiem-user-helper-dev_" in ps
    assert "$digest.Substring(0,32)" in ps
    assert "helper task file is not present" in ps
    assert "helper device id is not configured" in ps
    assert DEVICE not in ps


def test_golden_helper_frame_for_ps_client_request():
    base = helper.HelperRequest(request_id=REQ_ID, nonce="", shell="whoami", command="whoami", timeout_seconds=30)
    payload = {
        "request_id": REQ_ID,
        "nonce": helper.request_nonce(SECRET, base),
        "shell": "whoami", "cwd": None, "command": "whoami",
        "timeout_seconds": 30, "distro": None,
    }
    frame = service.encode_frame(payload)
    assert frame[:4] == len(frame[4:]).to_bytes(4, "big")
    decoded = service.read_frame(_Reader(frame).read_exact)
    assert decoded["nonce"] == payload["nonce"]
    assert helper.verify_nonce(SECRET, helper.parse_request(decoded))


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.i = data, 0
    def read_exact(self, n: int) -> bytes:
        if self.i + n > len(self.data): raise EOFError()
        b = self.data[self.i:self.i+n]; self.i += n; return b


def test_parse_user_helper_outcome_success_and_failure_passthrough():
    ok = json.dumps({"request_id": REQ_ID, "status": "ok", "exit_code": 0,
                     "stdout_b64": base64.b64encode(b"limone\r\n").decode(), "stderr_b64": base64.b64encode(b"").decode(), "duration_ms": 1}).encode()
    out = OracleMeshExecutor._parse_user_helper_outcome(ok)
    assert out.termination == "exited" and out.exit_code == 0 and b"limone" in out.body

    refused = json.dumps({"request_id": REQ_ID, "status": "error", "error_code": "user_helper_not_read_only", "detail": "x"}).encode()
    out = OracleMeshExecutor._parse_user_helper_outcome(refused)
    assert out.exit_code == 1
    assert json.loads(out.body.decode())["error_code"] == "user_helper_not_read_only"

    out = OracleMeshExecutor._parse_user_helper_outcome(b"user_session_unavailable: helper pipe is not available")
    assert json.loads(out.body.decode())["error_code"] == USER_SESSION_UNAVAILABLE
