"""release_chat.ps1 contracts: parse, plan shape, and secret hygiene.

The release script is the one command that ships chat.padiem.net (COM2 +
front Worker + pages mirror). CI verifies the file parses as PowerShell
where a runtime exists, and statically pins the review invariants: .NET
SHA256 (Get-FileHash is banned), the dry-run switch, the six-step plan
order, and that credential values are never echoed.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "release_chat.ps1"
REPO = HERE.resolve().parents[2]


def _powershell_exe():
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


class ReleaseScriptStaticContract(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_uses_dotnet_sha256_and_never_get_filehash(self):
        self.assertIn("[System.Security.Cryptography.SHA256]", self.text)
        self.assertNotIn("Get-FileHash", self.text)

    def test_dry_run_switch_exists(self):
        self.assertRegex(self.text, r"\[switch\]\$DryRun")

    def test_six_steps_in_order(self):
        last = -1
        for marker in ("1/6", "2/6", "3/6", "4/6", "5/6", "6/6"):
            idx = self.text.find(f"Write-Step \"{marker} ")
            self.assertGreaterEqual(idx, 0, marker)
            self.assertGreater(idx, last, marker)
            last = idx

    def test_never_echoes_the_cloudflare_token(self):
        for line in self.text.splitlines():
            self.assertIsNone(
                re.search(r"(Write-Host|Write-Output|Write-Info|Write-Step|Write-Verbose|echo)\b.*CLOUDFLARE_API_TOKEN", line),
                line,
            )
        # The token is only ever read from the environment into a header.
        self.assertIn("Bearer $env:CLOUDFLARE_API_TOKEN", self.text)

    def test_com2_lane_uses_keyed_batch_mode_ssh_and_the_ops_checkout(self):
        self.assertIn("-o BatchMode=yes", self.text)
        self.assertIn("user@192.168.0.101", self.text)
        self.assertIn("--ops-checkout", self.text)
        self.assertIn("COM2_DEPLOY_SUMMARY", self.text)

    def test_docs_point_screen_deploys_at_the_release_script(self):
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("release_chat.ps1", agents)
        doc = (REPO / "docs" / "operations" / "CHAT_PADIEM_NET_REQUEST_TOPOLOGY_20261108.md").read_text(encoding="utf-8")
        self.assertIn("release_chat.ps1", doc)

    def test_gate_and_packaging_workflows_match_the_topology(self):
        gate = (REPO / ".github" / "workflows" / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
        self.assertIn('--arg service "padiem-chat-front"', gate)
        self.assertIn("release_chat.ps1", gate)
        packaging = (REPO / ".github" / "workflows" / "validate-chat-com2-packaging.yml").read_text(encoding="utf-8")
        self.assertIn("deploy/chat-release/tests", packaging)



    def test_dry_run_completes_with_the_plan_contract(self):
        """The CTO's first touch is -DryRun: it must run to completion on a
        plain checkout (no Cloudflare auth, no COM2 access) and print the
        six-step plan plus the nothing-deployed line."""
        exe = _powershell_exe()
        script_path = str(SCRIPT) if Path(exe).name.lower().startswith("powershell") else SCRIPT.as_posix()
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", script_path, "-DryRun"],
            capture_output=True, text=True, timeout=1200, cwd=str(REPO),
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined[-2000:])
        for marker in ("STEP 1/6", "STEP 2/6", "STEP 3/6", "STEP 4/6", "STEP 5/6", "STEP 6/6",
                       "COM2_DEPLOY_SUMMARY", "sha256", "workers/domains chat.padiem.net",
                       "DRYRUN: nothing was deployed."):
            self.assertIn(marker, combined)
        # No credential material in the plan output.
        self.assertNotIn("CLOUDFLARE_API_TOKEN=", combined)


@unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
class ReleaseScriptParses(unittest.TestCase):
    def test_parses_without_errors(self):
        exe = _powershell_exe()
        if Path(exe).name.lower().startswith("powershell"):
            script_path = str(SCRIPT)
        else:
            script_path = SCRIPT.as_posix()
        parse_cmd = (
            "$t=$null;$e=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$t, [ref]$e);"
            "if ($e.Count -gt 0) { $e | ForEach-Object { Write-Output $_.Message }; exit 1 }"
            "else { Write-Output 'PARSE_OK' }"
        )
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", parse_cmd],
            capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PARSE_OK", result.stdout)


if __name__ == "__main__":
    unittest.main()

    def test_portable_paths_for_the_linux_ci_runtime(self):
        """The packaging job runs the dry-run under pwsh on ubuntu: backslash
        path separators inside Join-Path leaves and node args break there."""
        self.assertIn("test/worker.test.mjs", self.text)
        self.assertNotIn("apps\padiem-chat", self.text)
        self.assertNotIn("test\worker.test.mjs", self.text)
