"""release_chat.ps1 contracts: parse, plan shape, and secret hygiene.

The release script is the one command that ships chat.padiem.net (COM2 +
front Worker + pages mirror). CI verifies the file parses as PowerShell
where a runtime exists, and statically pins the review invariants: .NET
SHA256 (Get-FileHash is banned), the dry-run switch, the six-step plan
order, and that credential values are never echoed. The dry-run itself must
complete on a plain checkout AND on a work folder that sits on another
branch without apps/padiem-chat-front or apps/padiem-chat-pages — the
release always ships the pinned SHA out of git objects, never the work
folder.
"""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import uuid

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "release_chat.ps1"
REPO = HERE.resolve().parents[2]


def _powershell_exe():
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _script_arg(exe):
    return str(SCRIPT) if Path(exe).name.lower().startswith("powershell") else SCRIPT.as_posix()


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

    def test_com2_lane_matches_the_dep17_shape(self):
        # The launcher is generated as a literal sh and uploaded base64-encoded
        # (PS 5.1 -> ssh -> cmd -> wsl cannot carry the nested quoting), and it
        # runs the dep17.sh shape against the OPS checkout — never a /mnt/d
        # work-folder path.
        # Uploaded with scp and run as "bash <file>" (the dep17.sh path): a
        # pipe or ">" inside the ssh command is parsed by cmd.exe on COM2.
        self.assertIn("& scp -i $Script:Com2SshKey -o BatchMode=yes", self.text)
        self.assertIn('Invoke-Com2 "bash $remoteShPath"', self.text)
        self.assertIn('$remoteSh = $remoteSh -replace "`r`n", "`n"', self.text)
        self.assertNotIn("base64 -d", self.text)
        self.assertIn("WorkingDirectory=$OPS", self.text)
        self.assertIn("$OPS/deploy/host-com2/deploy_from_main.sh", self.text)
        self.assertIn("git -C \"$OPS\" fetch -q origin", self.text)
        self.assertIn('git -C "$OPS" cat-file -e "$SHA^{commit}"', self.text)
        self.assertNotIn("/mnt/d/work/ai-revenue-lab-ops", self.text)
        self.assertIn("-o BatchMode=yes", self.text)
        self.assertIn("user@192.168.0.101", self.text)
        self.assertIn("COM2_DEPLOY_SUMMARY", self.text)

    def test_front_and_pages_run_from_the_extracted_sha_folders(self):
        # The COM1 work folder may sit on another branch without these apps:
        # every front/pages command must target the SHA extraction, and the
        # front's [assets] relative walk must be verified inside it.
        self.assertIn("Push-Location $shaFrontDir", self.text)
        self.assertIn("Push-Location $shaPagesDir", self.text)
        self.assertIn('Join-Path $shaFrontDir "../padiem-chat/static/index.html"', self.text)
        self.assertNotIn("Push-Location $frontDir", self.text)
        self.assertNotIn("Push-Location $pagesDir", self.text)
        self.assertIn("apps/padiem-chat-pages", self.text.split("archive --format=zip", 1)[1].split("\n", 1)[0])
        # The front carries no package.json: nothing is installed, the tests
        # run on node builtins and wrangler comes from the npx cache.
        self.assertFalse((REPO / "apps" / "padiem-chat-front" / "package.json").exists())
        self.assertFalse((REPO / "apps" / "padiem-chat-pages" / "package.json").exists())
        self.assertNotIn("npm ci", self.text)

    def test_portable_paths_for_the_linux_ci_runtime(self):
        """The packaging job runs the dry-run under pwsh on ubuntu: backslash
        path separators inside Join-Path leaves and node args break there."""
        self.assertIn("test/worker.test.mjs", self.text)
        self.assertNotIn("apps\\padiem-chat", self.text)
        self.assertNotIn("test\\worker.test.mjs", self.text)

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

    def test_pages_mirror_failure_never_rolls_the_front_back(self):
        """A pages-mirror-only verification failure is recorded as
        PAGES_VERIFY_FAIL and fails the release with exit 1 — the front stays
        serving (the 2026-11-08 incident rolled a healthy front back over a
        pages /privacy 404)."""
        self.assertIn("$Script:PagesVerifyFailed", self.text)
        self.assertIn("PAGES_VERIFY_FAIL", self.text)
        self.assertIn("exit 1", self.text)
        # The rollback helper fires from its definition and the two
        # front-failure catch sites only — never from the pages-fail path.
        self.assertEqual(self.text.count("Invoke-FrontRollbackIfNeeded"), 3)

    def test_dry_run_completes_with_the_plan_contract(self):
        """The CTO's first touch is -DryRun: it must run to completion on a
        plain checkout (no Cloudflare auth, no COM2 access) and print the
        six-step plan plus the nothing-deployed line."""
        exe = _powershell_exe()
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", _script_arg(exe), "-DryRun"],
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
class ReleaseScriptRealConditions(unittest.TestCase):
    def tearDown(self):
        wt = getattr(self, "_worktree", None)
        if wt:
            subprocess.run(
                ["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)],
                capture_output=True, text=True, timeout=120,
            )

    def test_dry_run_survives_a_work_folder_without_front_and_pages(self):
        """The 2026-11-08 real-run failure: the COM1 work folder sat on another
        branch without apps/padiem-chat-front, and the script died on
        PathNotFound in the work folder. The dry-run must complete from such a
        work folder because it ships the pinned SHA out of git objects."""
        exe = _powershell_exe()
        self._worktree = REPO.parent / ("chat-release-wt-" + uuid.uuid4().hex[:8])
        subprocess.run(
            ["git", "-C", str(REPO), "worktree", "add", "--detach", str(self._worktree), "HEAD"],
            capture_output=True, text=True, timeout=300, check=True,
        )
        # The other-branch condition: the two released apps are absent.
        shutil.rmtree(self._worktree / "apps" / "padiem-chat-front")
        shutil.rmtree(self._worktree / "apps" / "padiem-chat-pages")
        script_path = str(self._worktree / "deploy" / "chat-release" / "release_chat.ps1") \
            if Path(exe).name.lower().startswith("powershell") \
            else (self._worktree / "deploy" / "chat-release" / "release_chat.ps1").as_posix()
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", script_path, "-DryRun"],
            capture_output=True, text=True, timeout=1200, cwd=str(self._worktree),
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, combined[-2000:])
        for marker in ("STEP 1/6", "STEP 2/6", "STEP 3/6", "STEP 4/6", "STEP 5/6", "STEP 6/6",
                       "DRYRUN: nothing was deployed."):
            self.assertIn(marker, combined)


@unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
class ReleaseScriptParses(unittest.TestCase):
    def test_parses_without_errors(self):
        exe = _powershell_exe()
        parse_cmd = (
            "$t=$null;$e=$null;"
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{_script_arg(exe)}', [ref]$t, [ref]$e);"
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
