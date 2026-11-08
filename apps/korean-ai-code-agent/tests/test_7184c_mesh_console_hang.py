"""#7184c — MeshAgent 원격 콘솔에서 사용자 모드 whoami 가 멈추던 경로를 고정한다.

2026-11-08 컴1 실측(사용자 모드 ON, pc_shell whoami):
- executor 저널: claimed → start → spawn(18:14:34.837) 이후 기록 없음.
  MeshAgent 아래 SYSTEM powershell 하나가 conhost 만 자식으로 두고 대기했고,
  pc_shell_stop 을 보내도 남았다.
- 같은 클라이언트 텍스트를 그대로 돌리면 세션 1 은 1.7초, SYSTEM 세션 0(예약 작업
  일회성)은 2.3초에 봉투와 센티널을 인쇄한다. 즉 "느린 단계"는 없고, 답이 나오지
  않은 상태가 콘솔을 점유한 채 남는다.

원인 두 조각:
(a) 사용자 모드 dispatch 가 dispatch_id 를 포트에 넘기지 않아 PC 의 .pid 표식이
    만들어지지 않았다. PC 쪽 stop 은 그 표식만 읽으므로(pc_shell_stop), 멈춘
    클라이언트를 끝낼 방법이 없었다. SYSTEM 레인은 같은 값을 넘긴다.
(b) 클라이언트의 헬퍼 첫 프레임 대기에는 상한이 없었다. 헬퍼는 사용자 자식이 사는
    동안 5초마다 heartbeat('running')를 보내고, 클라이언트는 그 프레임마다 15초
    대기 창을 새로 열었다. 자식이 끝나지 않으면 클라이언트도 끝나지 않고, 그동안
    그 PC 의 콘솔은 점유된 채라 MeshCentral 은 뒤따르는 runcommand 를 큐에 넣지
    않고 버린다(포트의 #7177 주석이 기록한 동작).

또한 whoami 처럼 한 번에 답하는 셸의 출력은 마지막 프레임의 stdout_b64 로 오는데,
클라이언트는 스트리밍 프레임만 모아서 성공한 whoami 가 빈 출력으로 돌아왔다(실측).

이 계약이 고정하는 것:
- 사용자 모드도 SYSTEM 과 같은 dispatch_id 표식을 남긴다.
- 첫 프레임 대기에는 상한이 있고, 넘으면 코드가 붙은 한 줄로 끝난다.
- 작업 대기(heartbeat)는 소유자의 stop 이 끝내며, 운영자 상한
  (PADIEM_MESH_USER_HELPER_REPLY_SECONDS)이 있을 때만 시간으로도 끝난다.
- 마지막 출력은 반환 전에 flush 되고, 한 번에 오는 답의 본문도 버려지지 않는다.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from kagent.local_agent_meshcentral_command_port import (
    MeshCentralCommandOutcome,
    _file_dispatch_console_script,
    _pid_file_literal,
    _wrap,
    parse_transcript,
)
from kagent.local_agent_oracle_mesh_executor import OracleMeshDispatch, OracleMeshExecutor

POWERSHELL = "powershell.exe"
DEVICE = "dev_diag7184c"
REQ_ID = "req_" + "c" * 32
SECRET_BYTES = b"unittest-dummy-secret-not-a-real-key"
WINDOWS_ONLY = unittest.skipUnless(sys.platform == "win32", "named pipes are Windows only")


def _client_text(**extra) -> str:
    fields = dict(request_id=REQ_ID, shell="whoami", command="whoami", cwd=None,
                  timeout_seconds=0, distro=None)
    fields.update(extra)
    return OracleMeshExecutor.build_user_helper_pipe_client_ps(**fields)


def _encoded(text: str) -> str:
    return base64.b64encode(text.encode("utf-16-le")).decode("ascii")


#: 헬퍼의 두 가지 실제 정지 모양. 'silent' 는 연결만 받고 말이 없고,
#: 'heartbeat' 는 started 뒤 5초 heartbeat 를 계속 보내며 자식은 끝나지 않는다.
_FAKE_HELPER = r"""
$sha=[System.Security.Cryptography.SHA256]::Create()
$digest=-join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes('@@DEVICE@@')) | ForEach-Object { $_.ToString('x2') })
$name='padiem-user-helper-dev_'+$digest.Substring(0,32)
$srv=New-Object System.IO.Pipes.NamedPipeServerStream($name,[System.IO.Pipes.PipeDirection]::InOut,1,[System.IO.Pipes.PipeTransmissionMode]::Byte,[System.IO.Pipes.PipeOptions]::None)
if($env:PADIEM_FAKE_READY){ try{ Set-Content -LiteralPath $env:PADIEM_FAKE_READY -Value 'ready' -Encoding ascii }catch{} }
$srv.WaitForConnection()
# The real helper reads the request before it answers; a fake that never reads
# makes the client's own write wait, which is a different failure.
$hdr=New-Object byte[] 4; $rd=0
while($rd -lt 4){ $n=$srv.Read($hdr,$rd,4-$rd); if($n -le 0){ break }; $rd+=$n }
[Array]::Reverse($hdr); $rlen=[System.BitConverter]::ToInt32($hdr,0)
$frame=New-Object byte[] $rlen; $rd=0
while($rd -lt $rlen){ $n=$srv.Read($frame,$rd,$rlen-$rd); if($n -le 0){ break }; $rd+=$n }
function Send([string]$j){ $b=[Text.Encoding]::UTF8.GetBytes($j); $l=[BitConverter]::GetBytes([int]$b.Length); [Array]::Reverse($l); $srv.Write($l,0,4); $srv.Write($b,0,$b.Length); $srv.Flush() }
if('@@MODE@@' -eq 'silent'){ Start-Sleep -Seconds @@SECONDS@@ }
else {
  Send ('{"request_id":"@@RID@@","status":"started"}')
  $n=0; $end=(Get-Date).AddSeconds(@@SECONDS@@)
  while((Get-Date) -lt $end){ Start-Sleep -Milliseconds 300; $n++; Send ('{"request_id":"@@RID@@","status":"running","heartbeat":'+$n+'}') }
}
$srv.Dispose()
"""


def _fake_helper_text(mode: str, seconds: int) -> str:
    return (_FAKE_HELPER.replace("@@DEVICE@@", DEVICE).replace("@@MODE@@", mode)
            .replace("@@SECONDS@@", str(seconds)).replace("@@RID@@", REQ_ID))


class TheUserModeClientCanBeStopped(unittest.TestCase):
    def test_the_dispatch_hands_its_dispatch_id_to_the_port(self):
        captured: dict = {}

        class _Port:
            def run_command(self, **kwargs):
                captured.update(kwargs)
                return MeshCentralCommandOutcome(
                    termination="no_reply", exit_code=None, output=b"")

        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        executor._command_port = _Port()
        executor._active_lock = threading.Lock()
        executor._active_by_node = {}
        executor._active_background = ()
        dispatch = OracleMeshDispatch(
            dispatch_id="dsp_abcdabcdabcdabcd", nonce="n" * 16, node_ref="node//X",
            file_path="C:/x", command_id="cmd_x", run_id="chat_pcq_" + "a" * 20,
            kind="command", user_mode=True, device_id="dev_x",
            command_text=json.dumps({"shell": "whoami", "command": "whoami", "cwd": None,
                                     "timeout_seconds": 0, "distro": None}),
        )
        executor._execute_user_mode_command(dispatch)
        # PC 쪽 stop 은 이 표식만 읽는다. 없던 동안 pc_shell_stop 은 끝낼 파일을
        # 찾지 못했고, 멈춘 클라이언트는 콘솔을 계속 점유했다.
        self.assertEqual(captured["dispatch_id"], "dsp_abcdabcdabcdabcd")
        # #7199: user mode is delivered as a staged file, not the console body. The
        # marker still lives in what the console runs, so pc_shell_stop finds it; the
        # staging script writes it before it runs the client with -File.
        self.assertIs(captured["deliver_as_file"], True)
        console = _file_dispatch_console_script(
            captured["command"], captured["dispatch_id"], None)
        self.assertIn(_pid_file_literal("dsp_abcdabcdabcdabcd"), console)
        self.assertIn("-File $__fp", console)


class EveryWaitInTheClientHasABound(unittest.TestCase):
    def test_the_first_reply_frame_is_bounded(self):
        script = _client_text()
        self.assertIn("PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS", script)
        self.assertIn("first-frame deadline expired", script)
        # 첫 프레임 뒤에는 그 상한이 풀린다: 그 뒤의 대기는 작업이다.
        self.assertIn("$__firstBy=0", script)

    def test_the_work_wait_keeps_a_separate_operator_cap(self):
        script = _client_text()
        self.assertIn("PADIEM_MESH_USER_HELPER_REPLY_SECONDS", script)
        self.assertIn("overall deadline expired", script)
        # 요청 timeout_seconds 는 서명 재료일 뿐 마감이 아니다(#7107): 직접 마감으로
        # 쓰면 건강한 32초 명령이 잘렸다. 그래서 전체 기한은 max(180, timeout+120)로
        # 구워 두고(#7196, timeout_seconds=0 이므로 180), 운영자 스위치가 이를
        # 덮어쓴다 — 양수면 그 초, 음수면 끈다.
        self.assertNotIn("$req.timeout_seconds -gt 0", script)
        self.assertIn("$__overall=180", script)
        self.assertIn("if($__cap -gt 0)", script)

    def test_the_answer_is_flushed_before_the_script_returns(self):
        self.assertIn("[Console]::Out.Flush()", _client_text())
        self.assertIn("[Console]::Out.Flush()", _wrap("Write-Output 1", None, None))

    def test_a_one_shot_reply_body_is_not_dropped(self):
        script = _client_text()
        self.assertIn("$__finalOut=[string]$frame.stdout_b64", script)
        self.assertIn("$stdout.AddRange([byte[]][Convert]::FromBase64String($__finalOut))", script)


class TheMeasuredWedgesEndOnTheirOwn(unittest.TestCase):
    """실제 래퍼 텍스트를 그대로 돌려 두 정지 상태의 끝을 확인한다."""

    def _run(self, mode: str, env_extra: dict, tmp: Path) -> tuple[float, str]:
        secret = tmp / "diag.secret"
        secret.write_bytes(SECRET_BYTES)
        args = f'--device-id "{DEVICE}" --secret-file "{secret}"'
        wrapped = _wrap(_client_text(task_arguments=args), None, None)
        ready = tmp / 'fake-ready.txt'
        server_env = dict(os.environ)
        server_env['PADIEM_FAKE_READY'] = str(ready)
        server = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-EncodedCommand", _encoded(_fake_helper_text(mode, 20))],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=server_env,
        )
        try:
            wait_until = time.monotonic() + 25
            while not ready.exists() and time.monotonic() < wait_until:
                time.sleep(0.1)
            self.assertTrue(ready.exists(), 'fake helper never started')
            env = dict(os.environ)
            env.update(env_extra)
            started = time.monotonic()
            completed = subprocess.run(
                [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-EncodedCommand", _encoded(wrapped)],
                capture_output=True, timeout=60, env=env,
            )
            elapsed = time.monotonic() - started
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except Exception:
                pass
        return elapsed, (completed.stdout or b"").decode("utf-8", "replace")

    @WINDOWS_ONLY
    def test_a_helper_that_accepts_and_says_nothing_is_a_failure_not_a_wait(self):
        with tempfile.TemporaryDirectory() as raw:
            elapsed, output = self._run(
                "silent", {"PADIEM_MESH_USER_HELPER_FIRST_FRAME_SECONDS": "3"}, Path(raw))
        self.assertLess(elapsed, 30, f"still waiting after {elapsed:.1f}s")
        _termination, _code, body = parse_transcript(output.encode("utf-8"))
        self.assertIn(b"first-frame deadline expired", body)

    @WINDOWS_ONLY
    def test_heartbeats_cannot_extend_the_wait_past_the_operator_cap(self):
        # 이번 장애의 모양: 헬퍼는 살아 heartbeat 를 보내고 자식은 끝나지 않는다.
        # 운영자 상한이 없으면 클라이언트는 무기한 대기하고 콘솔은 점유된다.
        with tempfile.TemporaryDirectory() as raw:
            elapsed, output = self._run(
                "heartbeat", {"PADIEM_MESH_USER_HELPER_REPLY_SECONDS": "4"}, Path(raw))
        self.assertLess(elapsed, 30, f"still waiting after {elapsed:.1f}s")
        _termination, _code, body = parse_transcript(output.encode("utf-8"))
        self.assertIn(b"overall deadline expired", body)


if __name__ == "__main__":
    unittest.main()
