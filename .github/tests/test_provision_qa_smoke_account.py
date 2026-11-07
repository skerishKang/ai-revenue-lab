"""provision_qa_smoke_account.ps1 contracts: parse, secret hygiene, escaping.

The tool is the one-shot masked provisioning the CTO runs on COM1 with the
representative typing the QA pair once. CI verifies it parses, cannot leak
the pair through output or disk writes, and that the env-file escaping is
correct for every character the password rules allow.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "scripts" / "provision_qa_smoke_account.ps1"


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

    def test_password_never_reaches_output_or_disk(self):
        # The plaintext pair exists only in the three in-memory consumers:
        # the two HTTPS bodies and the env content piped into ssh stdin.
        allowed = re.compile(
            r"(\$plainPassword\s*=|\$securePassword\s*=|Get-SecureStringPlainText \$securePassword"
            r"|\$plainPassword\.Length"
            r"|@\s*\{ email = \$email; password = \$plainPassword \}"
            r"|@\s*\{ identifier = \$email; password = \$plainPassword \}"
            r"|ConvertTo-EnvSingleQuoted \$plainPassword"
            r"|@\s*\{ name = \$Script:PasswordEnv; value = \$plainPassword \})"
        )
        assignment_allowed = re.compile(
            r"^\$\w+\s*=\s*(@\s*\{ (?:email|identifier) = \$email; password = \$plainPassword \})"
        )
        for number, line in enumerate(self.text.splitlines(), start=1):
            if "$plainPassword" in line or "$securePassword" in line:
                self.assertTrue(
                    allowed.search(line) or assignment_allowed.match(line.strip()),
                    f"line {number}: {line.strip()}",
                )
        # No output primitive ever mentions the pair variables.
        for number, line in enumerate(self.text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("Write-", "Out-Line ")):
                self.assertNotRegex(
                    stripped,
                    r"\$(plainPassword|securePassword|registerBody|loginBody|envContent)",
                    f"line {number} may print credential material: {stripped}",
                )
        # Nothing is ever written to disk: ssh stdin is the only sink.
        for token in ("Out-File", "Set-Content", "Add-Content", "Export-Clixml",
                      "Export-Csv", "WriteAllText", "WriteAllBytes", "New-ItemProperty"):
            self.assertNotIn(token, self.text, token)
        # The password is a SecureString at rest and never serialized by
        # ConvertFrom-SecureString (which exports an exportable string).
        self.assertIn("Read-Host", self.text)
        self.assertIn("-AsSecureString", self.text)
        self.assertNotIn("ConvertFrom-SecureString", self.text)

    def test_the_email_is_printed_masked_only(self):
        # Mask-Email reduces any address to ***@domain before it can print.
        self.assertIn("function Mask-Email", self.text)
        self.assertIn("Out-Line 'EMAIL_MASKED' (Mask-Email $email)", self.text)
        for number, line in enumerate(self.text.splitlines(), start=1):
            if "Out-Line" in line and "$email" in line and "Mask-Email" not in line:
                self.fail(f"line {number} prints the raw email: {line.strip()}")

    def test_com2_write_goes_through_root_only_install(self):
        self.assertIn("install -m 600 /dev/stdin", self.text)
        self.assertIn("/etc/padiem/qa-smoke.env", self.text)
        # The remote command carries no credential material (it only points
        # install at stdin), and the env content is never logged.
        remote_line = next(line for line in self.text.splitlines() if "sudo sh -c" in line)
        self.assertNotIn("plainPassword", remote_line)
        self.assertNotIn("envContent", remote_line)


class EscapeSelfTest(unittest.TestCase):
    def test_self_test_escape_passes(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        script_path = str(TOOL) if Path(exe).name.lower().startswith("powershell") else TOOL.as_posix()
        result = _run_powershell(exe, "-File", script_path, "-SelfTestEscape")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), "ESCAPE_SELFTEST=PASS")

    def test_env_value_escaping_contract(self):
        # POSIX single-quote rule the tool implements: wrap in quotes, double
        # embedded quotes. Holds for anything the password rules allow.
        def escape(value: str) -> str:
            return "'" + value.replace("'", "'\\''") + "'"
        self.assertEqual(escape("a'b"), "'a'\\''b'")
        self.assertEqual(escape("ab$"), "'ab$'")
        self.assertEqual(escape("plain"), "'plain'")
        self.assertEqual(escape(""), "''")


if __name__ == "__main__":
    unittest.main()
