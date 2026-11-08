"""#7182b — 사용자 모드 명령이 '끝나지 않는' 두 실제 원인을 고정한다.

2026-11-08 컴1 실측(사용자 모드 ON, pc_shell whoami 1회): SYSTEM PowerShell
클라이언트가 생성되고 결과가 오지 않았다. 같은 시각 헬퍼는 정상(Running, 파이프
존재, check-user-helper.ps1 VERDICT=OK)이었으므로 헬퍼 문제가 아니었다. 프로덕션
클라이언트 스크립트를 컴1에서 그대로 실행해 확인한 두 결함:

(a) 과제 경로 불일치 — USER_HELPER_TASK_PATH 는 r"\\Padiem" 이었고, 설치기는
    ``\\Padiem\\``(끝 구분자 포함, claw_connect.user_helper_registration.TASK_FOLDER)
    으로 등록한다. Get-ScheduledTask -TaskPath 는 폴더 경로를 정확히 비교하므로
    과제를 찾지 못하고, 클라이언트는 파이프 연결 전에
    'user_session_unavailable: helper task is not registered' 로 끝났다.
    실측: 배포본 스크립트 1초·exit 1, 같은 스크립트에 ``\\Padiem\\`` 만 넣으면
    whoami 출력 1.6초. 즉 (b)/(c)/(d)가 아니라 (a)다.

(b) 클라이언트의 ``exit`` — SYSTEM 레인은 이 스크립트를
    ``& { <client> } 2>&1 | Out-String`` 안에서 실행하고 봉투(Base64)와
    ``__PADIEM_EXIT__`` 센티널은 그 블록이 끝난 뒤에만 출력한다. 클라이언트의
    ``exit 0``/``exit 1`` 은 PowerShell 자체를 먼저 종료시켜 센티널이 사라졌고,
    parse_transcript 는 센티널이 없으면 no_reply 로 읽는다. 실측: 봉투 없이
    클라이언트 JSON 만 나온 트랜스크립트 → no_reply → executor 는 성공한 whoami
    에도 'helper pipe is not available' 을 돌려줬다.

이 계약은 세 조각을 고정한다:
- 과제 경로가 설치기가 등록한 폴더와 같다(끝 구분자 포함).
- 클라이언트는 exit 하지 않고 파이프라인에 답을 쓰고 return 한다 — 봉투와
  센티널이 반드시 인쇄된다.
- 봉투 트랜스크립트(센티널 값이 비어 있는 no_exit_code 포함)는 완결된 사용자 모드
  결과로 파싱된다. 헬퍼 무응답은 연결 상한 안에서 실패로 반환된다.
"""

from __future__ import annotations

import base64
import json
import unittest

from kagent.local_agent_meshcentral_command_port import (
    MeshCentralCommandOutcome,
    parse_transcript,
)
from kagent.local_agent_oracle_mesh_executor import (
    USER_HELPER_TASK_NAME,
    USER_HELPER_TASK_PATH,
    USER_SESSION_UNAVAILABLE,
    OracleMeshDispatch,
    OracleMeshExecutor,
)

#: 설치기(`claw_connect.user_helper_registration.TASK_FOLDER`)가 등록하는 폴더.
REGISTERED_TASK_FOLDER = "\\Padiem\\"
REQ_ID = "req_" + "0" * 32


def _dispatch(**extra) -> OracleMeshDispatch:
    fields = dict(
        dispatch_id="dsp_abcdabcdabcdabcd", nonce="n" * 16, node_ref="node//X",
        file_path="C:/x", command_id="cmd_x", run_id="chat_pcq_" + "a" * 20,
        kind="command", user_mode=True, device_id="dev_x",
        command_text=json.dumps({
            "shell": "powershell", "command": "whoami", "cwd": None,
            "timeout_seconds": 30, "distro": None}),
    )
    fields.update(extra)
    return OracleMeshDispatch(**fields)


def _client_script(**extra) -> str:
    return OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id=REQ_ID, shell="powershell", command="whoami", cwd=None,
        timeout_seconds=30, distro=None, **extra,
    )


def _envelope_transcript(pc_text: str, exit_value: str = "") -> bytes:
    """The exact three lines the wrapped PC command prints (measured on 컴1)."""
    return (
        b"PADIEM_B64=" + base64.b64encode(pc_text.encode("utf-8")) + b"\r\n"
        + b"__PADIEM_EXIT__" + exit_value.encode("ascii") + b"\r\n"
    )


def _observed(pc_text: str, exit_value: str = "") -> tuple[str, MeshCentralCommandOutcome]:
    """What the port hands back for that PC transcript: parsed exactly as in production."""
    termination, code, body = parse_transcript(_envelope_transcript(pc_text, exit_value))
    return termination, MeshCentralCommandOutcome(
        termination=termination, exit_code=code, output=body)


class TheTaskPathMatchesTheInstaller(unittest.TestCase):
    def test_the_folder_is_the_one_the_installer_registers(self):
        # Get-ScheduledTask -TaskPath 는 끝 구분자까지 비교한다. 이 값이
        # '\Padiem' 이던 동안 사용자 모드 명령은 파이프에 닿지도 못했다.
        self.assertEqual(USER_HELPER_TASK_PATH, REGISTERED_TASK_FOLDER)

    def test_the_client_asks_for_that_exact_folder(self):
        script = _client_script()
        # #7196: that registered folder on disk is %SystemRoot%\System32\Tasks\Padiem,
        # and the client reads the task FILE there directly instead of calling
        # Get-ScheduledTask (a Task Scheduler COM call with no timeout of its own).
        self.assertNotIn("Get-ScheduledTask", script)
        self.assertIn(
            "System32\\Tasks\\Padiem\\" + USER_HELPER_TASK_NAME,
            script,
        )


class TheClientNeverOutlivesTheEnvelope(unittest.TestCase):
    def test_the_client_has_no_exit_statement(self):
        script = _client_script()
        # 'exit 0'/'exit 1' 은 봉투와 센티널을 인쇄하기 전에 PowerShell 을 끝낸다.
        self.assertNotIn("exit 0", script)
        self.assertNotIn("exit 1", script)
        self.assertNotIn("exit ", script.replace("exit_code", ""))

    def test_the_refusal_path_throws_aborts_the_block_and_writes_the_code(self):
        script = _client_script()
        self.assertIn("function Fail($code,$msg){ throw [string]($code+': '+$msg) }", script)
        self.assertIn("Write-Output $detail", script)

    def test_the_answer_is_written_on_the_pipeline_and_not_to_the_console(self):
        script = _client_script()
        self.assertIn("Write-Output ($reply | ConvertTo-Json -Compress)", script)
        # [Console]::Out 은 래퍼의 Out-String 을 우회해 봉투 밖으로 새어나간다.
        self.assertNotIn("[Console]::Out.Write(", script)


class TheWrappedTranscriptCompletesTheDispatch(unittest.TestCase):
    def _executor(self, outcome: MeshCentralCommandOutcome) -> OracleMeshExecutor:
        class _FakePort:
            def run_command(self, *, node_ref, command, timeout_seconds,
                            cancel_probe=None, phase_observer=None, **kwargs):
                if callable(phase_observer):
                    phase_observer("spawn")
                return outcome

        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        executor._command_port = _FakePort()
        return executor

    def test_a_real_reply_with_an_empty_sentinel_is_a_finished_command(self):
        # 컴1 2026-11-08 17:2x 실측 표본: 클라이언트가 whoami 를 마쳤을 때 PC 가
        # 인쇄한 트랜스크립트 그대로. $LASTEXITCODE 는 cmdlet 만 있는 파이프라인이라
        # 비어 있고(no_exit_code), 답은 프레임 자신의 exit_code 를 싣는다.
        reply = json.dumps({
            "request_id": REQ_ID, "status": "ok", "exit_code": 0,
            "stdout_b64": base64.b64encode(b"padiem-command-\\limone\r\n").decode("ascii"),
            "stderr_b64": "", "truncated": False, "error_code": None,
            "duration_ms": 437,
        }, separators=(",", ":"))
        termination, observed = _observed(reply)
        # 검증 대상 바깥 경계: 센티널 값이 비어 있는 완결된 답이다.
        self.assertEqual(termination, "no_exit_code")
        outcome = self._executor(observed)._execute_user_mode_command(_dispatch())
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(outcome.body, b"padiem-command-\\limone\r\n")

    def test_a_measured_silent_helper_is_a_completed_failure_not_silence(self):
        # 헬퍼가 없을 때 컴1 실측: 5.4초(연결 상한 5초) 안에 이 봉투가 인쇄된다.
        # 대기 상한 안에서 실패로 반환되고, 침묵(no_reply)이 아니다.
        termination, observed = _observed(
            "user_session_unavailable: helper pipe is not available\r\n")
        self.assertEqual(termination, "no_exit_code")
        outcome = self._executor(observed)._execute_user_mode_command(_dispatch())
        self.assertEqual(outcome.termination, "exited")
        self.assertEqual(outcome.exit_code, 1)
        body = json.loads(outcome.body.decode("utf-8"))
        self.assertEqual(body["error_code"], USER_SESSION_UNAVAILABLE)

    def test_a_reply_without_the_sentinel_stays_unanswered(self):
        # 봉투·센티널 없이 클라이언트 JSON 만 나온 상태가 바로 이번 장애의 모습이다.
        # 그것을 완료로 읽지 않는 것이 이 수정의 반대편 경계다.
        reply = json.dumps({"request_id": REQ_ID, "status": "ok", "exit_code": 0,
                            "stdout_b64": "", "stderr_b64": ""})
        self.assertEqual(
            parse_transcript(reply.encode("utf-8"))[:2], ("no_reply", None))
        observed = MeshCentralCommandOutcome(
            termination="no_reply", exit_code=None, output=reply.encode("utf-8"))
        outcome = self._executor(observed)._execute_user_mode_command(_dispatch())
        body = json.loads(outcome.body.decode("utf-8"))
        self.assertEqual(body["error_code"], USER_SESSION_UNAVAILABLE)
        self.assertEqual(body["detail"], "helper pipe is not available")


class TheClientIsBounded(unittest.TestCase):
    def test_every_pipe_step_carries_a_bound(self):
        script = _client_script()
        # 연결 5초, 프레임 쓰기 5초, 프레임 읽기 15초 — 헬퍼가 받고 죽어도
        # executor 의 단일 dispatch 루프가 무기한 열려 있지 않다.
        self.assertIn("$client.Connect(5000)", script)
        self.assertIn("if(-not $w.Wait(5000)){ throw 'helper write timeout' }", script)
        # #7184c: the default frame window is still 15s, but it can only be as
        # long as the bound it sits inside (first frame / operator reply cap).
        self.assertIn("$__wait=15000", script)
        # #7215: 프레임 읽기는 이제 짧은 슬라이스로 기다리며 대기 중에도 중지를 폴링한다.
        # 바운드는 여전히 $__wait($__by)이고 만료 시 Timeout 으로 끝난다.
        self.assertIn("$__by=[Environment]::TickCount+$__wait", script)
        self.assertIn("if([Environment]::TickCount -ge $__by){ Timeout }", script)
        self.assertIn("if(CancelCheck){ throw 'padiem_cancelled' }", script)
        # 그리고 그 실패는 코드가 붙은 한 줄로 돌아온다(침묵이 아니라 결과).
        self.assertIn("helper pipe is not available", script)


if __name__ == "__main__":
    unittest.main()
