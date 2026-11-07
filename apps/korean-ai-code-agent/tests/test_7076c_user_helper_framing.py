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
REQ_ID = "req_" + "a" * 32


def test_executor_ps_embeds_exact_helper_request_material():
    cmd = "whoami"
    ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
        device_id=DEVICE, request_id=REQ_ID, shell="whoami", command=cmd,
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
    assert "padiem-user-helper-" + DEVICE in ps
    assert "Get-ScheduledTask" in ps and "--secret-file" in ps
    # discovers secret file path via scheduled task args on target PC; secret value never embedded


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
