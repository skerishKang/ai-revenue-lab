"""#7350 contracts: the release script owns its audit log, and the Cloudflare
account is resolved before the front-version lookup.

(가) $env:CLOUDFLARE_ACCOUNT_ID is set at script start — before
Get-FrontVersionIds can run. A multi-account stored wrangler login makes a
bare deployments-list call fail there, and a release without a rollback
point must stop before deploying; a dry-run only warns.
(나) the audit-log number is picked by the script: the highest release_*.log
number (.failed.log included) + 1, existing files are never overwritten, and
an explicit -LogPath that already exists is refused.
(다) a release log written in the last 10 minutes stops a real run unless
-Force; a dry-run only warns (CI runs two dry-runs back to back).
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


def _extract_functions():
    """The three shipped log helpers, lifted verbatim out of the release
    script so the runtime tests exercise exactly what ships. The executable
    start block after them is excluded (it reads the caller's params), and
    the extraction starts at the first function — the marker's "(#7350)"
    tail would parse as an unclosed parenthesized comment."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = text.split("function Get-ReleaseLogMaxNumber", 1)[1]
    body = "function Get-ReleaseLogMaxNumber" + body.split("$Script:LogDir = ", 1)[0]
    return body


def _run_driver(code):
    """Compose a driver script: the shipped helpers + the test calls.
    Returns (returncode, combined_output)."""
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "driver.ps1"
        driver.write_text(_extract_functions() + "\n" + code, encoding="utf-8")
        exe = _powershell_exe()
        script_arg = str(driver) if Path(exe).name.lower().startswith("powershell") else driver.as_posix()
        result = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", script_arg],
            capture_output=True, text=True, timeout=120,
        )
        return result.returncode, result.stdout + result.stderr


class ReleaseAccountAndLogStaticContract(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_account_id_resolves_before_the_version_lookup(self):
        """(가) order: the start-of-script account-ID assignment must run
        before the first Get-FrontVersionIds call — a multi-account stored
        wrangler login fails a bare deployments-list call (release_32,
        2026-11-10). The definition position is irrelevant; the call site is
        what reads the account."""
        first = self.text.find("$env:CLOUDFLARE_ACCOUNT_ID = $Script:CloudflareAccountId")
        self.assertGreaterEqual(first, 0)
        call = self.text.find("$prevIds = @(Get-FrontVersionIds)")
        self.assertGreaterEqual(call, 0)
        self.assertLess(first, call)

    def test_unreadable_version_stops_before_deploy_dryrun_only_warns(self):
        """(가) a release without a rollback point refuses to deploy: the
        STEP3 stop sits before the wrangler deploy call, and the dry-run path
        only prints the unreadable-version warning."""
        stop_at = self.text.find("STEP3_FAIL: could not read the current front Version ID")
        deploy_at = self.text.find("& $Script:Npx wrangler deploy --keep-vars")
        self.assertGreaterEqual(stop_at, 0)
        self.assertGreaterEqual(deploy_at, 0)
        self.assertLess(stop_at, deploy_at)
        self.assertIn("current front Version ID unreadable on this machine", self.text)

    def test_log_parameters_exist(self):
        """(나)(다) the runner no longer picks the number nor needs a blind
        retry past a concurrent release: -LogPath and -Force exist."""
        self.assertRegex(self.text, r"\[string\]\$LogPath = \"\"")
        self.assertRegex(self.text, r"\[switch\]\$Force")

    def test_transcript_opens_and_closes(self):
        """(나) the script writes its own audit log (a transcript mirroring
        the release output) and closes it on the completion path; the auto
        path never targets an existing file, so the transcript never
        overwrites one."""
        self.assertIn("Start-Transcript -Path $Script:ReleaseLogPath", self.text)
        self.assertIn("Stop-Transcript", self.text)
        self.assertNotIn("-Append", self.text)

    def test_auto_mode_never_returns_an_existing_file(self):
        """(나) auto numbering skips taken numbers (the 2026-11-10 same-number
        overwrite): the while loop bumps until the candidate is free."""
        resolve = self.text.split("function Resolve-ReleaseLogPath", 1)[1]
        resolve = resolve.split("\nfunction ", 1)[0]
        self.assertIn("$n = (Get-ReleaseLogMaxNumber $Dir) + 1", resolve)
        self.assertIn("while (Test-Path -LiteralPath $candidate)", resolve)

    def test_log_dir_exists_on_windows_and_linux_runners(self):
        """(나) the audit-log directory resolves on a Windows host (USERPROFILE)
        and on the Linux CI dry-run runners (HOME) — the PR #7351 first run
        died on a null Join-Path argument before any step could run."""
        block = self.text.split("$Script:LogDir = $env:USERPROFILE", 1)[1]
        block = block.split("$recentLogs = Get-RecentReleaseLogs", 1)[0]
        self.assertIn("$Script:LogDir = $env:HOME", block)
        self.assertIn("RELEASE_LOG_FAIL: no user profile directory", block)

    def test_real_run_stops_on_a_recent_log_unless_forced(self):
        """(다) a release log written in the last 10 minutes stops a real run
        unless -Force; the dry-run branch only warns."""
        guard = self.text.split("$recentLogs = Get-RecentReleaseLogs", 1)[1]
        guard = guard.split("Start-Transcript", 1)[0]
        self.assertIn("RELEASE_LOG_FAIL", guard)
        self.assertIn("another release may be in progress", guard)
        self.assertIn("Pass -Force to release anyway", guard)
        self.assertIn("a real run stops here unless -Force (a dry-run only warns)", guard)


class ReleaseLogNumberRuntime(unittest.TestCase):
    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_number_picks_max_plus_one_from_a_mixed_list(self):
        """(나) release_31.failed.log + release_63.log mixed → next is 64; a
        non-numeric name (release_first.log) and foreign logs are ignored."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("release_31.failed.log", "release_63.log", "release_7.log",
                         "release_first.log", "chat_99.log"):
                (base / name).write_text("x", encoding="utf-8")
            code = (
                "$out = Resolve-ReleaseLogPath '' '" + str(base) + "'\n"
                "Write-Output ('RES=' + $out)\n"
            )
            rc, combined = _run_driver(code)
            self.assertEqual(rc, 0, combined)
            match = re.search(r"RES=(\S+)", combined)
            self.assertIsNotNone(match, combined)
            self.assertEqual(Path(match.group(1).strip()).name, "release_64.log")

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_explicit_existing_logpath_is_refused(self):
        """(나) an explicitly passed log path that already exists is refused —
        the audit log is never overwritten."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            existing = base / "release_55.log"
            existing.write_text("keep", encoding="utf-8")
            code = (
                "try { Resolve-ReleaseLogPath '" + str(existing) + "' '" + str(base) + "' | Out-Null; "
                "Write-Output 'NO_THROW' } catch { Write-Output ('THREW: ' + $_.Exception.Message) }\n"
            )
            rc, combined = _run_driver(code)
            self.assertEqual(rc, 0, combined)
            self.assertIn("THREW", combined)
            self.assertNotIn("NO_THROW", combined)
            self.assertIn("never overwritten", combined)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_explicit_new_logpath_is_returned_as_is(self):
        """(나) an explicit path that does not exist is honored (the caller
        owns the name only until it collides with a real file)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "release_named.log"
            code = (
                "$out = Resolve-ReleaseLogPath '" + str(target) + "' '" + str(base) + "'\n"
                "Write-Output ('RES=' + $out)\n"
            )
            rc, combined = _run_driver(code)
            self.assertEqual(rc, 0, combined)
            self.assertIn("RES=" + str(target), combined)
            self.assertFalse(target.exists())

    @unittest.skipIf(_powershell_exe() is None, "no PowerShell runtime on this runner")
    def test_recent_log_window_counts_only_new_files(self):
        """(다) the 10-minute window sees a fresh release log (failed logs
        included) and stops seeing it once it ages past the window."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "release_77.log").write_text("x", encoding="utf-8")
            (base / "release_78.failed.log").write_text("x", encoding="utf-8")
            (base / "release_79.log").write_text("x", encoding="utf-8")
            code = (
                "$c1 = @(Get-RecentReleaseLogs '" + str(base) + "').Count; "
                "(Get-Item (Join-Path '" + str(base) + "' 'release_79.log')).LastWriteTime = (Get-Date).AddMinutes(-20); "
                "$c2 = @(Get-RecentReleaseLogs '" + str(base) + "').Count; "
                "Write-Output ('COUNTS=' + $c1 + ',' + $c2)\n"
            )
            rc, combined = _run_driver(code)
            self.assertEqual(rc, 0, combined)
            self.assertIn("COUNTS=3,2", combined)


if __name__ == "__main__":
    unittest.main()
