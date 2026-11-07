"""check-user-helper.ps1 contracts: parse, secret hygiene, pipe-name rule.

The tool is the one-shot read-only diagnosis the CTO runs around the
helper EXE swap (docs/operations/PC_USER_HELPER_RELEASE_20261107.md
step 6). CI verifies it parses, never reads the secret file's content,
and derives the same pipe name as the Python implementation — fixed
vector, computed here with hashlib exactly like
claw_connect.user_session_helper.device_id_pipe_suffix.
"""
from pathlib import Path
import hashlib
import re
import shutil
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "tools" / "check-user-helper.ps1"

# MeshCentral-shaped raw id with '$' — the same shape the helper tests use.
VECTOR_RAW = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
VECTOR_PIPE = "padiem-user-helper-dev_" + hashlib.sha256(
    VECTOR_RAW.encode("utf-8")).hexdigest()[:32]


def _powershell_exe():
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _run_powershell(exe, *args):
    return subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *args],
        capture_output=True, text=True, timeout=300,
    )


class ParserAndHygiene(unittest.TestCase):
    def setUp(self):
        self.text = TOOL.read_text(encoding="utf-8")

    def test_parses_without_errors(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        script_path = str(TOOL) if Path(exe).name.lower().startswith("powershell") else TOOL.as_posix()
        parse_cmd = (
            "$t=$null;$e=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$t, [ref]$e);"
            "if ($e.Count -gt 0) { $e | ForEach-Object { Write-Output $_.Message }; exit 1 }"
            "else { Write-Output 'PARSE_OK' }"
        )
        result = _run_powershell(exe, "-Command", parse_cmd)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PARSE_OK", result.stdout)

    def test_never_reads_the_secret_file_content(self):
        # The whole tool must have no content-reading primitive at all: the
        # EXE hash reads bytes via [System.IO.File]::ReadAllBytes, so only
        # Get-Content / ReadAllText / -Raw are banned outright, and the
        # ReadAllBytes call must sit on a line that never mentions the secret.
        for token in ("Get-Content", "ReadAllText", " -Raw", "cat ", "Select-String"):
            self.assertNotIn(token, self.text, token)
        for number, line in enumerate(self.text.splitlines(), start=1):
            if "ReadAllBytes" in line:
                self.assertNotIn("secret", line.lower(), f"line {number}: {line.strip()}")
            if "helper.secret" in line.lower():
                self.assertRegex(
                    line,
                    r"(Test-Path|Get-Item|Get-Acl|SecretPath\s*=|^#|never|NEVER|"
                    r"existence|metadata)",
                    f"line {number} touches the secret path outside metadata access: {line.strip()}",
                )
        # The header states the rule and the secret path only ever flows into
        # metadata cmdlets via the one $Script:SecretPath variable.
        self.assertIn("NEVER reads", self.text)
        self.assertEqual(self.text.count("$Script:SecretPath = "), 1)

    def test_output_is_key_value_lines_only(self):
        for number, line in enumerate(self.text.splitlines(), start=1):
            if "Out-Line" in line and "^" not in line and "function Out-Line" not in line:
                # Literal keys and the computed SECRET_ACL_n key are the only
                # accepted shapes; everything prints KEY=VALUE.
                self.assertRegex(
                    line.strip(),
                    r"^Out-Line (\(|')",
                    f"line {number}: {line.strip()}",
                )


class PipeNameRule(unittest.TestCase):
    def test_fixed_vector_matches_the_python_rule(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        script_path = str(TOOL) if Path(exe).name.lower().startswith("powershell") else TOOL.as_posix()
        result = _run_powershell(
            exe, "-File", script_path, "-PrintPipeNameOnly", "-DeviceId", VECTOR_RAW,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"PIPE_NAME={VECTOR_PIPE}")

    def test_fixed_vector_value(self):
        # The vector itself: sha256(utf-8(raw)) hex[:32] behind the shared
        # prefix — the same derivation as
        # claw_connect.user_session_helper.device_id_pipe_suffix.
        suffix = "dev_" + hashlib.sha256(VECTOR_RAW.encode("utf-8")).hexdigest()[:32]
        self.assertRegex(suffix, r"^dev_[0-9a-f]{32}$")
        self.assertEqual(VECTOR_PIPE, "padiem-user-helper-" + suffix)


if __name__ == "__main__":
    unittest.main()
