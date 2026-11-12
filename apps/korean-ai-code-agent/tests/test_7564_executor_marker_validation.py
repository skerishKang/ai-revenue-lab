"""#7564 - the executor-side judgments this change split out.

The marker/child verdicts run on the PC inside generated PowerShell, so the
decision logic is kept as module constants (``SWEEP_MARKER_JUDGE_PS``,
``SWEEP_CHILD_JUDGE_PS``, ``SWEEP_OWNER_SID_PS``, the pipe guard and the
secret-path guard) and run here on real PowerShell with made-up inputs. The
PowerShell drivers run only where the PC's SYSTEM lane runs - Windows
PowerShell 5.1 - so they execute on the KAgent windows-latest CI leg and skip
elsewhere; the pure Python checks below run on both CI legs.

Nothing here ends a process this suite did not start: the judgment functions
only DECIDE (kill / clean / skip); the driver never invokes taskkill, and the
pipe test talks to a pipe server it spawned itself.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kagent import local_agent_meshcentral_command_port as cp
from kagent.local_agent_oracle_mesh_executor import (
    USER_HELPER_PIPE_GUARD_PS,
    USER_HELPER_SECRET_PATH_GUARD_PS,
    OracleMeshExecutor,
)

POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
SYSTEM_SIDS = ("S-1-5-18", "S-1-5-32-544")


def _run_ps(script_path: str, timeout: float = 180.0) -> dict:
    completed = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
         "Bypass", "-File", script_path],
        capture_output=True, timeout=timeout,
    )
    out = completed.stdout.decode("utf-8", errors="replace")
    start = out.find("{")
    if start < 0:
        raise AssertionError("PowerShell driver produced no JSON: %r / %r" % (out, completed.stderr.decode("utf-8", errors="replace")))
    return json.loads(out[start:])


def _write_driver(body: str) -> str:
    handle, path = tempfile.mkstemp(suffix=".ps1")
    with os.fdopen(handle, "w", encoding="utf-8-sig") as stream:
        stream.write(body)
    return path


class MarkerScriptShapeTests(unittest.TestCase):
    """Python-visible script facts; run on both CI legs."""

    DISPATCH = "dsp_" + "ab" * 8

    def _sweep(self, mode):
        return cp.sweep_script(
            dispatch_id=self.DISPATCH, keep_dispatch_ids=(),
            mode=mode, host_tag="test-host",
        )

    def test_only_system_owned_markers_are_trusted(self):
        self.assertEqual(cp.TRUSTED_MARKER_SIDS, SYSTEM_SIDS)
        for mode in ("abandoned", "idle_console", "held"):
            script = self._sweep(mode)
            # The owner is read before any marker content is: the ACL check
            # sits between the folder listing and the first marker read.
            listed = script.find("gci -LiteralPath")
            owner_gate = script.find("-notcontains $__os", listed)
            first_content = script.find("gc -LiteralPath $__f.FullName", listed)
            self.assertLess(owner_gate, first_content, mode)
            self.assertIn("'S-1-5-18','S-1-5-32-544'", script)

    def test_no_bare_name_system_executables(self):
        # The sweep and stop scripts carry no commentary, so every taskkill
        # mention there is an invocation and must be the System32 path.
        for script in (self._sweep("abandoned"), self._sweep("idle_console"),
                       self._sweep("held"), cp.cancel_kill_command(self.DISPATCH)):
            self.assertEqual(script.count("taskkill"),
                             script.count("System32\\taskkill.exe"), script[:200])
        for script in (cp._wrap("Write-Output hi", self.DISPATCH, "test-host"),
                       cp._file_dispatch_console_script(
                           "Write-Output hi", self.DISPATCH, "test-host"),
                       OracleMeshExecutor.build_user_helper_pipe_client_ps(
                           request_id="req_x", shell="powershell", command="whoami",
                           cwd=None, timeout_seconds=10, distro=None)):
            for bare in ("& taskkill ", "& whoami", "& icacls", "& cmd ",
                         "& powershell", "&net ", "& schtasks"):
                self.assertNotIn(bare, script)

    def test_new_markers_carry_process_start_time(self):
        wrapped = cp._wrap("Write-Output hi", self.DISPATCH, "test-host")
        self.assertIn("Set-Content -LiteralPath $__padiem_pidfile -Value $PID", wrapped)
        self.assertIn("Add-Content -LiteralPath $__padiem_pidfile -Value 'test-host'", wrapped)
        self.assertIn("-Value $__padiem_dt.ToFileTime()", wrapped)
        staged = cp._file_dispatch_console_script(
            "Write-Output hi", self.DISPATCH, "test-host")
        self.assertIn("Set-Content -LiteralPath $__pp -Value $PID", staged)
        self.assertIn("-Value $__padiem_dt.ToFileTime()", staged)

    def test_stop_verifies_owner_and_start_time(self):
        script = cp.cancel_kill_command(self.DISPATCH)
        self.assertIn("'S-1-5-18','S-1-5-32-544' -contains (__padiemSid", script)
        self.assertIn(
            "[string]$__padiem_r.CreationDate.ToFileTime() -eq $__padiem_st", script)
        self.assertIn("System32\\taskkill.exe /T /F /PID $__padiem_kill", script)

    def test_child_requires_started_after_agent_in_script(self):
        script = self._sweep("idle_console")
        self.assertIn("__e.cr -le $agentCr", script)
        self.assertIn("$__e.pp -ne $agentPid", script)

    def test_scripts_stay_under_the_terminal_queue_budget(self):
        for mode in ("abandoned", "idle_console", "held"):
            script = self._sweep(mode)
            self.assertLess(len(script.encode("utf-8")),
                            cp.TERMINAL_PREQUEUE_LIMIT_BYTES, mode)
        self.assertLess(len(cp.cancel_kill_command(self.DISPATCH).encode("utf-8")),
                        cp.TERMINAL_PREQUEUE_LIMIT_BYTES)

    def test_oversize_script_is_refused_at_the_builder(self):
        saved = cp.TERMINAL_SCRIPT_BUDGET_BYTES
        try:
            cp.TERMINAL_SCRIPT_BUDGET_BYTES = 10
            with self.assertRaises(cp.MeshCentralCommandRefused):
                self._sweep("abandoned")
            with self.assertRaises(cp.MeshCentralCommandRefused):
                cp.cancel_kill_command(self.DISPATCH)
        finally:
            cp.TERMINAL_SCRIPT_BUDGET_BYTES = saved

    def test_pipe_client_checks_server_identity_before_writing(self):
        ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_x", shell="powershell", command="whoami",
            cwd=None, timeout_seconds=10, distro=None)
        check = ps.find("__PadiemPipeServerOk $client")
        self.assertGreater(check, ps.find("pipe connected"))
        self.assertLess(check, ps.find("WriteAsync($len"))
        self.assertIn("GetNamedPipeServerProcessId", ps)
        self.assertIn("WTSGetActiveConsoleSessionId", ps)
        self.assertIn("WTSQueryUserToken", ps)
        self.assertIn("helper_pipe_server_mismatch", ps)
        # Nothing the helper reports is evidence: the guard reads OS records only.
        self.assertNotIn("whoami.exe", USER_HELPER_PIPE_GUARD_PS)

    def test_pipe_client_refuses_secret_outside_expected_folder(self):
        ps = OracleMeshExecutor.build_user_helper_pipe_client_ps(
            request_id="req_x", shell="powershell", command="whoami",
            cwd=None, timeout_seconds=10, distro=None)
        self.assertIn("__PadiemSecretPathOk $secretFile", ps)
        self.assertIn("helper_secret_path_refused", ps)
        # The expected root is bound to the installer's folder at the call site.
        self.assertIn("$env:ProgramData+'\\Padiem'", ps)
        self.assertIn("GetFullPath", USER_HELPER_SECRET_PATH_GUARD_PS)
        self.assertIn("OrdinalIgnoreCase", USER_HELPER_SECRET_PATH_GUARD_PS)
        # No owner check: on installed PCs the secret may be owned by whoever
        # ran the installer, and that is not a defect of the machine.
        self.assertNotIn("Get-Acl", USER_HELPER_SECRET_PATH_GUARD_PS)


class MarkerJudgePowerShellTests(unittest.TestCase):
    """The decision functions, run on real Windows PowerShell with fake inputs.

    Runs on the KAgent windows-latest CI leg (Windows PowerShell 5.1, the same
    interpreter the PC's SYSTEM lane uses); skipped where no Windows
    PowerShell exists.
    """

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_marker_judge_decisions(self):
        driver = "\n".join([
            "$ErrorActionPreference='Stop'",
            cp.SWEEP_OWNER_SID_PS,
            cp.SWEEP_MARKER_JUDGE_PS,
            "# fake process table: cr is a file time, pp the parent pid",
            "$px=@{}",
            "$px[[uint32]4242]=@{pp=[uint32]9;cr=[long]1111;nm='cmd.exe'}",
            "$px[[uint32]4243]=@{pp=[uint32]9;cr=[long]2222;nm='cmd.exe'}",
            "$px[[uint32]4244]=@{pp=[uint32]9;cr=[long]3333;nm='cmd.exe'}",
            "$px[[uint32]4245]=@{pp=[uint32]9;cr=[long]4444;nm='cmd.exe'}",
            "$ms=@(",
            " @{id='dsp_old';pid=[uint32]4242;host='h1';st='';sid='S-1-5-18';file='C:\\t\\old.pid'},",
            " @{id='dsp_owner';pid=[uint32]4300;host='h1';st='';sid='S-1-1-0';file='C:\\t\\owner.pid'},",
            " @{id='dsp_match';pid=[uint32]4243;host='h1';st='2222';sid='S-1-5-18';file='C:\\t\\match.pid'},",
            " @{id='dsp_stale';pid=[uint32]4244;host='h1';st='9999';sid='S-1-5-18';file='C:\\t\\stale.pid'},",
            " @{id='dsp_safe';pid=[uint32]4245;host='h1';st='';sid='S-1-5-18';file='C:\\t\\safe.pid'},",
            " @{id='dsp_host';pid=[uint32]4242;host='other';st='';sid='S-1-5-18';file='C:\\t\\host.pid'},",
            " @{id='dsp_gone';pid=[uint32]4999;host='h1';st='';sid='S-1-5-18';file='C:\\t\\gone.pid'},",
            " @{id='dsp_nopid';pid=[uint32]0;host='h1';st='';sid='S-1-5-18';file='C:\\t\\nopid.pid'}",
            ")",
            "$safe=@([uint32]4245)",
            "$r1=__padiemJudgeM $ms $px $safe @() 'h1'",
            "# a $null tag is the inert case: the host comparison fails for every",
            "# marker, so a sweep that cannot name its own host ends nothing.",
            "$r2=__padiemJudgeM $ms $px $safe @() $null",
            "$old=($r1 | Where-Object { $_.dispatch -eq 'dsp_old' } | Select-Object -First 1).act",
            "$owner=($r1 | Where-Object { $_.why -eq 'owner' } | Select-Object -First 1).act",
            "$match=($r1 | Where-Object { $_.dispatch -eq 'dsp_match' } | Select-Object -First 1).act",
            "$stale=($r1 | Where-Object { $_.why -eq 'stale' } | Select-Object -First 1).act",
            "$killCount=($r1 | Where-Object { $_.act -eq 'kill' }).Count",
            "$safeD=($r1 | Where-Object { $_.why -eq 'safe' } | Select-Object -First 1).act",
            "$hostD=($r1 | Where-Object { $_.why -eq 'host' } | Select-Object -First 1).act",
            "$gone=($r1 | Where-Object { $_.why -eq 'gone' } | Select-Object -First 1).act",
            "$nopid=($r1 | Where-Object { $_.why -eq 'pid' } | Select-Object -First 1).act",
            "$nullTagKills=($r2 | Where-Object { $_.act -eq 'kill' }).Count",
            "@{old=$old; owner=$owner; match=$match; stale=$stale; killCount=$killCount;"
            " safeD=$safeD; hostD=$hostD; gone=$gone; nopid=$nopid;"
            " nullTagKills=$nullTagKills} | ConvertTo-Json -Depth 5",
        ])
        path = _write_driver(driver)
        try:
            result = _run_ps(path)
        finally:
            os.unlink(path)
        self.assertEqual(result["old"], "kill")
        self.assertEqual(result["owner"], "skip")
        self.assertEqual(result["match"], "kill")
        self.assertEqual(result["stale"], "clean")
        self.assertEqual(result["killCount"], 2)
        self.assertEqual(result["safeD"], "skip")
        self.assertEqual(result["hostD"], "skip")
        self.assertEqual(result["gone"], "clean")
        self.assertEqual(result["nopid"], "skip")
        self.assertEqual(result["nullTagKills"], 0)

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_child_judge_requires_start_after_agent(self):
        driver = "\n".join([
            "$ErrorActionPreference='Stop'",
            cp.SWEEP_CHILD_JUDGE_PS,
            "$px=@{}",
            "# the agent itself, its start time T0=1000",
            "$px[[uint32]7]=@{pp=[uint32]1;cr=[long]1000;nm='agent.exe'}",
            "# children of pid 7: after the agent, before the agent, claimed, other parent",
            "$px[[uint32]100]=@{pp=[uint32]7;cr=[long]6000;nm='powershell.exe'}",
            "$px[[uint32]101]=@{pp=[uint32]7;cr=[long]500;nm='powershell.exe'}",
            "$px[[uint32]102]=@{pp=[uint32]7;cr=[long]6000;nm='powershell.exe'}",
            "$px[[uint32]103]=@{pp=[uint32]9;cr=[long]6000;nm='other.exe'}",
            "$px[[uint32]104]=@{pp=[uint32]7;cr=[long]9000;nm='powershell.exe'}",
            "$px[[uint32]105]=@{pp=[uint32]7;cr=[long]6000;nm='powershell.exe'}",
            "$px[[uint32]106]=@{pp=[uint32]105;cr=[long]6100;nm='notconhost.exe'}",
            "# conhost child of 100: does not block it",
            "$px[[uint32]107]=@{pp=[uint32]100;cr=[long]6100;nm='conhost.exe'}",
            "$safe=@([uint32]4242)",
            "$claimed=@([uint32]102)",
            "# now = 10_000, idle bound = 3_000 ticks",
            "$idle=__padiemJudgeK $px $safe $claimed 10000 7 1000 3000 $true",
            "$held=__padiemJudgeK $px $safe $claimed 10000 7 1000 0 $false",
            "$idleKilled=(($idle | ForEach-Object { $_.pid } | Sort-Object) -join ',')",
            "$heldKilled=(($held | ForEach-Object { $_.pid } | Sort-Object) -join ',')",
            "@{idleKilled=$idleKilled; heldKilled=$heldKilled} | ConvertTo-Json -Depth 5",
        ])
        path = _write_driver(driver)
        try:
            result = _run_ps(path)
        finally:
            os.unlink(path)
        # 100: child of the agent, started after it, old enough, conhost-only
        #      children -> killed. 101: SAME parent, started BEFORE the agent ->
        #      not a child, never killed, even in the held scope. 102: a marker
        #      names it -> skipped only in the idle scope. 103: other parent.
        #      104: younger than the bound. 105: has a non-conhost child.
        self.assertEqual(result["idleKilled"], "100")
        self.assertEqual(result["heldKilled"], "100,102,104,105")

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_owner_sid_of_a_real_temp_file(self):
        handle, path = tempfile.mkstemp(suffix=".pid")
        os.close(handle)
        driver = "\n".join([
            "$ErrorActionPreference='Stop'",
            cp.SWEEP_OWNER_SID_PS,
            "$own=__padiemSid '" + path.replace("'", "''") + "'",
            "$missing=__padiemSid 'C:\\__padiem_no_such_file_7564__.pid'",
            "@{own=$own; missing=$missing; isSystem=($own -eq 'S-1-5-18' -or $own -eq 'S-1-5-32-544')} | ConvertTo-Json",
        ])
        driver_path = _write_driver(driver)
        try:
            result = _run_ps(driver_path)
        finally:
            os.unlink(path)
            os.unlink(driver_path)
        self.assertTrue(result["own"])
        self.assertEqual(result["missing"], "")
        # The test runner's own account is not one of the trusted authors.
        self.assertFalse(result["isSystem"])

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_secret_path_boundary(self):
        # The guard takes the expected root as a parameter; production binds it
        # to the installer's ProgramData folder at the call site, and the
        # binding is asserted in test_pipe_client_refuses_secret_outside_folder.
        driver = "\n".join([
            "$ErrorActionPreference='Stop'",
            USER_HELPER_SECRET_PATH_GUARD_PS,
            "$root=(Join-Path ($env:TEMP) ('padiem-7564-selftest'))",
            "$inFolder=(Join-Path $root 'helper.secret')",
            "$real=(Join-Path $env:ProgramData 'Padiem\\helper.secret')",
            "$inside=(__PadiemSecretPathOk $inFolder $root)",
            "$outside=(__PadiemSecretPathOk (Join-Path (Join-Path $env:TEMP 'elsewhere') 'helper.secret') $root)",
            "$sibling=(__PadiemSecretPathOk (Join-Path ($root+'2') 'helper.secret') $root)",
            "$relative=(__PadiemSecretPathOk 'helper.secret' $root)",
            "$empty=(__PadiemSecretPathOk '' $root)",
            "$insideReal=(__PadiemSecretPathOk $real (($env:ProgramData)+'\\Padiem'))",
            "@{inside=$inside; outside=$outside; sibling=$sibling;"
            " relative=$relative; empty=$empty; insideReal=$insideReal} | ConvertTo-Json",
        ])
        path = _write_driver(driver)
        try:
            result = _run_ps(path)
        finally:
            os.unlink(path)
        self.assertTrue(result["inside"])
        self.assertTrue(result["insideReal"])
        self.assertFalse(result["outside"])
        self.assertFalse(result["sibling"])
        self.assertFalse(result["relative"])
        self.assertFalse(result["empty"])

    @unittest.skipIf(POWERSHELL is None, "Windows PowerShell is not available")
    def test_pipe_server_identity_check_against_a_spawned_server(self):
        pipe_name = "padiem-7564-selftest"
        server = subprocess.Popen(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
             "$s=New-Object System.IO.Pipes.NamedPipeServerStream('%s',"
             "[IO.Pipes.PipeDirection]::InOut); $s.WaitForConnection();"
             " Start-Sleep -Seconds 4; $s.Dispose()" % pipe_name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        driver = "\n".join([
            "$ErrorActionPreference='Stop'",
            USER_HELPER_PIPE_GUARD_PS,
            "$c=New-Object System.IO.Pipes.NamedPipeClientStream('.',"
            " '" + pipe_name + "', [IO.Pipes.PipeDirection]::InOut)",
            "$c.Connect(20000)",
            "$__p=[uint32]0",
            "[void][PadiemPipeGuard]::GetNamedPipeServerProcessId("
            "$c.SafePipeHandle.DangerousGetHandle(),[ref]$__p)",
            "$ci=__PadiemConsoleIdentity",
            "$fakeSession=(__PadiemPipeServerOk $c 2147483000 'S-1-5-999-FAKE')",
            "$fakeUser=(__PadiemPipeServerOk $c $ci[0] 'S-1-5-999-FAKE')",
            "$realIdentity=(__PadiemPipeServerOk $c $ci[0] $ci[1])",
            "@{serverPid=$__p; fakeSession=$fakeSession; fakeUser=$fakeUser;"
            " realIdentity=$realIdentity; consoleSession=$ci[0]} | ConvertTo-Json -Depth 3",
        ])
        path = _write_driver(driver)
        try:
            result = _run_ps(path)
        finally:
            os.unlink(path)
            server.terminate()
            server.wait(timeout=30)
        # The OS names the process that owns the server side of the client's
        # own connection: the pipe server this test spawned itself.
        self.assertEqual(int(result["serverPid"]), server.pid)
        self.assertFalse(result["fakeSession"])
        self.assertFalse(result["fakeUser"])
        # realIdentity depends on where the runner's sessions live; the check
        # itself must always answer as a boolean.
        self.assertIn(result["realIdentity"], (True, False))
        self.assertGreaterEqual(int(result["consoleSession"]), 0)


if __name__ == "__main__":
    unittest.main()
