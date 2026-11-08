"""#7182c: PC-side helper client — one wall-clock deadline, no COM, own journal.

Why this exists
---------------
On 2026-11-08 the user-mode lane stalled again after #7178/#7184/#7182 were
merged and the executor was restarted: the console agent started the client at
18:14:34, the client's PowerShell stayed alive with only a conhost child, and no
answer ever came back for minutes. Measured on 컴1 the same day, the exact
production text (client + ``_wrap``) completed in **0.4 s** as SYSTEM from a
scheduled task against the real helper (started -> stdout -> stdout -> ok), so
the client's own logic was not the blocker *in that context*.

What shipped from that measurement
----------------------------------
* the only step that could wait without a bound before the pipe opened was
  ``Get-ScheduledTask`` (Task Scheduler COM/RPC through the ScheduledTasks
  module, measured **812 ms**). It is replaced by reading the registered task's
  own file — plain bounded file I/O.
* every pipe window is clamped to one total deadline, so whatever stalls, the
  client answers ``user_session_unavailable: ... (stage=<stage>)`` instead of
  holding the console forever.
* an opt-in step journal (``C:\\ProgramData\\Padiem\\client-trace.enabled``) names
  the exact last line on the next live attempt.

These tests pin that contract on the generated text. The executable proof lives
in ``TheClientActuallyAnswersWhenTheHelperGoesQuiet`` below, which is skipped on
any host without the registered helper.
"""

import os
import re
import sys
import unittest

from kagent.local_agent_oracle_mesh_executor import (
    USER_HELPER_CLIENT_DEADLINE_FLOOR_SECONDS,
    USER_HELPER_CLIENT_DEADLINE_MARGIN_SECONDS,
    USER_HELPER_TASK_NAME,
    USER_HELPER_TASK_PATH,
    OracleMeshExecutor,
    user_helper_client_deadline_seconds,
)

REQ_ID = "req_" + "0" * 31 + "9"
TASK_ARGUMENTS = (
    '--device-id k0pVCZx5VqYn8P9FW23CaqTNZWHGSlLASVKF1tqJTPRjRGBOhcTfgZbmfi$D62t1 '
    '--secret-file "C:\\ProgramData\\Padiem\\helper.secret"'
)


def _client(**kwargs) -> str:
    kwargs.setdefault("timeout_seconds", 30)
    return OracleMeshExecutor.build_user_helper_pipe_client_ps(
        request_id=REQ_ID, shell="powershell", command="whoami", cwd=None,
        distro=None, **kwargs,
    )


class TheDeadlineIsOneNumber(unittest.TestCase):
    def test_the_deadline_sits_behind_the_helpers_own_timeout(self):
        # 헬퍼는 자기 timeout 에서 자식을 끝내고 곧바로 프레임을 보낸다. 그
        # 뒤에 남는 것은 답이 건너오는 시간뿐이다.
        self.assertEqual(
            user_helper_client_deadline_seconds(30),
            USER_HELPER_CLIENT_DEADLINE_FLOOR_SECONDS)
        self.assertEqual(
            user_helper_client_deadline_seconds(600),
            600 + USER_HELPER_CLIENT_DEADLINE_MARGIN_SECONDS)

    def test_a_missing_or_negative_timeout_still_gets_the_floor(self):
        for value in (None, 0, -1, "", "abc"):
            self.assertEqual(
                user_helper_client_deadline_seconds(value),
                USER_HELPER_CLIENT_DEADLINE_FLOOR_SECONDS,
                msg=repr(value))

    def test_the_generated_client_carries_that_number(self):
        self.assertIn(
            "$deadline=[DateTime]::UtcNow.AddSeconds(180)", _client())
        self.assertIn(
            "$deadline=[DateTime]::UtcNow.AddSeconds(720)",
            _client(timeout_seconds=600))


class NoUnboundedStepSurvives(unittest.TestCase):
    def test_the_client_never_calls_into_the_task_scheduler_module(self):
        script = _client()
        self.assertNotIn("Get-ScheduledTask", script)
        self.assertNotIn("Get-CimInstance", script)
        self.assertNotIn("New-ScheduledTask", script)

    def test_the_registered_task_is_read_from_its_own_file(self):
        script = _client()
        self.assertIn(
            "System32\\Tasks\\"
            + USER_HELPER_TASK_PATH.strip("\\") + "\\" + USER_HELPER_TASK_NAME,
            script)
        self.assertIn("[IO.File]::ReadAllText($taskFile)", script)
        # 실패는 여전히 코드가 붙은 한 줄이고, 대체 경로(SYSTEM 실행)는 없다.
        self.assertIn("helper task is not registered", script)

    def test_every_wait_is_bounded_by_the_deadline(self):
        script = _client()
        self.assertNotIn("$client.Connect(5000)", script)
        self.assertNotIn("Wait(5000)", script.replace("[Math]::Min(5000,$remain)", ""))
        self.assertNotIn("Wait(15000)", script.replace("[Math]::Min(15000,$remain)", ""))
        self.assertEqual(script.count("$remain=[int]($deadline-[DateTime]::UtcNow)"), 4)

    def test_an_expired_deadline_is_a_named_answer_not_silence(self):
        script = _client()
        for stage in ("connect", "write", "read"):
            self.assertIn(
                "user_session_unavailable: helper client deadline expired (stage="
                + stage + ")", script)
        # 코드 접두사가 붙으므로 executor 는 침묵이 아니라 결과로 읽는다.
        self.assertIn("if($detail -notmatch '^[a-z_]+: '){", script)


class NoInteractiveConsoleDependency(unittest.TestCase):
    def test_progress_and_confirmation_are_silenced(self):
        # 콘솔이 붙은 상태에서 진행 표시나 확인 대기가 끼어들지 않는다.
        script = _client()
        self.assertIn("$ProgressPreference='SilentlyContinue'", script)
        self.assertIn("$ConfirmPreference='None'", script)
        self.assertIn("$ErrorActionPreference='Stop'", script)


class TheStepJournalIsOffUnlessAsked(unittest.TestCase):
    def test_the_journal_needs_the_operator_marker_or_the_env_switch(self):
        script = _client()
        self.assertIn(
            "[IO.File]::Exists('C:\\ProgramData\\Padiem\\client-trace.enabled')",
            script)
        self.assertIn("PADIEM_HELPER_CLIENT_TRACE", script)

    def test_the_journal_cannot_grow_without_a_bound(self):
        script = _client()
        self.assertIn("-gt 262144", script)

    def test_the_journal_has_no_secret_or_device_id_or_command(self):
        script = _client()
        journal = script.split("function T([string]$s){", 1)[1].split("}\n$stage=", 1)[0]
        for leak in ("$secret", "$deviceId", "$arg", "$command", "helper.secret"):
            self.assertNotIn(leak, journal)
        for stage in re.findall(r"T \(?['\"]([^'\"]+)", script):
            self.assertNotIn("k0pVCZx5", stage)

    def test_the_journal_names_each_stage(self):
        script = _client()
        for stage in ("start", "task_lookup", "task_parsed", "hmac", "connect",
                      "connected", "request_written", "reply_ready"):
            self.assertIn("T '" + stage + "'", script)


class TheClientActuallyAnswersWhenTheHelperGoesQuiet(unittest.TestCase):
    """Executable proof of the bound (컴1 only, skipped elsewhere).

    Runs the generated client as SYSTEM from a one-shot scheduled task against a
    helper whose child never ends, with the deadline seam at 5 s. Before #7182c
    this shape left a PowerShell alive with no output; now the client answers with
    a code-prefixed line that names the stage.
    """

    PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    TASK_NAME = "Padiem7182cDeadlineProbe"

    def setUp(self):
        if os.name != "nt":
            self.skipTest("Windows-only probe")
        if not os.path.exists(self.PS):
            self.skipTest("no Windows PowerShell")
        self.trace = r"C:\ProgramData\Padiem\client-trace.log"
        self.marker = r"C:\ProgramData\Padiem\client-trace.enabled"
        if not os.path.isdir(r"C:\ProgramData\Padiem"):
            self.skipTest("no Padiem program data directory")

    def _run(self, client: str) -> tuple[str, float]:
        import base64
        import subprocess
        import tempfile
        import time
        from kagent.local_agent_meshcentral_command_port import _wrap
        import pathlib

        encoded = base64.b64encode(
            _wrap(client, "dsp_abcdef0123456789", None).encode("utf-16-le")).decode("ascii")
        script = (
            "$ErrorActionPreference='Stop'\r\n"
            "$enc='" + encoded + "'\r\n"
            "$a=New-ScheduledTaskAction -Execute '" + self.PS + "' -Argument "
            "('-NoProfile -ExecutionPolicy Bypass -EncodedCommand ' + $enc)\r\n"
            "$p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest\r\n"
            "Register-ScheduledTask -TaskName '" + self.TASK_NAME + "' -Action $a -Principal $p -Force | Out-Null\r\n"
            "Start-ScheduledTask -TaskName '" + self.TASK_NAME + "'\r\n"
        )
        handle = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig")
        handle.write(script)
        handle.close()
        pathlib.Path(self.marker).write_text("1", encoding="ascii")
        try:
            os.path.exists(self.trace) and os.remove(self.trace)
        except OSError:
            pass
        started = time.monotonic()
        try:
            subprocess.run([self.PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", handle.name],
                           capture_output=True, timeout=120)
            deadline = started + 90
            while time.monotonic() < deadline:
                if os.path.exists(self.trace) and "reply_ready" in open(
                        self.trace, encoding="utf-8", errors="replace").read():
                    break
                if os.path.exists(self.trace) and "fail " in open(
                        self.trace, encoding="utf-8", errors="replace").read():
                    break
                time.sleep(0.5)
        finally:
            try:
                os.remove(handle.name)
            except OSError:
                pass
        elapsed = time.monotonic() - started
        text = open(self.trace, encoding="utf-8", errors="replace").read() if os.path.exists(self.trace) else ""
        return text, elapsed

    def tearDown(self):
        try:
            os.remove(self.marker)
        except OSError:
            pass
        import subprocess
        subprocess.run([self.PS, "-NoProfile", "-Command",
                        "Unregister-ScheduledTask -TaskName '" + self.TASK_NAME + "' -Confirm:$false -ErrorAction SilentlyContinue"],
                       capture_output=True, timeout=60)

    def test_a_helper_that_ignores_the_deadline_gets_an_answer(self):
        # 자식이 120초 자는 명령 + 5초 클라이언트 기한. 예전에는 5초 뒤에도
        # 아무 출력 없이 살아 있었다.
        client = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_" + "7" * 31 + "1", shell="powershell",
            command="Start-Sleep -Seconds 120", cwd=None, timeout_seconds=300,
            distro=None, deadline_seconds=5)
        trace, elapsed = self._run(client)
        self.assertIn("request_written", trace)
        self.assertIn("helper client deadline expired", trace)
        self.assertLess(elapsed, 60)

    def test_the_same_client_still_completes_a_normal_command(self):
        client = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_" + "8" * 31 + "2", shell="powershell",
            command="whoami", cwd=None, timeout_seconds=30, distro=None)
        trace, elapsed = self._run(client)
        self.assertIn("reply_ready", trace)
        self.assertIn("frame ok", trace)
        self.assertLess(elapsed, 60)


if __name__ == "__main__":
    unittest.main()
