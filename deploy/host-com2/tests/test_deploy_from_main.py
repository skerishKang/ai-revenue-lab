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
once = os.path.join(os.environ.get("FAKE_ROOT", ""), "fail_once_{svc}")
if os.path.exists(once):
    count = int(open(once).read().strip())
    if count <= 1:
        os.remove(once)
    else:
        open(once, "w").write(str(count - 1))
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
systemctl_bin=$SYSTEMCTL_BIN
python_bin=$PYTHON_BIN
git_bin=git
ai_check=${FAKE_AI_MODE:-warn}
run_deploy "$1"
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
    "apps/korean-ai-platform/asgi.py": "# b14\n",
    "packages/shared/placeholder.txt": "shared\n",
}

# The second commit decides which service the change belongs to.
CHANGES = {
    "chat": ("apps/padiem-chat/app/chat_marker.py", "CHAT = 2\n"),
    "p01": ("apps/padiem-ai-engine/asgi.py", "# engine 2\n"),
    "b14": ("apps/korean-ai-platform/asgi.py", "# b14 2\n"),
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
        (self.p01 / "app").symlink_to(release, target_is_directory=True)
        self.b14 = self.tmp / "b14-app"
        self.b14.mkdir()
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
            "COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY p01:SKIP b14:SKIP", result.stdout
        )
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])

    def test_apply_moves_the_checkout_and_installs_only_the_changed_service(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:PASS p01:SKIP b14:SKIP", result.stdout)
        self.assertEqual(self._head(), self.second)
        calls = self._calls()
        installs = [line for line in calls if line.startswith("install chat")]
        self.assertEqual(len(installs), 1, calls)
        self.assertIn(f"--source-root {self.ops.as_posix()}", installs[0])
        self.assertFalse([line for line in calls if line.startswith("install p01")])
        self.assertFalse([line for line in calls if line.startswith("install b14")])
        self.assertIn("systemctl stop padiem-chat-com2.service", calls)
        self.assertIn("systemctl start padiem-chat-com2.service", calls)
        previous = self.previous / self.first
        self.assertTrue((previous / "apps/padiem-chat/app/chat_marker.py").is_file())

    def test_ai_503_warn_leaves_deploy_in_place(self) -> None:
        self.env["FAKE_AI_CODE"] = "entitlement_unavailable"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:FAIL error_code=entitlement_unavailable", result.stdout)
        self.assertEqual(len([x for x in self._calls() if x.startswith("install chat")]), 1)

    def test_ai_401_required_rolls_back(self) -> None:
        self.env["FAKE_AI_CODE"] = "qa_login_refused"
        self.env["FAKE_AI_MODE"] = "required"
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("chat:ROLLBACK", result.stdout)
        self.assertIn("ai:FAIL error_code=qa_login_refused", result.stdout)
        self.assertEqual(len([x for x in self._calls() if x.startswith("install chat")]), 2)

    def test_ai_pass_has_no_error_code(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:PASS", result.stdout)

    def test_a_failed_health_check_rolls_the_service_back(self) -> None:
        self._fail_health_once("chat")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:ROLLBACK p01:SKIP b14:SKIP", result.stdout)
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
        self._fail_health_once("p01")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:SKIP p01:ROLLBACK b14:SKIP", result.stdout)
        installs = [line for line in self._calls() if line.startswith("install p01")]
        self.assertEqual(len(installs), 1, installs)
        snapshots = sorted((self.p01 / "rollback").glob("p01.fake*"))
        self.assertEqual(len(snapshots), 1, snapshots)
        marker = (self.p01 / "app" / "SNAPSHOT_ID").read_text(encoding="utf-8").strip()
        self.assertEqual(marker, snapshots[0].name)


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

    def test_b14_reports_a_manual_rollback_for_a_copied_checkout(self) -> None:
        self._fail_health_once("b14")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:ROLLBACK_FAILED", result.stdout
        )
        self.assertIn("COM2_DEPLOY_B14_ROLLBACK=MANUAL", result.stderr)


class ScriptBoundaryTest(unittest.TestCase):
    def test_the_script_only_mutates_behind_apply(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("systemctl enable", "wrangler", "openssl", "curl "):
            self.assertNotIn(forbidden, text)
        for required in ("--apply", "MIGRATION_FIRST", "ROLLBACK", "CHAT_DB_UNREADABLE"):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
