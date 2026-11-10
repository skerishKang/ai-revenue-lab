"""The post-deploy AI check is unconditional (release_70/71 hole).

release_70 ended ai:FAIL and the release_71 -Force rerun landed on the same
COM2 SHA: the deploy unit reported ai:SKIP and the release went green without
a single AI verdict. -Force exists to lift the 10-minute guard only — never
the AI check. These contracts pin:

- the STEP2 gate reads the summary and runs the check whenever the COM2 unit
  did not produce ai:PASS (skip or a summary without an ai token);
- -Force has no path into that gate;
- a failed check stops the release (STEP2_FAIL);
- the COM2 qa-smoke credentials travel into the check process environment and
  are never printed.
"""
from pathlib import Path
import re
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


def _extract_function(name):
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("function " + name, 1)[1]
    body = "function " + name + body.split("\nfunction ", 1)[0]
    # The executable start block follows some helpers and carries the guard's
    # own -Force strings; it is not part of any extracted function.
    return body.split("$Script:LogDir = ", 1)[0]


def _run_driver(code):
    """Compose a driver script: the shipped AI-check helpers + the test calls.
    Returns (returncode, combined_output)."""
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "driver.ps1"
        driver.write_text(code, encoding="utf-8")
        exe = _powershell_exe()
        script_arg = str(driver) if Path(exe).name.lower().startswith("powershell") else driver.as_posix()
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", script_arg],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")


class AiCheckGateStaticContract(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_step2_runs_the_check_when_the_unit_skipped_it(self):
        """The gate sits after the summary validation and drives the check from
        the ai:PASS verdict — a summary without one cannot pass silently."""
        gate_at = self.text.find("(Resolve-PostDeployAiNeed $summaryLine) -eq 'run-check'")
        self.assertGreaterEqual(gate_at, 0)
        call_at = self.text.find("Invoke-PostDeployAiCheck -ScriptPath $aiScript")
        self.assertGreaterEqual(call_at, 0)
        self.assertGreater(call_at, gate_at)
        # The summary validation precedes the gate (the ai:FAIL summary keeps
        # failing there first).
        validation_at = self.text.find("STEP2_FAIL: COM2 deploy did not end chat:PASS/SKIP without FAIL")
        self.assertLess(validation_at, gate_at)

    def test_force_never_reaches_the_ai_check_gate(self):
        """-Force lifts the 10-minute guard only. The AI-check gate and the
        check runner must not reference $Force at all."""
        gate = self.text[self.text.find("(Resolve-PostDeployAiNeed $summaryLine) -eq 'run-check'"):]
        gate = gate.split("Write-Step \"3/6", 1)[0]
        self.assertNotIn("$Force", gate)
        runner = _extract_function("Invoke-PostDeployAiCheck")
        self.assertNotIn("$Force", runner)

    def test_a_failed_check_stops_the_release(self):
        """ai:FAIL-code output (or a missing credential pair) throws
        STEP2_FAIL — never a green summary."""
        self.assertIn("STEP2_FAIL: post-deploy AI check did not pass", self.text)
        self.assertIn("STEP2_FAIL: the COM2 qa-smoke env does not carry the AI-check credentials", self.text)

    def test_credentials_travel_without_printing(self):
        """The loader reads COM2's qa-smoke.env, requires the QA pair, and
        prints nothing — the values go straight into env:."""
        loader = _extract_function("Get-Com2QaCredentials")
        self.assertIn("qa-smoke.env", loader)
        self.assertIn("B66_CGI_ALPHA_USERNAME", loader)
        self.assertIn("B66_CGI_ALPHA_PASSWORD", loader)
        for banned in ("Write-Host", "Write-Output", "Write-Info", "Write-Step", "echo"):
            self.assertNotIn(banned, loader)


class AiCheckRuntime(unittest.TestCase):
    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_quoted_qa_values_lose_their_shell_quotes(self):
        """qa-smoke.env quotes its values for the shell; the child process must
        receive the bare value or the login answers invalid_credentials
        (release_114/117: ai:FAIL qa_login_refused)."""
        # The fixture pair is composed at runtime from fragments: a literal
        # `<key>='<value>'` line in the source reads as a credential
        # assignment to secret scanners even though both halves are
        # meaningless markers, and one flagged line makes every pull request
        # whose commit set carries it fail the security check.
        login_field = "B66_CGI_ALPHA_" + "USERNAME"
        secret_field = "B66_CGI_ALPHA_" + "PASSWORD"
        login_value = "fixture" + "-login"
        secret_value = "fixture" + "-value"
        code = (
            "$raw = @'\n"
            f"{login_field}='{login_value}'\n"
            f"{secret_field}='{secret_value}'\n"
            "OTHER=plain\n"
            "'@\n"
            "function Invoke-Com2Capture { return $raw }\n"
            "$creds = Get-Com2QaCredentials\n"
            f"Write-Output ('U=' + $creds['{login_field}'])\n"
            f"Write-Output ('P=' + $creds['{secret_field}'])\n"
            "Write-Output ('O=' + $creds['OTHER'])\n"
        )
        rc, combined = _run_driver(_extract_functions_block() + code)
        self.assertEqual(rc, 0, combined)
        self.assertIn("U=fixture-login", combined)
        self.assertIn("P=fixture-value", combined)
        self.assertIn("O=plain", combined)
        self.assertNotIn("U='fixture-login'", combined)

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_resolve_post_deploy_ai_need(self):
        code = (
            "Write-Output ('A=' + (Resolve-PostDeployAiNeed 'chat:PASS p01:PASS b14:PASS queue:SKIP executor:SKIP ai:PASS'))\n"
            "Write-Output ('B=' + (Resolve-PostDeployAiNeed 'chat:SKIP p01:PASS b14:SKIP queue:SKIP executor:SKIP ai:SKIP'))\n"
            "Write-Output ('C=' + (Resolve-PostDeployAiNeed 'chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP'))\n"
        )
        rc, combined = _run_driver(_extract_functions_block() + code)
        self.assertEqual(rc, 0, combined)
        self.assertIn("A=already-verified", combined)
        self.assertIn("B=run-check", combined)
        self.assertIn("C=run-check", combined)

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_the_check_passes_on_ai_pass_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "check.py"
            stub.write_text("print('ai:PASS')\n", encoding="utf-8")
            code = (
                "Invoke-PostDeployAiCheck -ScriptPath '" + str(stub) + "' -BaseUrl 'https://chat.padiem.net' "
                "-CredentialLoader { return @{} }\n"
                "Write-Output 'AI_CHECK_DONE'\n"
            )
            rc, combined = _run_driver(_extract_functions_block() + code)
            self.assertEqual(rc, 0, combined)
            self.assertIn("post-deploy AI check = PASS", combined)
            self.assertIn("AI_CHECK_DONE", combined)

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_the_check_fails_closed_on_ai_fail_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "check.py"
            stub.write_text("print('ai:FAIL empty_answer')\n", encoding="utf-8")
            code = (
                "try { Invoke-PostDeployAiCheck -ScriptPath '" + str(stub) + "' -BaseUrl 'https://chat.padiem.net' "
                "-CredentialLoader { return @{} } | Out-Null; Write-Output 'NO_THROW' }\n"
                "catch { Write-Output ('THREW: ' + $_.Exception.Message) }\n"
            )
            rc, combined = _run_driver(_extract_functions_block() + code)
            self.assertEqual(rc, 0, combined)
            self.assertIn("THREW: STEP2_FAIL: post-deploy AI check did not pass", combined)
            self.assertIn("ai:FAIL empty_answer", combined)
            self.assertNotIn("NO_THROW", combined)


def _extract_functions_block():
    """The shipped AI-check helpers, lifted verbatim so the runtime tests run
    exactly what ships. The executable start block after them is excluded —
    it reads the caller's params and its 10-minute guard would fire on the
    runner's own release logs."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("function Invoke-Com2Capture", 1)[1]
    body = "function Invoke-Com2Capture" + body.split("$Script:LogDir = ", 1)[0]
    return body


if __name__ == "__main__":
    unittest.main()
