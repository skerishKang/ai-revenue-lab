"""provision_qa_pc_token.ps1 contracts: PC label pick, exact match, hygiene.

The daily real-usage check reads the token this script mints. The PC is chosen
here, once, by the link label; the daily run only uses the token. These tests
pin the default to the COM2 display name and keep the choice exact so a missing
or differently named PC fails with the active labels instead of silently
reading another PC. No network, no credential.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "scripts" / "provision_qa_pc_token.ps1"
DEFAULT_LABEL = "K_lipvoice · 컴2"


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


class PcTokenProvisioningContract(unittest.TestCase):
    def setUp(self):
        self.text = TOOL.read_text(encoding="utf-8")

    def test_default_label_is_the_com2_display_name(self):
        self.assertIn(f'[string]$PcDeviceLabel = "{DEFAULT_LABEL}"', self.text)
        self.assertNotIn("CGI-1", self.text)

    def test_the_label_match_is_exact_not_partial(self):
        self.assertIn("$_.label -eq $Label", self.text)
        self.assertNotIn("$_.label -like", self.text)
        self.assertNotIn("$_.label -match", self.text)

    def test_a_missing_label_lists_the_active_labels(self):
        self.assertIn("active labels:", self.text)
        self.assertIn("no active paired PC labelled", self.text)

    def test_no_token_or_node_id_reaches_output(self):
        for number, line in enumerate(self.text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("Write-", "Out-Line ")):
                self.assertNotIn("$issuedBody.token", stripped, f"line {number}")
                self.assertNotIn("$link.mesh_node_id", stripped, f"line {number}")
                self.assertNotIn("$email", stripped, f"line {number}")

    def test_self_test_passes(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        result = _run_powershell(exe, "-File", str(TOOL), "-SelfTest")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SELF_TEST=PASS", result.stdout)

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


if __name__ == "__main__":
    unittest.main()