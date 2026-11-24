"""STEP 6 rollback contracts: non-interactive, bounded, and never blocking.

Two failure modes are pinned here:

- `wrangler rollback` prompts for a message and then for a confirmation. The
  release used to call it bare from a failure path, so it sat on a prompt that
  nothing would answer. The current rollback command defines `--message`
  (skips both prompts) and `--yes` (accepts the prompt defaults); the release
  must pass them.
- a rollback that stalls on the API must not hold the release open: the call
  runs under a bounded wait, and the timeout is recorded in the summary before
  the release moves on.

The runtime probe drives `Invoke-FrontRollbackCommand` with a fake runner
script (a .cmd that echoes or sleeps). It never touches wrangler, Cloudflare or
the network.
"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "release_chat.ps1"


def _powershell_exe():
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _extract_functions(*names):
    """Lift the shipped helpers out of release_chat.ps1 with the PowerShell AST
    so the probe exercises the real text, never a copy."""
    exe = _powershell_exe()
    if exe is None:
        raise unittest.SkipTest("no PowerShell runtime on this runner")
    wanted = "','".join(names)
    path_for_probe = str(SCRIPT).replace("'", "''")
    probe = (
        "$t=$null;$e=$null;"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{path_for_probe}',[ref]$t,[ref]$e);"
        "$out=@();"
        f"foreach ($n in @('{wanted}')) {{"
        "  $fn=$ast.Find({param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq $n},$true);"
        "  if (-not $fn) { Write-Output ('MISSING=' + $n); exit 3 }"
        "  $out += $fn.Extent.Text"
        "};"
        "$out -join \"`n\""
    )
    result = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"could not extract {names}: {result.stdout}{result.stderr}")
    return result.stdout


def _run_ps(exe, body):
    tmp = Path(tempfile.mkdtemp(prefix="rollback-probe-"))
    try:
        probe_file = tmp / "probe.ps1"
        probe_file.write_text(body, encoding="utf-8-sig")
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(probe_file)],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if result.returncode != 0:
        raise AssertionError(f"probe failed (exit {result.returncode}): {result.stdout}{result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _assert_in(needle, haystack, label=""):
    """assertIn without dumping the whole script into the failure message."""
    if needle not in haystack:
        raise AssertionError(f"missing {needle!r} {label}")


def _command_lines(text):
    """The line that builds the rollback command (not comments, log messages or
    the ComSpec error text that also mention it)."""
    return [
        line for line in text.splitlines()
        if "wrangler rollback" in line and line.lstrip().startswith("$command =")
    ]


class RollbackIsNonInteractive(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_rollback_passes_message_and_yes(self):
        lines = _command_lines(self.text)
        self.assertEqual(len(lines), 1, f"expected exactly one rollback command, got {lines}")
        _assert_in("--message release-step-failure", lines[0])
        _assert_in("--yes", lines[0], "--yes accepts the prompt defaults")
        _assert_in("wrangler rollback", lines[0])

    def test_the_version_travels_in_a_plain_parameter(self):
        # The npx.ps1 re-parse trap: no $Script:-qualified variable may reach
        # the command arguments. The command is a format string, so the version
        # is its second placeholder (the runner and log path are the others).
        _assert_in("wrangler rollback {1} --message release-step-failure --yes", self.text)
        if "wrangler rollback $Script:PrevFrontVersion" in self.text:
            raise AssertionError("the rollback version must not be a $Script:-qualified variable")


class RollbackHasABoundedWait(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")
        self.function = self.text.split("function Invoke-FrontRollbackCommand", 1)[1]
        self.function = self.function.split("\nfunction ", 1)[0]

    def test_the_wait_is_bounded_and_a_stalled_rollback_is_killed(self):
        _assert_in("$Script:RollbackTimeoutSeconds = 120", self.text)
        _assert_in("$process.WaitForExit($TimeoutSeconds * 1000)", self.function)
        # A stalled rollback must be killed as a tree (cmd -> npx -> node),
        # otherwise it keeps running after the release moved on.
        _assert_in("taskkill /T /F /PID $process.Id", self.function)
        _assert_in("$process.Kill()", self.function)
        _assert_in("Remove-Item -LiteralPath $work -Recurse -Force", self.function)

    def test_the_call_does_not_wait_on_a_prompt_or_a_pipe(self):
        # The prompt is avoided by the flags; the pipe is avoided by writing
        # wrangler's output to a file, so a full stream cannot block the wait.
        _assert_in("2>&1", self.function)
        if "Wait-Job" in self.function or "Start-Job" in self.function:
            raise AssertionError("a background job keeps the child alive; the bounded process is required")

    def test_the_timeout_is_logged_and_the_release_continues(self):
        caller = self.text.split("function Invoke-FrontRollbackIfNeeded", 1)[1]
        caller = caller.split("\nfunction ", 1)[0]
        _assert_in("if ($rollback.TimedOut) {", caller)
        _assert_in("FRONT_ROLLBACK_TIMEOUT", caller)
        _assert_in('Add-Summary "FRONT_ROLLBACK_TIMEOUT=$($Script:RollbackTimeoutSeconds)s"', caller)
        timeout_at = caller.find("FRONT_ROLLBACK_TIMEOUT")
        return_at = caller.find("return", timeout_at)
        self.assertGreater(return_at, timeout_at, "a timed-out rollback must not throw")

    def test_the_success_path_keeps_its_log_and_summary(self):
        caller = self.text.split("function Invoke-FrontRollbackIfNeeded", 1)[1]
        caller = caller.split("\nfunction ", 1)[0]
        _assert_in('Write-Info "rolling the front back to $rollbackVersion"', caller)
        _assert_in('Add-Summary "FRONT_ROLLED_BACK_TO=$rollbackVersion"', caller)


class RollbackTimedRun(unittest.TestCase):
    """Mock runners: a .cmd that answers at once, and one that sleeps past the
    budget. Nothing here executes wrangler."""

    def test_fast_runner_completes_and_a_slow_one_times_out_quickly(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        if not shutil.which("cmd"):
            self.skipTest("no cmd.exe on this runner")

        tmp = Path(tempfile.mkdtemp(prefix="rollback-mock-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        fast = tmp / "fake_fast.cmd"
        fast.write_text("@echo off\r\necho ROLLBACK_OK\r\n", encoding="ascii")
        slow = tmp / "fake_slow.cmd"
        # ~8 s of ping, so a 1 s budget must time out and a 10 s budget must not
        # wait for it in this test.
        slow.write_text("@echo off\r\nping -n 9 127.0.0.1 >nul\r\necho LATE\r\n", encoding="ascii")

        functions = _extract_functions("Invoke-FrontRollbackCommand")
        body = "\n".join([
            functions,
            "$fast = Invoke-FrontRollbackCommand -NpxRunner '" + str(fast).replace("'", "''") +
            "' -Directory '" + str(tmp).replace("'", "''") + "' -Version 'v1' -TimeoutSeconds 30",
            "Write-Output ('FAST=' + $fast.TimedOut + '|' + ($fast.Output -match 'ROLLBACK_OK'))",
            "$sw = [Diagnostics.Stopwatch]::StartNew()",
            "$slow = Invoke-FrontRollbackCommand -NpxRunner '" + str(slow).replace("'", "''") +
            "' -Directory '" + str(tmp).replace("'", "''") + "' -Version 'v1' -TimeoutSeconds 1",
            "$sw.Stop()",
            "Write-Output ('SLOW=' + $slow.TimedOut + '|' + [math]::Round($sw.Elapsed.TotalSeconds, 1))",
        ])
        lines = dict(line.split("=", 1) for line in _run_ps(exe, body) if "=" in line)

        self.assertEqual(lines.get("FAST"), "False|True", "a completed rollback keeps its output")
        self.assertTrue(lines.get("SLOW", "").startswith("True|"), lines.get("SLOW"))
        elapsed = float(lines["SLOW"].split("|", 1)[1])
        self.assertLess(elapsed, 5, f"the bounded wait did not return promptly ({elapsed}s)")


class NoModuleDependentTempFile(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_http_fetch_uses_the_dotnet_temp_name(self):
        # New-TemporaryFile lives in Microsoft.PowerShell.Utility; a PowerShell
        # 7 launch hands the script a 7-shaped PSModulePath and Windows
        # PowerShell 5.1 cannot resolve it, failing STEP 5 before the fetch.
        code = [
            line for line in self.text.splitlines()
            if "New-TemporaryFile" in line and not line.lstrip().startswith("#")
        ]
        self.assertEqual(code, [], "New-TemporaryFile needs Microsoft.PowerShell.Utility; use [IO.Path]::GetTempFileName()")
        _assert_in("[IO.Path]::GetTempFileName()", self.text)
        segment = self.text.split("function Get-HttpBytes", 1)[1]
        segment = segment.split("\nfunction ", 1)[0]
        _assert_in("[IO.Path]::GetTempFileName()", segment)
        _assert_in("Remove-Item -Force $tmp", segment)


if __name__ == "__main__":
    unittest.main()
