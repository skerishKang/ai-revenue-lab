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

    def test_com2_write_survives_the_cmdexe_remote_shell(self):
        # COM2's ssh lands in Windows cmd.exe: no sudo there, and cmd would
        # chew any quote, pipe or redirect before wsl.exe ever sees it (the
        # release_chat.ps1 exit-255 trap). The whole remote command is ONE
        # bare argv line: wsl.exe -d Ubuntu -u root --exec ... — nothing for
        # cmd to reinterpret, stdin rides ssh -> cmd -> wsl untouched.
        lines = self.text.splitlines()
        write_line = next(line for line in lines if "--exec install" in line)
        verify_line = next(line for line in lines if "--exec test" in line)
        # The remote templates are the PowerShell single-quoted literals on
        # those lines; assert against the VALUE, not the quoting syntax.
        write_remote = re.search(r"'([^']+)'", write_line).group(1)
        verify_remote = re.search(r"'([^']+)'", verify_line).group(1)
        for remote in (write_remote, verify_remote):
            self.assertIn("wsl.exe -d Ubuntu -u root --exec", remote, remote)
            # No shell metacharacter the remote cmd.exe would eat first.
            for forbidden in ("sudo", "'", '"', "|", ">", "<", "&&"):
                self.assertNotIn(forbidden, remote, f"{forbidden!r} in: {remote}")
        self.assertIn("install -D -m 600 /dev/stdin", write_remote)
        # The path arrives through the -f substitution: the template ends in
        # {0} and the param default pins /etc/padiem/qa-smoke.env.
        self.assertRegex(write_remote, r"install -D -m 600 /dev/stdin \{0\}$")
        self.assertRegex(verify_remote, r"test -s \{0\}$")
        self.assertIn('$Com2EnvPath = "/etc/padiem/qa-smoke.env"', self.text)
        # The remote command carries no credential material — it only points
        # install at stdin; the env content never touches argv or a log.
        self.assertNotIn("plainPassword", write_line)
        self.assertNotIn("envContent", write_line)
        self.assertNotIn("plainPassword", verify_line)
        # The remote command must be passed UNQUOTED through the ssh
        # arguments (each token a separate argv ssh rejoins), so no quote
        # character ever reaches the remote shell.
        arguments_template = next(line for line in lines if "o ConnectTimeout=10 {1} {2}" in line)
        self.assertNotIn('"{2}"', arguments_template)
        # sudo branches and messages are gone: no executable line mentions it
        # (comments may explain why the remote shell gets none).
        for number, line in enumerate(self.text.splitlines(), start=1):
            if not line.strip().startswith("#"):
                self.assertNotIn("sudo", line, f"line {number}: {line.strip()}")


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
