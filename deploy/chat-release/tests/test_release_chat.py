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
import functools
import re
import shutil
import subprocess
import sys
import tempfile
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


@functools.lru_cache(maxsize=1)
def _windows_powershell_exe():
    """The Windows-only PowerShell 5.1 binary, or None when absent (Linux CI)."""
    exe = shutil.which("powershell")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.Major"],
            capture_output=True, text=True, timeout=60,
        )
    except Exception:
        return None
    if out.returncode == 0 and out.stdout.strip().startswith("5"):
        return exe
    return None


@functools.lru_cache(maxsize=None)
def _extract_function_text(fn_name):
    """Pull one function definition out of release_chat.ps1 with the PowerShell
    AST so the runtime probes exercise the REAL script text, never a copy."""
    exe = _powershell_exe()
    if exe is None:
        raise AssertionError("no PowerShell runtime on this runner")
    path_for_probe = _script_arg(exe).replace("'", "''")
    probe = (
        "$t=$null;$e=$null;"
        f"$ast=[System.Management.Automation.Language.Parser]::ParseFile('{path_for_probe}',[ref]$t,[ref]$e);"
        f"$fn=$ast.Find({{param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $a.Name -eq '{fn_name}'}},$true);"
        "if ($fn) { $fn.Extent.Text } else { exit 3 }"
    )
    result = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", probe],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise AssertionError(f"could not extract {fn_name}: {result.stdout}{result.stderr}")
    return result.stdout.strip()


def _run_runner_probe(exe, fn_text, *, os_value=None, strip_path=False):
    """Dot-source the extracted Resolve-NpxRunner in a fresh host process and
    return its single verdict line. os_value=None strips $env:OS entirely (the
    2026-11-15 release_188 condition); strip_path breaks PATH so Get-Command
    cannot resolve any npx shim."""
    fn_file = Path(tempfile.gettempdir()) / f"resolve_npx_runner_probe_{uuid.uuid4().hex[:8]}.ps1"
    fn_file.write_text(fn_text, encoding="ascii")
    try:
        lines = [f". '{fn_file.as_posix()}' ;", "Remove-Item Env:OS -ErrorAction SilentlyContinue ;"]
        if os_value is not None:
            lines.append(f"$env:OS = '{os_value}' ;")
        if strip_path:
            lines.append("$env:PATH = 'Z:\\__no_such_path_for_the_probe__' ;")
        lines.append(
            "try { $r = Resolve-NpxRunner ; Write-Output ('OK=' + $r) } "
            "catch { Write-Output ('THROW=' + $_.Exception.Message) }"
        )
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", " ".join(lines)],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        fn_file.unlink(missing_ok=True)
    for line in result.stdout.splitlines():
        if line.startswith("OK=") or line.startswith("THROW="):
            return line
    raise AssertionError(f"probe produced no verdict (exit {result.returncode}): {result.stdout}{result.stderr}")


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

    def test_step5_pair_iteration_keeps_the_full_url(self):
        """PowerShell flattens a single-element @() pair literal: the verify
        would iterate STRINGS and $pair[1] becomes the second CHARACTER ("h"),
        which the 4th deploy requested as a bogus host (STEP5_FAIL: remote
        name could not be resolved: 'h'). The comma-preserved single-element
        form and the multi-element form must both keep $pair[1] = full URL."""
        exe = _powershell_exe()
        snippet = (
            "$frontStatusPairs = @("
            "@('chat.padiem.net /health', 'https://chat.padiem.net/health'),"
            "@('chat.padiem.net /privacy', 'https://chat.padiem.net/privacy'));"
            "$frontAssetHosts = @(,@('chat.padiem.net', 'https://chat.padiem.net'));"
            "$urls = @();"
            "foreach ($pair in $frontStatusPairs) { $urls += $pair[1] }"
            "foreach ($pair in $frontAssetHosts) { $urls += ($pair[1] + '/chat-transport.js') }"
            "($urls -join '|')"
        )
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", snippet],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        urls = result.stdout.strip().split("|")
        self.assertEqual(urls, [
            "https://chat.padiem.net/health",
            "https://chat.padiem.net/privacy",
            "https://chat.padiem.net/chat-transport.js",
        ])

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

    def test_pages_assets_use_the_stamped_copy(self):
        """STEP 5 compares pages' /index.html with the stamped bytes.

        The pages static layer serves build.mjs's dist/index.html, not the
        repository's unversioned index.html. Comparing against $shaStaticDir
        would fail every release once "/" is excluded from the proxy.
        """
        pages = self.text.split("# PAGES mirror checks", 1)[1]
        self.assertIn("Join-Path $stampStaticDir $asset", pages)
        self.assertNotIn("Join-Path $shaStaticDir $asset", pages)


    def test_npx_is_pinned_to_the_cmd_application_full_path(self):
        """npm's npx.ps1 runs Set-StrictMode and re-parses $MyInvocation.Line,
        re-evaluating the ORIGINAL command text in its own scope: a call
        argument carrying a $Script:-qualified variable dies there with
        "cannot be retrieved" (2026-11-10: the release lost its pages step and
        then its rollback to exactly that; a bare "npx" on PATH prefers
        npx.ps1 in pwsh, and the exec launcher env carried no $env:OS). The
        script must pin the npx.cmd APPLICATION by full path on Windows."""
        self.assertIn("Get-Command npx.cmd -CommandType Application", self.text)
        self.assertNotIn(
            '$Script:Npx = if ($env:OS -eq "Windows_NT") { "npx.cmd" } else { "npx" }',
            self.text)
        self.assertNotIn("wrangler rollback $Script:PrevFrontVersion", self.text)
        # The rollback call moved into Invoke-FrontRollbackCommand, where the
        # version arrives as a plain parameter; its non-interactive flags and
        # bounded wait are pinned in test_release_chat_rollback.py.
        # The command is built as a format string: runner, version, log path.
        self.assertIn("wrangler rollback {1} --message release-step-failure --yes", self.text)

    def test_rollback_resolves_a_missing_recorded_version(self):
        """The rollback point can be unset when the failure lands before step 3
        stored it. The helper must re-read the deployments list once, travel
        the version in a LOCAL variable, and skip with an explicit summary
        line when nothing resolves — never crash the reporting path."""
        fn = self.text.split("function Invoke-FrontRollbackIfNeeded", 1)[1]
        fn = fn.split("\nfunction ", 1)[0]
        self.assertIn("if (-not $Script:FrontDeployed) { return }", fn)
        self.assertIn("$rollbackVersion = $Script:PrevFrontVersion", fn)
        self.assertIn("Get-FrontVersionIds", fn)
        self.assertIn("FRONT_ROLLBACK_SKIPPED", fn)

    def test_a_failed_rollback_keeps_the_step_failure_in_the_log(self):
        """2026-11-10: the rollback crash replaced the STEP4 pages failure, so
        the release ended without any failure reason. The step-4/5 catch must
        store the original error, record a rollback failure without raising
        it, and re-throw the ORIGINAL failure."""
        self.assertIn("$releaseFailure = $_", self.text)
        self.assertIn("try { Invoke-FrontRollbackIfNeeded }", self.text)
        self.assertIn("FRONT_ROLLBACK_FAILED", self.text)
        self.assertIn("throw $releaseFailure", self.text)
        self.assertNotIn("catch {\n    Invoke-FrontRollbackIfNeeded\n    throw\n}", self.text)
    def test_pinned_sha_is_guarded_against_stale_origin_main(self):
        """2026-11-09: three releases aborted at STEP2 with SHA_NOT_ORIGIN_MAIN
        because COM1's origin/main was stale while COM2 had already fetched a
        newer one. The release must (a) refresh COM1's own refs before
        pinning, and (b) compare the pinned SHA against COM2-side fetched
        origin/main before launching any deploy unit."""
        # Local fetch happens before the pin is resolved (order matters).
        fetch_at = self.text.find("git -C $RepoRoot fetch -q origin")
        pin_at = self.text.find("$mainCommit = Resolve-CommitRef")
        self.assertGreaterEqual(fetch_at, 0)
        self.assertGreaterEqual(pin_at, 0)
        self.assertLess(fetch_at, pin_at)
        # COM2-side comparison runs before any systemd unit is created.
        compare_at = self.text.find("COM2 origin/main")
        unit_at = self.text.find('Invoke-Com2 "bash $remoteShPath"')
        self.assertGreaterEqual(compare_at, 0)
        self.assertGreaterEqual(unit_at, 0)
        self.assertLess(compare_at, unit_at)
        self.assertIn("rev-parse origin/main", self.text)
        self.assertIn("COM2 origin/main ($com2Main) != pinned release SHA", self.text)
        self.assertIn("Rerun release_chat.ps1 to re-fetch and re-pin", self.text)
        # A failed fetch must not silently pin stale refs on a real run.
        self.assertIn("refusing to pin from stale refs", self.text)

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
        # The dry-run expands the STEP 5 URL list: a flattened pair list would
        # print a character ("h") instead of the host — assert the full URLs
        # (the 4th deploy's STEP5_FAIL came from exactly that flattening).
        for url in ("GET https://chat.padiem.net/health",
                    "GET https://chat.padiem.net/privacy",
                    "GET https://chat.padiem.net/chat-transport.js",
                    "GET https://chat.padiem.net/index.html",
                    "GET https://padiem-chat.pages.dev/privacy",
                    "GET https://padiem-chat.pages.dev/chat-transport.js",
                    "GET https://padiem-chat.pages.dev/index.html"):
            self.assertIn(url, combined)
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


class ReleaseScriptOsDetection(unittest.TestCase):
    """2026-11-15 (release_188): the npx runner probe trusted the OS
    environment variable and the pwsh-only IsWindows flag. The environment
    that ran the release strips standard variables (no $env:OS) and Windows
    PowerShell 5.1 has no $IsWindows, so the probe fell to bare "npx", which
    resolved to the re-parsing npx.ps1, and STEP 4 died on the
    $Script:-qualified pages project argument. The probe must read the host
    from the .NET runtime, verify the Windows runner is a real npx.cmd file,
    stop with one explicit line when it is not, and print the decision inside
    the audit transcript."""

    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_host_probe_reads_the_runtime_not_the_environment(self):
        self.assertIn("[System.Environment]::OSVersion.Platform", self.text)
        self.assertIn("[System.PlatformID]::Win32NT", self.text)
        self.assertNotIn('$env:OS -eq "Windows_NT"', self.text)
        self.assertNotIn("-or $IsWindows", self.text)
        self.assertIn("function Resolve-NpxRunner", self.text)

    def test_windows_branch_needs_a_real_file_or_stops_before_step1(self):
        fn = self.text.split("function Resolve-NpxRunner", 1)[1]
        fn = fn.split("\nfunction ", 1)[0]
        self.assertIn("Get-Command npx.cmd -CommandType Application", fn)
        self.assertIn("Test-Path -LiteralPath $npxCmd -PathType Leaf", fn)
        self.assertIn("RELEASE_OS_FAIL", fn)

    def test_the_runner_decision_lands_in_the_audit_transcript(self):
        decision = self.text.find("npx runner = ")
        transcript = self.text.find("Start-Transcript")
        step1 = self.text.find('Write-Step "1/6')
        self.assertGreaterEqual(decision, 0)
        self.assertGreater(decision, transcript)
        self.assertGreater(step1, 0)
        self.assertLess(decision, step1)
        self.assertIn("$Script:Npx = Resolve-NpxRunner", self.text)

    def test_pages_project_argument_travels_in_a_local_variable(self):
        self.assertIn(
            "& $Script:Npx wrangler pages deploy dist --project-name $pagesProject --branch main",
            self.text,
        )
        self.assertNotIn(
            "& $Script:Npx wrangler pages deploy dist --project-name $Script:PagesProject --branch main",
            self.text,
        )

    def test_wrangler_login_lookup_survives_a_stripped_userprofile(self):
        seg = self.text.split("function Use-WranglerLoginForReadOnlyApi", 1)[1]
        seg = seg.split("\nfunction ", 1)[0]
        self.assertIn("[System.Environment]::GetFolderPath", seg)
        self.assertNotIn("Join-Path $env:USERPROFILE", seg)
        self.assertIn("if (-not $profileDir) { return }", seg)

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_runner_resolves_with_os_stripped_in_the_default_host(self):
        # The exact release_188 condition: $env:OS absent. On Windows the
        # probe must still pin the full-path npx.cmd; on the Linux CI runner
        # plain npx stays correct.
        fn = _extract_function_text("Resolve-NpxRunner")
        verdict = _run_runner_probe(_powershell_exe(), fn, os_value=None)
        self.assertTrue(verdict.startswith("OK="), verdict)
        value = verdict[3:]
        if sys.platform == "win32":
            self.assertTrue(value.endswith("npx.cmd"), verdict)
            self.assertTrue(Path(value).exists(), verdict)
            self.assertNotIn("npx.ps1", value)
        else:
            self.assertEqual(value, "npx")

    @unittest.skipIf(_windows_powershell_exe() is None, "Windows PowerShell 5.1 not on this runner")
    def test_runner_resolves_with_os_stripped_on_windows_powershell_51(self):
        # release_188 died exactly here: no $env:OS, PowerShell 5.1 (no
        # $IsWindows). The probe must still pin the full-path npx.cmd.
        fn = _extract_function_text("Resolve-NpxRunner")
        verdict = _run_runner_probe(_windows_powershell_exe(), fn, os_value=None)
        self.assertTrue(verdict.startswith("OK="), verdict)
        value = verdict[3:]
        self.assertTrue(value.endswith("npx.cmd"), verdict)
        self.assertTrue(Path(value).exists(), verdict)

    @unittest.skipIf(_windows_powershell_exe() is None, "Windows PowerShell 5.1 not on this runner")
    def test_runner_resolves_with_os_set_on_windows_powershell_51(self):
        # The classic environment keeps working too.
        fn = _extract_function_text("Resolve-NpxRunner")
        verdict = _run_runner_probe(_windows_powershell_exe(), fn, os_value="Windows_NT")
        self.assertTrue(verdict.startswith("OK="), verdict)
        self.assertTrue(verdict[3:].endswith("npx.cmd"), verdict)

    @unittest.skipIf(_windows_powershell_exe() is None, "Windows PowerShell 5.1 not on this runner")
    def test_runner_stops_with_one_line_when_npx_cmd_is_missing(self):
        # Fail-fast: with no npx.cmd resolvable the probe must stop with the
        # explicit RELEASE_OS_FAIL line, never fall back to a re-parsing shim.
        fn = _extract_function_text("Resolve-NpxRunner")
        verdict = _run_runner_probe(_windows_powershell_exe(), fn, os_value="Windows_NT", strip_path=True)
        self.assertTrue(verdict.startswith("THROW="), verdict)
        self.assertIn("RELEASE_OS_FAIL", verdict)

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_runner_survives_a_broken_path_on_the_linux_runner(self):
        # On the Linux CI runner the Unix platform probe returns bare npx
        # without touching PATH at all — a broken PATH cannot break it.
        if sys.platform == "win32":
            self.skipTest("Linux-only expectation")
        fn = _extract_function_text("Resolve-NpxRunner")
        verdict = _run_runner_probe(_powershell_exe(), fn, os_value=None, strip_path=True)
        self.assertEqual(verdict, "OK=npx")


if __name__ == "__main__":
    unittest.main()
