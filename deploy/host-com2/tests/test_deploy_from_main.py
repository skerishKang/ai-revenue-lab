"""Offline checks for deploy/host-com2/deploy_from_main.sh.

Every case runs the real script against a throwaway git repository whose
installers, health probes and systemctl are recording fakes. Nothing reaches
COM2, systemd, or a real service; no root is required.
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "deploy" / "host-com2" / "deploy_from_main.sh"
# CreateProcess prefers System32 (WSL) over PATH for "bash"; resolve it once.
BASH_BIN = os.environ.get("PADIEM_TEST_BASH") or shutil.which("bash") or "bash"

FAKE_INSTALL = """#!/usr/bin/env bash
set -euo pipefail
svc={svc}
echo "install ${{svc}} $*" >> "$FAKE_LOG"
if [[ $svc == p01 ]]; then
  snap="$P01_ROOT/rollback/p01.fake${{RANDOM}}"
  mkdir -p "$snap"
  printf '%s
' "$(basename "$snap")" > "$snap/SNAPSHOT_ID"
fi
exit "$(cat "$FAKE_ROOT/install_${{svc}}.rc" 2>/dev/null || echo 0)"
"""

FAKE_HEALTH = """#!/usr/bin/env python3
import os
import sys
root = os.environ.get("FAKE_ROOT", "")
counter = os.path.join(root, "calls_{svc}")
try:
    seen = int(open(counter).read().strip())
except (OSError, ValueError):
    seen = 0
open(counter, "w").write(str(seen + 1))
once = os.path.join(root, "fail_once_{svc}")
if os.path.exists(once):
    count = int(open(once).read().strip())
    if count <= 1:
        os.remove(once)
    else:
        open(once, "w").write(str(count - 1))
    print("HEALTH=FAIL STATUS=0")
    sys.exit(1)
until = os.path.join(root, "fail_{svc}")
if os.path.exists(until) and seen < int(open(until).read().strip()):
    print("HEALTH=FAIL STATUS=0")
    sys.exit(1)
print("HEALTH=PASS STATUS=200")
sys.exit(0)
"""

FAKE_SYSTEMCTL = """#!/usr/bin/env bash
echo "systemctl $*" >> "$FAKE_LOG"
if [[ $1 == is-active ]]; then
  exit "$(cat "$FAKE_ROOT/active_${3}" 2>/dev/null || echo 0)"
fi
exit 0
"""

APPLY_WRAPPER = """set -euo pipefail
source "$1"
shift
apply=1
ops_checkout=$OPS_CHECKOUT
state_dir=$STATE_DIR
chat_db=$CHAT_DB
p01_root=$P01_ROOT
b14_app=$B14_APP
queue_root=$QUEUE_ROOT
systemctl_bin=$SYSTEMCTL_BIN
python_bin=$PYTHON_BIN
git_bin=git
ai_check=${FAKE_AI_MODE:-warn}
run_deploy "$1"
"""

# The queue's own probe is a shell script, with the same failure knobs.
QUEUE_HEALTH = """#!/usr/bin/env bash
root=${FAKE_ROOT:-}
counter="$root/calls_queue"
seen=0
[[ -f $counter ]] && seen=$(cat "$counter")
echo $((seen + 1)) > "$counter"
if [[ -f $root/fail_once_queue ]]; then
  count=$(cat "$root/fail_once_queue")
  if (( count <= 1 )); then rm -f "$root/fail_once_queue"; else echo $((count - 1)) > "$root/fail_once_queue"; fi
  echo 'HEALTH=FAIL STATUS=0'
  exit 1
fi
if [[ -f $root/fail_queue ]] && (( seen < $(cat "$root/fail_queue") )); then
  echo 'HEALTH=FAIL STATUS=0'
  exit 1
fi
echo 'HEALTH=PASS STATUS=200'
"""

BASE_FILES = {
    "apps/padiem-chat/app/chat_marker.py": "CHAT = 1\n",
    "apps/padiem-chat/app/__init__.py": "",
    "apps/padiem-chat/migrations/001_auth_history.sql": "CREATE TABLE a (id INTEGER);\n",
    "apps/padiem-ai-engine/asgi.py": "# engine\n",
    "apps/padiem-ai-engine/app/__init__.py": "",
    "apps/padiem-ai-engine/clients/placeholder": "clients",
    "apps/padiem-ai-engine/ingress/placeholder": "ingress",
    "apps/padiem-ai-engine/migrations/placeholder": "migrations",
    "apps/padiem-ai-engine/worker.py": "# worker\n",
    "apps/padiem-ai-engine/worker_identity.py": "# identity\n",
    "packages/padiem-ai-core/padiem_ai_core/__init__.py": "# core\n",
    "packages/padiem-control-plane/padiem_control_plane/__init__.py": "# control\n",
    "apps/korean-ai-code-agent/src/kagent/__init__.py": "# kagent\n",
    "apps/korean-ai-platform/asgi.py": "# b14\n",
    "apps/padiem-mesh-queue/service.py": "# queue\n",
    "apps/padiem-mesh-queue/deploy/health_check.sh": QUEUE_HEALTH,
    "packages/shared/placeholder.txt": "shared\n",
}

# The second commit decides which service the change belongs to.
CHANGES = {
    "chat": ("apps/padiem-chat/app/chat_marker.py", "CHAT = 2\n"),
    "council": ("apps/padiem-council-apps/static/index.html", "council update\n"),
    "p01": ("apps/padiem-ai-engine/asgi.py", "# engine 2\n"),
    "b14": ("apps/korean-ai-platform/asgi.py", "# b14 2\n"),
    "queue": ("apps/padiem-mesh-queue/service.py", "# queue 2\n"),
    "migration": (
        "apps/padiem-chat/migrations/002_new_owner.sql",
        "ALTER TABLE a ADD COLUMN b TEXT;\n",
    ),
}


class DeployHarness(unittest.TestCase):
    """A throwaway origin + production checkout; no test methods of its own."""

    scenario = "chat"

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="com2-deploy-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = self.tmp / "origin.git"
        self._git(str(self.tmp), "init", "--bare", "-q", str(self.origin))
        self.ops = self.tmp / "ops"
        self.ops.mkdir()
        self._git(str(self.ops), "init", "-q")
        self._git(str(self.ops), "config", "user.email", "test@example.invalid")
        self._git(str(self.ops), "config", "user.name", "test")
        self._write_base()
        self.first = self._commit("base")
        self._git(str(self.ops), "remote", "add", "origin", str(self.origin))
        self._git(str(self.ops), "push", "-q", "-u", "origin", "HEAD:main")
        relative, text = CHANGES[self.scenario]
        self._write(relative, text)
        self.second = self._commit("change")
        self._git(str(self.ops), "push", "-q", "origin", "HEAD:main")
        # The host is still on the previous release; origin/main is ahead.
        self._git(str(self.ops), "checkout", "-q", "--detach", self.first)

        self.state = self.tmp / "state"
        self.previous = self.tmp / "releases" / "previous"
        self.fakes = self.tmp / "fakes"
        self.fakes.mkdir()
        self.log = self.tmp / "calls.log"
        self.p01 = self.tmp / "p01"
        (self.p01 / "rollback").mkdir(parents=True)
        release = self.p01 / "releases" / "initial"
        shutil.copytree(self.ops / "apps/padiem-ai-engine", release)
        for source, name in (
            ("packages/padiem-ai-core/padiem_ai_core", "padiem_ai_core"),
            ("packages/padiem-control-plane/padiem_control_plane", "padiem_control_plane"),
            ("apps/korean-ai-code-agent/src/kagent", "kagent"),
        ):
            shutil.copytree(self.ops / source, release / name)
        (self.p01 / "app").symlink_to(release, target_is_directory=True)
        self.b14 = self.tmp / "b14-app"
        self.b14.mkdir()
        self.queue = self.tmp / "mesh-queue"
        self.queue.mkdir()
        self.db = self.tmp / "chat.sqlite3"
        self._ledger(
            ["001_auth_history.sql"]
            + (["002_new_owner.sql"] if self.scenario != "migration" else [])
        )
        self.systemctl = self.tmp / "fake-systemctl"
        self.systemctl.write_text(FAKE_SYSTEMCTL, encoding="utf-8")
        self.systemctl.chmod(0o755)
        self.env = {
            **os.environ,
            "FAKE_LOG": str(self.log),
            "FAKE_ROOT": str(self.fakes),
            "P01_ROOT": str(self.p01),
            "PADIEM_COM2_STAGING_CHECKOUT": str(self.tmp / "staging-elsewhere"),
            "PADIEM_COM2_PYTHON": Path(sys.executable).as_posix(),
            "PADIEM_COM2_PREVIOUS_DIR": self.previous.as_posix(),
            "PADIEM_COM2_P01_APP": self.p01.as_posix(),
            "PADIEM_COM2_CHAT_HEALTH_ATTEMPTS": "1",
            "PADIEM_COM2_CHAT_HEALTH_INTERVAL": "0",
            # Bounded so a retry test finishes in seconds, not in the 30s default.
            "PADIEM_COM2_HEALTH_TIMEOUT": "4",
            "PADIEM_COM2_HEALTH_INTERVAL": "1",
        }

    # --- harness -----------------------------------------------------------

    def _git(self, cwd: str, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    def _write(self, relative: str, text: str) -> None:
        path = self.ops / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_base(self) -> None:
        for relative, text in BASE_FILES.items():
            self._write(relative, text)
        target = self.ops / "deploy/host-com2"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCRIPT, target / "deploy_from_main.sh")
        self._write(".github/scripts/post_deploy_ai_answer_check.py", """
import os
import sys
code = os.getenv("FAKE_AI_CODE", "none")
print("ai:PASS" if code == "none" else "ai:FAIL error_code=" + code)
sys.exit(0 if code == "none" else 1)
""")
        for service in ("chat", "p01", "b14"):
            install = self.ops / f"deploy/host-com2/{service}/install.sh"
            install.parent.mkdir(parents=True, exist_ok=True)
            install.write_text(FAKE_INSTALL.format(svc=service), encoding="utf-8")
            health = self.ops / f"deploy/host-com2/{service}/health.py"
            health.write_text(FAKE_HEALTH.format(svc=service), encoding="utf-8")

    def _commit(self, message: str) -> str:
        self._git(str(self.ops), "add", "-A")
        self._git(str(self.ops), "commit", "-q", "-m", message)
        return self._git(str(self.ops), "rev-parse", "HEAD")

    def _ledger(self, applied: list[str]) -> None:
        con = sqlite3.connect(self.db)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS padiem_local_migration_ledger "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            for name in applied:
                con.execute(
                    "INSERT OR REPLACE INTO padiem_local_migration_ledger VALUES (?, ?)",
                    (name, "2026-10-31T00:00:00+00:00"),
                )
            con.commit()
        finally:
            con.close()

    def _head(self) -> str:
        return self._git(str(self.ops), "rev-parse", "HEAD")

    def _run_main(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH_BIN, (self.ops / "deploy/host-com2/deploy_from_main.sh").as_posix(), *args],
            capture_output=True, text=True, errors="replace", env=self.env, check=False,
        )

    def _run_apply(self) -> subprocess.CompletedProcess[str]:
        env = {
            **self.env,
            "OPS_CHECKOUT": self.ops.as_posix(),
            "STATE_DIR": self.state.as_posix(),
            "CHAT_DB": self.db.as_posix(),
            "P01_ROOT": self.p01.as_posix(),
            "B14_APP": self.b14.as_posix(),
            "SYSTEMCTL_BIN": self.systemctl.as_posix(),
            "PYTHON_BIN": Path(sys.executable).as_posix(),
            "QUEUE_ROOT": self.queue.as_posix(),
        }
        return subprocess.run(
            [BASH_BIN, "-c", APPLY_WRAPPER, "bash",
             (self.ops / "deploy/host-com2/deploy_from_main.sh").as_posix(), self.second],
            capture_output=True, text=True, errors="replace", env=env, check=False,
        )

    def _calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text(encoding="utf-8").splitlines() if line]

    def _fail_health_once(self, service: str) -> None:
        (self.fakes / f"fail_once_{service}").write_text("1\n", encoding="utf-8")

    def _fail_service(self, service: str, times: int) -> None:
        # Fail the first `times` probes: long enough to outlast the retry window.
        (self.fakes / f"fail_{service}").write_text(f"{times}\n", encoding="utf-8")

    def _install_fails(self, service: str) -> None:
        # A failing installer is a verdict at once: no probe has to time out.
        (self.fakes / f"install_{service}.rc").write_text("1\n", encoding="utf-8")

    def _stage(self, sha: str | None = None) -> Path:
        return self.previous.parent / "src" / (sha or self.second)

    def _started(self, unit: str) -> int:
        return sum(1 for line in self._calls() if line == f"systemctl start {unit}")

    def _stage_dir(self) -> Path:
        stage = self.tmp / "src"
        self.env["PADIEM_COM2_SOURCE_DIR"] = stage.as_posix()
        return stage

    def _cached_stage(self, sha: str, stage: Path) -> Path:
        """A mirror that looks finished, so the run trusts it and only checks it."""
        target = stage / sha
        (target / "deploy/host-com2").mkdir(parents=True, exist_ok=True)
        (target / ".padiem-stage-complete").write_text(sha + "\n", encoding="utf-8")
        return target


class SourceStagingTest(DeployHarness):
    """The 9p permission fix: mirror first, verify, and never install from D:."""

    scenario = "chat"

    def test_stage_only_mirrors_and_touches_no_service(self) -> None:
        stage = self._stage_dir()
        result = self._run_main(
            self.second, "--stage-only",
            "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        self.assertIn("COM2_DEPLOY_MODE=STAGE_ONLY", out)
        self.assertIn("COM2_DEPLOY_SUMMARY=stage:PASS", out)
        self.assertTrue((stage / self.second / "apps/padiem-chat/app/chat_marker.py").exists(), out)
        self.assertIn("COM2_DEPLOY_READABLE_STAGED_USER", out)
        self.assertIn("FILES=0 DIRS=0", out)
        self.assertEqual(self._calls(), [], out)

    def test_unreadable_mirror_stops_before_any_service_is_touched(self) -> None:
        stage = self._stage_dir()
        target = self._cached_stage(self.second, stage)
        broken = target / "deploy/host-com2/broken.py"
        broken.write_text("x = 1\n", encoding="utf-8")
        broken.chmod(0o600)
        result = self._run_main(
            self.second, "--stage-only",
            "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, out)
        self.assertIn("COM2_DEPLOY_REASON=SOURCE_PERMISSIONS_STAGED", out)
        self.assertIn("FILES=1", out)
        self.assertEqual(self._calls(), [], out)

    def test_installs_read_the_mirror_and_not_the_checkout(self) -> None:
        # No cached mirror: the run must build it from the commit and install
        # from that path, so a 0600 checkout can never strand a service.
        stage = self._stage_dir()
        result = self._run_apply()
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        installs = [line for line in self._calls() if line.startswith("install ")]
        self.assertTrue(installs, out)
        self.assertIn(stage.as_posix(), " ".join(installs))
        self.assertNotIn(self.ops.as_posix(), " ".join(installs))


class ChatScenarioTest(DeployHarness):
    scenario = "chat"

    def test_dry_run_reports_the_plan_and_touches_nothing(self) -> None:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_MODE=DRY_RUN", result.stdout)
        self.assertIn(f"COM2_DEPLOY_SHA={self.second}", result.stdout)
        self.assertIn("COM2_DEPLOY_SERVICES=chat", result.stdout)
        self.assertIn("COM2_DEPLOY_PENDING_MIGRATIONS=none", result.stdout)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY p01:SKIP b14:SKIP queue:SKIP",
            result.stdout,
        )
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])

    def test_apply_moves_the_checkout_and_installs_only_the_changed_service(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:PASS p01:SKIP b14:SKIP queue:SKIP", result.stdout
        )
        self.assertEqual(self._head(), self.second)
        calls = self._calls()
        installs = [line for line in calls if line.startswith("install chat")]
        self.assertEqual(len(installs), 1, calls)
        # The installer reads the Linux-side mirror of this commit, never the
        # checkout: on 9p a 0644 file can still be unreadable for the service.
        stage = self.previous.parent / "src" / self.second
        self.assertEqual(installs[0], f"install chat --apply --source-root {stage.as_posix()}")
        self.assertTrue((stage / "apps/padiem-chat/app/chat_marker.py").is_file())
        self.assertFalse([line for line in calls if line.startswith("install p01")])
        self.assertFalse([line for line in calls if line.startswith("install b14")])
        self.assertIn("systemctl stop padiem-chat-com2.service", calls)
        self.assertIn("systemctl start padiem-chat-com2.service", calls)
        previous = self.previous / self.first
        self.assertTrue((previous / "apps/padiem-chat/app/chat_marker.py").is_file())

    def test_checkout_repairs_restricted_tracked_files_without_exposing_secrets(self) -> None:
        import stat
        unchanged = self.ops / "apps/padiem-chat/app/__init__.py"
        unchanged.chmod(0o600)
        secret = self.ops / "private.env"
        secret.write_text("test-only", encoding="utf-8")
        secret.chmod(0o600)
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.ops / "apps/padiem-chat/app/chat_marker.py"
        self.assertEqual(stat.S_IMODE(unchanged.stat().st_mode), 0o644)
        self.assertTrue(source.stat().st_mode & stat.S_IROTH)
        self.assertEqual(stat.S_IMODE(secret.stat().st_mode), 0o600)
        if os.name == "posix" and os.geteuid() == 0:
            import pwd
            self.tmp.chmod(0o755)
            try:
                user = pwd.getpwnam("padiem-chat")
            except KeyError:
                user = pwd.getpwnam("nobody")
            def drop():
                os.setgroups([])
                os.setgid(user.pw_gid)
                os.setuid(user.pw_uid)
            probe = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); import app.chat_marker",
                 str(self.ops / "apps/padiem-chat")],
                preexec_fn=drop, capture_output=True, text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_ai_503_warn_leaves_deploy_in_place(self) -> None:
        self.env["FAKE_AI_CODE"] = "entitlement_unavailable"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:FAIL error_code=entitlement_unavailable", result.stdout)
        self.assertEqual(len([x for x in self._calls() if x.startswith("install chat")]), 1)

    def test_ai_401_required_rolls_back(self) -> None:
        self.env["FAKE_AI_CODE"] = "qa_login_refused"
        self.env["FAKE_AI_MODE"] = "required"
        self.env["B66_CGI_ALPHA_USERNAME"] = "qa-fixture"
        self.env["B66_CGI_ALPHA_PASSWORD"] = "qa-fixture"
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("chat:ROLLBACK", result.stdout)
        self.assertIn("ai:FAIL error_code=qa_login_refused", result.stdout)
        self.assertEqual(len([x for x in self._calls() if x.startswith("install chat")]), 2)

    def test_missing_required_credentials_stop_before_service_changes(self) -> None:
        self.env["FAKE_AI_MODE"] = "required"
        self.env["B66_CGI_ALPHA_USERNAME"] = ""
        self.env["B66_CGI_ALPHA_PASSWORD"] = ""
        result = self._run_apply()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("AI_CHECK_REQUIRED_CREDENTIALS_MISSING", result.stderr)
        self.assertIn("RERUN_WITH_CREDENTIALS_OR_EXPLICIT_WARN", result.stderr)
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])

    def test_ai_pass_has_no_error_code(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:PASS", result.stdout)

    def test_a_failed_health_check_rolls_the_service_back(self) -> None:
        self._fail_health_once("chat")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:ROLLBACK p01:SKIP b14:SKIP queue:SKIP", result.stdout
        )
        installs = [line for line in self._calls() if line.startswith("install chat")]
        self.assertEqual(len(installs), 2, installs)
        self.assertIn((self.previous / self.first).as_posix(), installs[1])
        self.assertIn("systemctl start padiem-chat-com2.service", self._calls())

    def test_slow_chat_start_is_retried_without_rollback(self) -> None:
        import time
        (self.fakes / "fail_once_chat").write_text("5", encoding="utf-8")
        self.env["PADIEM_COM2_CHAT_HEALTH_ATTEMPTS"] = "6"
        self.env["PADIEM_COM2_CHAT_HEALTH_INTERVAL"] = "2"
        started = time.monotonic()
        result = self._run_apply()
        self.assertGreaterEqual(time.monotonic() - started, 10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("HEALTH=FAIL STATUS=0"), 5)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:PASS", result.stdout)
        self.assertEqual(len([c for c in self._calls() if c.startswith("install chat")]), 1)

    def test_previous_checkout_is_readable_not_writable_by_service_user(self) -> None:
        import stat
        self._fail_health_once("chat")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        previous = self.previous / self.first
        source = previous / "apps/padiem-chat/app/chat_marker.py"
        for part in (self.previous, previous, previous / "apps",
                     previous / "apps/padiem-chat", source.parent):
            self.assertTrue(part.stat().st_mode & stat.S_IROTH, str(part))
            self.assertTrue(part.stat().st_mode & stat.S_IXOTH, str(part))
            self.assertFalse(part.stat().st_mode & stat.S_IWOTH, str(part))
        self.assertTrue(source.stat().st_mode & stat.S_IROTH)
        self.assertFalse(source.stat().st_mode & stat.S_IWOTH)
        self.assertFalse(source.stat().st_mode & stat.S_IWGRP)
        # When root is available, run the actual import as an unprivileged
        # service identity rather than inferring access from modes alone.
        if os.name == "posix" and os.geteuid() == 0:
            import pwd
            self.tmp.chmod(0o755)
            try:
                user = pwd.getpwnam("padiem-chat")
            except KeyError:
                user = pwd.getpwnam("nobody")
            def drop_privileges():
                os.setgroups([])
                os.setgid(user.pw_gid)
                os.setuid(user.pw_uid)
            probe = subprocess.run(
                [sys.executable, "-I", "-c",
                 "import sys; sys.path.insert(0, sys.argv[1]); import app.chat_marker",
                 str(previous / "apps/padiem-chat")],
                preexec_fn=drop_privileges, capture_output=True, text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_a_sha_that_is_not_origin_main_is_refused(self) -> None:
        result = self._run_main(
            self.first, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("SHA_NOT_ORIGIN_MAIN", result.stderr)

    def test_a_checkout_shared_with_staging_is_refused(self) -> None:
        self.env["PADIEM_COM2_STAGING_CHECKOUT"] = self.ops.as_posix()
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("OPS_CHECKOUT_IS_STAGING", result.stderr)

    def test_an_unreadable_chat_database_is_refused_on_apply(self) -> None:
        self.db.unlink()
        result = self._run_apply()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("CHAT_DB_UNREADABLE", result.stderr)
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])


class CouncilAssetScenarioTest(DeployHarness):
    scenario = "council"

    def test_council_asset_change_selects_chat_deploy(self):
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_SERVICES=chat", result.stdout)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY", result.stdout)


class MigrationScenarioTest(DeployHarness):
    scenario = "migration"

    def test_a_new_migration_stops_before_any_code_moves(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertIn("COM2_DEPLOY_MIGRATION_FIRST=YES", result.stderr)
        self.assertIn("마이그레이션 먼저", result.stderr)
        self.assertIn("002_new_owner.sql", result.stderr)
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])


class P01ScenarioTest(DeployHarness):
    scenario = "p01"

    def test_p01_rolls_back_to_the_previous_release_snapshot(self) -> None:
        self._install_fails("p01")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:ROLLBACK b14:SKIP queue:SKIP", result.stdout
        )
        # The rollback is verified with the same patience as a fresh start.
        self.assertIn("COM2_DEPLOY_HEALTH_P01_ROLLBACK_ATTEMPTS=1", result.stdout)

    def test_a_slow_p01_start_is_not_reported_as_a_broken_release(self) -> None:
        self._fail_health_once("p01")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_P01_ATTEMPTS=2", result.stdout)
        self.assertIn("p01:PASS", result.stdout)
        self.assertNotIn("P01_ROLLBACK", result.stdout)

    def test_a_p01_that_never_becomes_healthy_is_retried_then_rolled_back(self) -> None:
        self._fail_service("p01", 20)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        attempts = int(result.stdout.split("COM2_DEPLOY_HEALTH_P01_ATTEMPTS=")[1].split()[0])
        self.assertGreaterEqual(attempts, 3, result.stdout)
        self.assertIn("p01:ROLLBACK_FAILED", result.stdout)
        installs = [line for line in self._calls() if line.startswith("install p01")]
        self.assertEqual(len(installs), 1, installs)
        snapshots = sorted((self.p01 / "rollback").glob("p01.fake*"))
        self.assertEqual(len(snapshots), 1, snapshots)
        marker = (self.p01 / "app" / "SNAPSHOT_ID").read_text(encoding="utf-8").strip()
        self.assertEqual(marker, snapshots[0].name)


    def test_rollback_replaces_real_app_directory(self) -> None:
        (self.p01 / "app").unlink()
        (self.p01 / "app").mkdir()
        (self.p01 / "app" / "marker").write_text("current", encoding="utf-8")
        (self.p01 / "app" / "cycle").symlink_to(".", target_is_directory=True)
        self._install_fails("p01")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("p01:ROLLBACK", result.stdout)
        self.assertTrue((self.p01 / "app").is_symlink())
        self.assertTrue((self.p01 / "app" / "SNAPSHOT_ID").is_file())
        moved = list((self.p01 / "releases").glob("p01.displaced.*/marker"))
        self.assertEqual(len(moved), 1)
        self.assertEqual(moved[0].read_text(encoding="utf-8"), "current")

    def test_shared_package_drift_is_not_skipped(self) -> None:
        release = (self.p01 / "app").resolve()
        (release / "padiem_ai_core" / "__init__.py").write_text("# stale\n", encoding="utf-8")
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_P01_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", result.stdout)
        self.assertIn("p01:PASS", result.stdout)

    def test_p01_running_link_mismatch_is_not_skipped(self) -> None:
        release = (self.p01 / "app").resolve()
        (release / "asgi.py").write_text("# stale release\n", encoding="utf-8")
        self._git(str(self.ops), "checkout", "-q", "--detach", self.second)
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_P01_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", result.stdout)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:SKIP p01:PASS b14:SKIP", result.stdout)
        self.assertTrue(any(c.startswith("install p01") for c in self._calls()))


class B14ScenarioTest(DeployHarness):
    scenario = "b14"

    def test_b14_runs_from_the_mirror_and_keeps_the_operator_copy(self) -> None:
        (self.b14 / "operator-marker").write_text("hand staged\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:PASS queue:SKIP", result.stdout
        )
        self.assertTrue(self.b14.is_symlink(), self.b14.readlink())
        self.assertEqual(
            self.b14.resolve(), (self._stage() / "apps/korean-ai-platform").resolve()
        )
        self.assertIn("install b14 --reload", self._calls())
        displaced = list(self.b14.parent.glob("b14-app.displaced-*"))
        self.assertEqual(len(displaced), 1, displaced)
        self.assertEqual(
            (displaced[0] / "operator-marker").read_text(encoding="utf-8"), "hand staged\n"
        )

    def test_a_slow_b14_start_is_not_reported_as_a_broken_release(self) -> None:
        self._fail_health_once("b14")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_B14_ATTEMPTS=2", result.stdout)
        self.assertIn("b14:PASS", result.stdout)

    def test_a_failed_b14_install_falls_back_to_the_previous_tree(self) -> None:
        self._install_fails("b14")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("b14:ROLLBACK", result.stdout)
        self.assertEqual(
            self.b14.resolve(),
            (self.previous / self.first / "apps/korean-ai-platform").resolve(),
        )
        # The installer failed before the unit was ever started, so the rollback
        # start is the only one — and the unit must be up after it.
        self.assertEqual(self._started("padiem-b14.service"), 1, self._calls())

    def test_manual_rollback_still_leaves_the_unit_started(self) -> None:
        # A link to nowhere is the one thing this script cannot put back. It must say
        # MANUAL and still bring the service up: a stopped unit is not a rollback.
        (self.previous / self.first).mkdir(parents=True)
        self.b14.rmdir()
        self.b14.symlink_to(self.tmp / "gone")
        self._install_fails("b14")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_B14_ROLLBACK=MANUAL", result.stderr)
        self.assertIn("b14:ROLLBACK", result.stdout)
        self.assertEqual(self._started("padiem-b14.service"), 1, self._calls())


class MeshQueueScenarioTest(DeployHarness):
    scenario = "queue"

    def test_queue_code_is_staged_from_the_mirror_and_restarts(self) -> None:
        (self.queue / "queue.env").write_text("MESH_QUEUE_DB_PATH=/keep\n", encoding="utf-8")
        (self.queue / "queue.sqlite3").write_text("data", encoding="utf-8")
        (self.queue / "src").mkdir()
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_SERVICES=queue", result.stdout)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:PASS", result.stdout
        )
        self.assertEqual(
            (self.queue / "service.py").read_text(encoding="utf-8"), "# queue 2\n"
        )
        self.assertEqual(
            (self.queue / "app").resolve(), (self._stage() / "apps/padiem-chat/app").resolve()
        )
        self.assertEqual(
            (self.queue / "padiem_ai_core").resolve(),
            (self._stage() / "packages/padiem-ai-core/padiem_ai_core").resolve(),
        )
        # The operator's state is never part of a deploy.
        self.assertEqual(
            (self.queue / "queue.env").read_text(encoding="utf-8"), "MESH_QUEUE_DB_PATH=/keep\n"
        )
        self.assertTrue((self.queue / "queue.sqlite3").is_file())
        self.assertTrue((self.queue / "src").is_dir())
        self.assertEqual(self._started("padiem-mesh-queue.service"), 1, self._calls())

    def test_a_slow_queue_start_is_not_reported_as_a_broken_release(self) -> None:
        self._fail_health_once("queue")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_QUEUE_ATTEMPTS=2", result.stdout)
        self.assertIn("queue:PASS", result.stdout)

    def test_a_broken_queue_rolls_its_code_back_and_stays_started(self) -> None:
        self._fail_service("queue", 20)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("queue:ROLLBACK_FAILED", result.stdout)
        self.assertEqual(
            (self.queue / "service.py").read_text(encoding="utf-8"), "# queue\n"
        )
        self.assertEqual(self._started("padiem-mesh-queue.service"), 2, self._calls())


class ScriptBoundaryTest(unittest.TestCase):
    def test_start_probes_are_given_thirty_seconds_by_default(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("health_timeout=${PADIEM_COM2_HEALTH_TIMEOUT:-30}", text)
        for label in ("P01", "B14", "QUEUE", "P01_ROLLBACK", "B14_ROLLBACK", "QUEUE_ROLLBACK"):
            self.assertIn(f"wait_for_health {label} ", text)
        # No single-shot probe is left behind a start or a rollback.
        self.assertNotIn(
            chr(10) + '    "$python_bin" "$staged/deploy/host-com2/p01/health.py"', text
        )
        self.assertNotIn('"$python_bin" "$ops_checkout/deploy/host-com2/b14/health.py"', text)

    def test_the_script_only_mutates_behind_apply(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("systemctl enable", "wrangler", "openssl", "curl "):
            self.assertNotIn(forbidden, text)
        for required in ("--apply", "MIGRATION_FIRST", "ROLLBACK", "CHAT_DB_UNREADABLE"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
