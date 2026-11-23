"""STEP 5 pages-mirror verification contracts.

The mirror verification used to compare the production alias
(padiem-chat.pages.dev) with the stamped deploy copy immediately after
`wrangler pages deploy` returned. The alias answers from the OUTGOING
deployment for a short window after an upload (measured 15-80 s on the
platform), so a correct release intermittently ended with
`PAGES_VERIFY_FAIL: index.html sha256 mismatch` while the front Worker
already served the new bytes.

These contracts pin the two-part fix:

- STEP 4 captures the immutable per-deployment host from wrangler's output;
  STEP 5 compares THAT first, so the uploaded bytes are confirmed without
  waiting on the alias switch, and falls back to the alias alone when the
  output carries no deployment host.
- the alias is re-checked a few times (5 s apart) ONLY while an older ?v=
  stamp still answers. A same-version byte difference, a missing stamp or a
  fetch error fails at once and is never retried away; exhausting the retries
  is still PAGES_VERIFY_FAIL with the front untouched.
"""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "release_chat.ps1"
REPO = HERE.resolve().parents[2]
STAMPER = HERE.parent / "stamp_index_html.mjs"
PAGES_BUILD = REPO / "apps" / "padiem-chat-pages" / "build.mjs"

VERSION = "ab12cd34"
PINNED = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _powershell_exe():
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def _node():
    exe = shutil.which("node")
    if exe is None:
        raise unittest.SkipTest("no node runtime on this runner")
    return exe


def _extract_functions(*names):
    """Lift the shipped helpers out of release_chat.ps1 with the PowerShell AST
    so the probes exercise the real text, never a copy."""
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
    """Run an ASCII-only probe script and return its stdout lines."""
    probe_file = Path(tempfile.mkdtemp(prefix="pages-verify-")) / "probe.ps1"
    try:
        probe_file.write_text(body, encoding="ascii")
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(probe_file)],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        shutil.rmtree(probe_file.parent, ignore_errors=True)
    if result.returncode != 0:
        raise AssertionError(f"probe failed (exit {result.returncode}): {result.stdout}{result.stderr}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


class TwoBuildPathsAgree(unittest.TestCase):
    """The Worker ships a stamped copy of the pinned static tree; the pages
    build stamps dist/ from the same tree and version. STEP 5 compares BOTH
    surfaces with the Worker copy, so the two build paths must produce the
    same bytes — otherwise every release would fail on a basis mismatch."""

    def test_pages_dist_index_matches_the_stamped_worker_copy(self):
        node = _node()
        tmp = Path(tempfile.mkdtemp(prefix="pages-dist-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        stamped = tmp / "stamped-static"
        shutil.copytree(REPO / "apps" / "padiem-chat" / "static", stamped)
        stamp = subprocess.run(
            [node, str(STAMPER), str(stamped), VERSION],
            capture_output=True, text=True, timeout=300,
        )
        self.assertEqual(stamp.returncode, 0, stamp.stdout + stamp.stderr)

        out = tmp / "dist"
        driver = tmp / "build-driver.mjs"
        driver.write_text(
            "import { pathToFileURL } from \"node:url\";\n"
            "const [buildPath, outDir] = process.argv.slice(2);\n"
            "const mod = await import(pathToFileURL(buildPath).href);\n"
            "await mod.buildDist({ outDir });\n",
            encoding="utf-8",
        )
        run_env = dict(os.environ)
        run_env["PADIEM_ASSET_VERSION"] = VERSION
        build = subprocess.run(
            [node, str(driver), str(PAGES_BUILD), str(out)],
            capture_output=True, text=True, timeout=600, env=run_env, cwd=str(tmp),
        )
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        self.assertTrue((out / "_routes.json").exists(), "build.mjs did not assemble dist")

        worker_bytes = (stamped / "index.html").read_bytes()
        pages_bytes = (out / "index.html").read_bytes()
        self.assertIn(f"?v={VERSION}".encode(), pages_bytes)
        self.assertEqual(
            pages_bytes, worker_bytes,
            "dist/index.html and the stamped Worker copy must be byte-identical; "
            "STEP 5 compares both surfaces with the Worker copy",
        )


class AliasRetryDecision(unittest.TestCase):
    """The retry window is the deployment switch and nothing else."""

    def _run_cases(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        functions = _extract_functions(
            "Test-PagesAliasRetryNeeded", "Invoke-PagesAliasVerify")

        def case(name, probe_setup, probe_body, pinned=PINNED, version=VERSION):
            return (
                f"{probe_setup}\n"
                "$probe = { " + probe_body + " }\n"
                f"$r = Invoke-PagesAliasVerify -Pinned '{pinned}' -Version '{version}' -Probe $probe\n"
                "Write-Output (\"CASE=" + name +
                ";Matched={0};Attempts={1};Failure={2}\" -f $r.Matched, $r.Attempts, $r.Failure)\n"
            )

        sequence = (
            "$script:seq = @("
            f"[pscustomobject]@{{Fetched=$true;Hash='old';Stamp='aaaaaaaa'}},"
            f"[pscustomobject]@{{Fetched=$true;Hash='{PINNED}';Stamp='{VERSION}'}}"
            ");\n$script:idx = 0\n"
        )
        body = "\n".join([
            functions,
            "$Script:PagesAliasAttempts = 6\n",
            "$Script:PagesAliasRetrySeconds = 0\n",
            case("stale_then_fresh", sequence,
                 "$p = $script:seq[$script:idx]; $script:idx = $script:idx + 1; $p"),
            case("same_version_other_bytes", "",
                 f"[pscustomobject]@{{Fetched=$true;Hash='other';Stamp='{VERSION}'}}"),
            case("no_stamp", "",
                 "[pscustomobject]@{Fetched=$true;Hash='other';Stamp=''}"),
            case("fetch_error", "",
                 "[pscustomobject]@{Fetched=$false;Hash='';Stamp=''}"),
            case("permanent_stale", "",
                 "[pscustomobject]@{Fetched=$true;Hash='old';Stamp='aaaaaaaa'}"),
        ])
        lines = _run_ps(exe, body)
        cases = {}
        for line in lines:
            if not line.startswith("CASE="):
                continue
            fields = dict(part.split("=", 1) for part in line.split(";"))
            cases[fields["CASE"]] = fields
        return cases

    def test_only_an_older_stamp_is_retried(self):
        cases = self._run_cases()
        self.assertEqual(cases["stale_then_fresh"]["Matched"], "True")
        self.assertEqual(cases["stale_then_fresh"]["Attempts"], "2",
                         "the outgoing deployment must be re-checked once more")

    def test_a_real_mismatch_fails_on_the_first_attempt(self):
        cases = self._run_cases()
        # Same release stamp but different bytes: the upload is wrong, not late.
        self.assertEqual(cases["same_version_other_bytes"]["Matched"], "False")
        self.assertEqual(cases["same_version_other_bytes"]["Attempts"], "1")
        self.assertEqual(cases["same_version_other_bytes"]["Failure"], "mismatch")
        # No stamp at all: nothing proves the alias is mid-switch.
        self.assertEqual(cases["no_stamp"]["Attempts"], "1")
        self.assertEqual(cases["no_stamp"]["Failure"], "mismatch")
        # A fetch error stays a mirror failure, never a retry loop and never a
        # front rollback.
        self.assertEqual(cases["fetch_error"]["Attempts"], "1")
        self.assertEqual(cases["fetch_error"]["Failure"], "fetch_error")

    def test_exhaustion_keeps_the_pages_failure_and_the_front(self):
        cases = self._run_cases()
        self.assertEqual(cases["permanent_stale"]["Matched"], "False")
        self.assertEqual(cases["permanent_stale"]["Attempts"], "6")
        self.assertEqual(cases["permanent_stale"]["Failure"], "retry_exhausted")

        text = SCRIPT.read_text(encoding="utf-8")
        # The retry budget is bounded and explicit.
        self.assertIn("$Script:PagesAliasAttempts = 6", text)
        self.assertIn("$Script:PagesAliasRetrySeconds = 5", text)
        # Exhaustion records PAGES_VERIFY_FAIL (still exit 1) ...
        self.assertIn('$Script:PagesVerifyFailed.Add("$asset sha256 mismatch ($($alias.Failure) after $($alias.Attempts) attempt(s))")', text)
        self.assertIn("if ($Script:PagesVerifyFailed.Count -gt 0) { exit 1 }", text)
        # ... and the pages path never gains a rollback call: the front keeps
        # serving (definition + the two front-failure catch sites only).
        self.assertEqual(text.count("Invoke-FrontRollbackIfNeeded"), 3)


class DeploymentSnapshotIsCheckedFirst(unittest.TestCase):
    """STEP 4 captures the immutable deployment host; STEP 5 compares it
    before the alias, and degrades to the alias alone when absent."""

    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_step4_captures_the_deployment_host_from_the_wrangler_output(self):
        self.assertIn("Get-PagesDeploymentUrl $pagesDeployOutput $pagesProject", self.text)
        self.assertIn("PAGES_DEPLOYMENT_UNPARSED", self.text)
        self.assertIn('Add-Summary "PAGES_DEPLOYMENT=$($Script:PagesDeploymentUrl)"', self.text)
        # The deploy call still travels in a local variable (npx.ps1 re-parse).
        self.assertIn("& $Script:Npx wrangler pages deploy dist --project-name $pagesProject --branch main", self.text)

    def test_the_output_capture_does_not_trip_ps51_native_stderr(self):
        """PS 5.1 turns a redirected native stderr into an ErrorRecord, and the
        release runs with $ErrorActionPreference=Stop, so `2>&1`/`*>` around
        wrangler (which writes progress to stderr) fails the step. The capture
        must scope Continue to the call and restore it."""
        segment = self.text.split("$pagesProject = $Script:PagesProject", 1)[1]
        segment = segment.split("pages deployment snapshot", 1)[0]
        self.assertIn('$ErrorActionPreference = "Continue"', segment)
        self.assertIn("finally { $ErrorActionPreference = $releaseEap }", segment)
        self.assertNotIn("*> $pagesOutFile", segment)
        self.assertIn("2>&1 | Out-String", segment)

    def test_step5_compares_the_snapshot_against_the_stamped_copy(self):
        pages = self.text.split("# PAGES mirror checks", 1)[1]
        snapshot_at = pages.find("$Script:PagesDeploymentUrl")
        alias_at = pages.find("Invoke-PagesAliasVerify")
        self.assertGreaterEqual(snapshot_at, 0)
        self.assertGreater(alias_at, snapshot_at, "the snapshot check runs before the alias")
        self.assertIn('Join-Path $stampStaticDir "index.html"', pages)
        self.assertIn("deployment snapshot index.html sha256 mismatch", pages)

    def test_the_deployment_url_parser_reads_only_the_hash_snapshot(self):
        exe = _powershell_exe()
        if exe is None:
            self.skipTest("no PowerShell runtime on this runner")
        functions = _extract_functions("Get-PagesDeploymentUrl")
        body = "\n".join([
            functions,
            "Write-Output ('HASH=' + (Get-PagesDeploymentUrl "
            "'Deployment complete! https://abc12345.padiem-chat.pages.dev  (alias https://main.padiem-chat.pages.dev)' "
            "'padiem-chat'))\n",
            # A branch alias is not an immutable snapshot.
            "Write-Output ('ALIAS=' + (Get-PagesDeploymentUrl "
            "'https://main.padiem-chat.pages.dev' 'padiem-chat'))\n",
            "Write-Output ('NONE=' + (Get-PagesDeploymentUrl 'no url here' 'padiem-chat'))\n",
            "Write-Output ('EMPTY=' + (Get-PagesDeploymentUrl '' 'padiem-chat'))\n",
        ])
        values = dict(
            line.split("=", 1) for line in _run_ps(exe, body) if "=" in line
        )
        self.assertEqual(values.get("HASH"), "https://abc12345.padiem-chat.pages.dev")
        self.assertEqual(values.get("ALIAS", ""), "")
        self.assertEqual(values.get("NONE", ""), "")
        self.assertEqual(values.get("EMPTY", ""), "")


if __name__ == "__main__":
    unittest.main()
