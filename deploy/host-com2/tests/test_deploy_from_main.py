"""Offline checks for deploy/host-com2/deploy_from_main.sh.

Every case runs the real script against a throwaway git repository whose
installers, health probes and systemctl are recording fakes. Nothing reaches
COM2, systemd, or a real service; no root is required.
"""
from __future__ import annotations

import getpass
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
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
# Shared unit state: missing file means active (the harness default), stop
# writes 0, start writes 1. The fake ss reads the same files, so a stopped
# unit's port really disappears from `ss -ltn`.
state_file() { printf '%s/%s' "$FAKE_ROOT" "state_${1}"; }
case "$1" in
  is-active)
    state=$(cat "$(state_file "$3")" 2>/dev/null || echo 1)
    [[ -f "$FAKE_ROOT/active_${3}" ]] && state=$(cat "$FAKE_ROOT/active_${3}")
    [[ $state == 1 ]]; exit $?
    ;;
  show)
    # `show -p <property> --value <unit>`: the unit name is argument 5.
    unit="${5}"
    property="${3}"
    case "$property" in
      MainPID)
        # MainPID 0 means the previous process is gone; a marker pins a wedged PID.
        if [[ -f "$FAKE_ROOT/mainpid_${unit}" ]]; then
          cat "$FAKE_ROOT/mainpid_${unit}"
        elif [[ $(cat "$(state_file "${unit}")" 2>/dev/null || echo 0) == 1 ]]; then
          echo 4242
        else
          echo 0
        fi
        ;;
      ActiveState)
        # `restarting_<unit>` is the Restart=always window: the last start died
        # and systemd holds the next attempt, where is-active is already false.
        if [[ -f "$FAKE_ROOT/restarting_${unit}" ]]; then
          echo activating
        elif [[ $(cat "$(state_file "${unit}")" 2>/dev/null || echo 1) == 1 ]]; then
          echo active
        else
          echo inactive
        fi
        ;;
      LoadState)
        if [[ -f "$FAKE_ROOT/not_loaded_${unit}" ]]; then echo not-found; else echo loaded; fi
        ;;
    esac
    exit 0
    ;;
  stop)
    echo 0 > "$(state_file "$2")"
    rm -f "$FAKE_ROOT/restarting_$2"
    ;;
  start)
    # `crashed_<unit>` models a process that dies at once: systemd reports the
    # unit inactive while it waits out RestartSec for the next attempt.
    if [[ -f "$FAKE_ROOT/crashed_$2" ]]; then
      echo 0 > "$(state_file "$2")"
      echo 1 > "$FAKE_ROOT/restarting_$2"
    else
      echo 1 > "$(state_file "$2")"
      rm -f "$FAKE_ROOT/restarting_$2"
    fi
    key="$FAKE_ROOT/starts_${2}"
    n=$(cat "$key" 2>/dev/null || echo 0)
    echo $((n + 1)) > "$key"
    # The second start of one unit in a single run is the rollback start. The
    # broken-release knobs model the failure of the NEW release only, so the
    # rollback start clears them: the old release is healthy by construction.
    if (( n + 1 >= 2 )); then
      case "$2" in
        padiem-chat-com2.service) rm -f "$FAKE_ROOT/fail_chat" "$FAKE_ROOT/ss_hide_8798" ;;
        padiem-p01.service)       rm -f "$FAKE_ROOT/fail_p01"  "$FAKE_ROOT/ss_hide_8811" ;;
        padiem-b14.service)       rm -f "$FAKE_ROOT/fail_b14"  "$FAKE_ROOT/ss_hide_8789" ;;
      esac
    fi
    ;;
esac
exit 0
"""

FAKE_JOURNALCTL = """#!/usr/bin/env bash
echo "journalctl $*" >> "$FAKE_LOG"
# journal_traceback holds how many of the next calls report a traceback: the
# deploy checks once, the rollback opens its own window.
marker="$FAKE_ROOT/journal_traceback"
if [[ -f $marker ]]; then
  left=$(cat "$marker")
  if (( left > 0 )); then
    echo "Traceback (most recent call last):"
    echo $((left - 1)) > "$marker"
  fi
fi
exit 0
"""

FAKE_SS = """#!/usr/bin/env bash
# Stand-in for `ss -ltn`: one line per listening loopback port in the REAL
# shape (state, queues, local address, peer address) — 11-02 the old fake
# printed the local address alone, which hid an end-of-line-anchor bug.
# A port shows up only while its unit is running (the shared state_ files the
# fake systemctl maintains), and additionally:
# ss_hide_<port>    the port does not listen while the marker exists (a release
#                   that never binds the watched port).
# ss_delay_<port>   the port starts listening on invocation N+1 only — a slow
#                   bind, one poll per second in production.
root=${FAKE_ROOT:-}
shown=""
for entry in 8798:padiem-chat-com2.service 8811:padiem-p01.service 8789:padiem-b14.service; do
  port=${entry%%:*}
  unit=${entry#*:}
  state=$(cat "$root/state_${unit}" 2>/dev/null || echo 1)
  [[ $state == 1 ]] || continue
  [[ -f "$root/ss_hide_$port" ]] && continue
  if [[ -f "$root/ss_delay_$port" ]]; then
    threshold=$(cat "$root/ss_delay_$port")
    counter="$root/calls_ss_delay_$port"
    n=0
    [[ -f $counter ]] && n=$(cat "$counter")
    echo $((n + 1)) > "$counter"
    (( n >= threshold )) || continue
  fi
  shown+="LISTEN 0      2048       127.0.0.1:$port      0.0.0.0:*"$'\\n'
done
printf '%s' "$shown"
"""

APPLY_WRAPPER = """set -euo pipefail
source "$1"
shift
apply=1
ops_checkout=$OPS_CHECKOUT
state_dir=$STATE_DIR
chat_db=$CHAT_DB
chat_db_user=
p01_root=$P01_ROOT
b14_app=$B14_APP
queue_root=$QUEUE_ROOT
queue_unit_dir=$QUEUE_UNIT_DIR
systemctl_bin=$SYSTEMCTL_BIN
journalctl_bin=$JOURNALCTL_BIN
executor_root=$ORACLE_MESH_ROOT
executor_src=$executor_root/kagent-src
executor_releases=$executor_root/src
executor_unit_dir=$EXECUTOR_UNIT_DIR
python_bin=$PYTHON_BIN
git_bin=git
ai_check=${FAKE_AI_MODE:-warn}
run_deploy "$1"
"""

# One service function, without the pre-deploy "enabled but stopped" start.
DEPLOY_CHAT_WRAPPER = """set -euo pipefail
source "$1"
apply=1
systemctl_bin=$SYSTEMCTL_BIN
python_bin=$PYTHON_BIN
staged=$OPS_CHECKOUT
deploy_chat
"""

# The queue's own probe is a shell script, with the same failure knobs.
QUEUE_HEALTH = """#!/usr/bin/env bash
root=${FAKE_ROOT:-}
counter="$root/calls_queue"
seen=0
[[ -f $counter ]] && seen=$(cat "$counter")
echo $((seen + 1)) > "$counter"
starts=$(cat "$root/starts_padiem-mesh-queue.service" 2>/dev/null || echo 0)
if [[ -f $root/queue_health_output ]] && (( starts == 1 )); then
  cat "$root/queue_health_output"
  exit 0
fi
if [[ -f $root/fail_once_queue ]]; then
  count=$(cat "$root/fail_once_queue")
  if (( count <= 1 )); then rm -f "$root/fail_once_queue"; else echo $((count - 1)) > "$root/fail_once_queue"; fi
  echo 'MESH_QUEUE_HEALTH=UNREACHABLE curl=7'
  exit 1
fi
if [[ -f $root/fail_queue ]] && (( seen < $(cat "$root/fail_queue") )); then
  echo 'MESH_QUEUE_HEALTH=UNREACHABLE curl=7'
  exit 1
fi
echo 'MESH_QUEUE_HEALTH=OK pending_unclaimed=0 pending_claimed=0 received=0'
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
    "packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py": "# metrics\n",
    # The installer stages every Core module deploy.sh lists (#6855 fix), so the
    # fixture tree must carry the whole list the real checkout carries.
    "packages/padiem-ai-core/padiem_ai_core/document_semantics.py": "# semantics\n",
    "packages/padiem-ai-core/padiem_ai_core/document_normalization.py": "# normalization\n",
    "packages/padiem-ai-core/padiem_ai_core/document_parser_boundary.py": "# boundary\n",
    "packages/padiem-ai-core/padiem_ai_core/conversation_bounds.py": "# bounds\n",
    "packages/padiem-ai-core/padiem_ai_core/evidence_blocks.py": "# evidence\n",
    "packages/padiem-control-plane/padiem_control_plane/__init__.py": "# control\n",
    "packages/padiem-control-plane/padiem_control_plane/models_registry.py": "# registry\n",
    "apps/korean-ai-code-agent/src/kagent/__init__.py": "# kagent\n",
    # The executor imports the Core package, as the real one does.
    "apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py": (
        "import padiem_ai_core\n\n# executor\n"
    ),
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
        "CREATE TABLE IF NOT EXISTS new_owner (id INTEGER);\n",
    ),
}


CHANGES.update({
    "tests_only": ("apps/padiem-chat/tests/test_added.py", "test fixture\n"),
    "code_and_test": ("apps/padiem-chat/app/chat_marker.py", "CHAT = 2\n"),
    "docs_only": ("docs/ops/deploy-note.md", "documentation\n"),
    "runtime_config": ("apps/padiem-chat/.env", "SAMPLE_SETTING=changed\n"),
    "common_unit_policy": (
        "deploy/host-com2/restart-policy/10-padiem-restart.conf",
        "[Service] changed\\n",
    ),
    "shared_runtime": (
        "packages/padiem-ai-core/padiem_ai_core/pc_work_metrics.py",
        "# shared runtime changed\\n",
    ),
    "historical_test_paths": (
        "apps/korean-ai-platform/tests/test_5784_b14_local_runtime.py",
        "test fixture\n",
    ),
    # The deploy script itself has no service mapping: the plan selects nothing
    # for it, which is exactly the case that used to strand the checkout.
    "deploy_script_only": (
        "deploy/host-com2/deploy_from_main.sh",
        "#!/usr/bin/env bash\n# script-only change\n",
    ),
})


EXTRA_CHANGES = {
    "tests_only": [
        ("apps/padiem-ai-engine/test_engine.py", "assert True\\n"),
        ("apps/korean-ai-platform/test_registry.py", "assert True\\n"),
        ("apps/padiem-mesh-queue/conftest.py", "# fixture\\n"),
        ("deploy/host-com2/p01/tests/test_p01_packaging.py", "# fixture\\n"),
        ("apps/padiem-chat/static/interaction.test.mjs", "test fixture\\n"),
        ("apps/padiem-chat/scripts/check_test.py", "test fixture\\n"),
        ("apps/padiem-chat/pytest.ini", "[pytest]\\n"),
        ("apps/padiem-chat/.env.example", "SAMPLE_SETTING=example\\n"),
        ("docs/operations/plan.md", "documentation\\n"),
        (".gitignore", "artifact\\n"),
        ("progress.md", "checkpoint\\n"),
    ],
    "code_and_test": [
        ("apps/padiem-chat/tests/test_chat_marker.py", "assert True\\n"),
    ],
    "docs_only": [
        ("README.md", "documentation\\n"),
    ],
    "runtime_config": [
        ("apps/padiem-ai-engine/uv.lock", "# lock\\n"),
        ("apps/korean-ai-platform/requirements.txt", "# requirements\\n"),
        ("apps/padiem-mesh-queue/deploy/padiem-mesh-queue.service", "[Service]\\n"),
        ("deploy/host-com2/chat/padiem-chat-com2.service", "[Service]\\n"),
        ("apps/padiem-chat/.env.example", "SAMPLE_SETTING=example\\n"),
    ],
    "historical_test_paths": [
        ("apps/korean-ai-platform/tests/test_b14_model_registry_file.py", "test fixture\\n"),
        ("apps/korean-ai-platform/tests/test_owner_startup_command.py", "test fixture\\n"),
        ("apps/korean-ai-platform/tests/test_pc_work_metrics_com2_staging.py", "test fixture\\n"),
        ("apps/padiem-mesh-queue/conftest.py", "# fixture\\n"),
        ("apps/padiem-mesh-queue/tests/test_copy_state.py", "test fixture\\n"),
        ("apps/padiem-mesh-queue/tests/test_mesh_drive_refresh_end_to_end.py", "test fixture\\n"),
        ("apps/padiem-mesh-queue/tests/test_queue_to_d1.py", "test fixture\\n"),
        ("apps/padiem-mesh-queue/tests/test_queue_watchdog.py", "test fixture\\n"),
        ("deploy/host-com2/p01/tests/test_p01_packaging.py", "test fixture\\n"),
        ("apps/padiem-chat/app/local_cpython.py", "CHAT_RUNTIME = changed\\n"),
        ("apps/padiem-chat/conftest.py", "# fixture\\n"),
        ("apps/padiem-chat/tests/test_2505_chat_claw_conversation_continuity.py", "test fixture\\n"),
        ("deploy/host-com2/tests/test_deploy_from_main.py", "test fixture\\n"),
        ("packages/padiem-ai-core/tests/test_pillow_wheel_receipts.py", "test fixture\\n"),
        ("deploy/host-com2/chat/.env.example", "EXAMPLE_SETTING=changed\\n"),
        (".gitignore", "generated\\n"),
        ("progress.md", "checkpoint\\n"),
    ],
}


class DeployHarness(unittest.TestCase):
    """A throwaway origin + production checkout; no test methods of its own."""

    scenario = "chat"
    base_extra: dict[str, str] = {}

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
        for relative, text in [CHANGES[self.scenario], *EXTRA_CHANGES.get(self.scenario, [])]:
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
        # No B14 tree by default: the running-code comparison must report
        # NOT_INSTALLED, not a mismatch, for every scenario that never installs it.
        self.b14 = self.tmp / "b14-app"
        self.queue = self.tmp / "mesh-queue"
        self.queue.mkdir()
        self.units = self.tmp / "units"
        self.units.mkdir()
        self.executor_units = self.tmp / "executor-units"
        self.executor_units.mkdir()
        self.db = self.tmp / "chat.sqlite3"
        self._ledger(
            ["001_auth_history.sql"]
            + (["002_new_owner.sql"] if self.scenario != "migration" else [])
        )
        self.systemctl = self.tmp / "fake-systemctl"
        self.systemctl.write_text(FAKE_SYSTEMCTL, encoding="utf-8")
        self.systemctl.chmod(0o755)
        self.journalctl = self.tmp / "fake-journalctl"
        self.journalctl.write_text(FAKE_JOURNALCTL, encoding="utf-8")
        self.journalctl.chmod(0o755)
        self.fake_ss = self.tmp / "fake-ss"
        self.fake_ss.write_text(FAKE_SS, encoding="utf-8")
        self.fake_ss.chmod(0o755)
        self.env = {
            **os.environ,
            "FAKE_LOG": str(self.log),
            "FAKE_ROOT": str(self.fakes),
            "P01_ROOT": str(self.p01),
            "PADIEM_COM2_STAGING_CHECKOUT": str(self.tmp / "staging-elsewhere"),
            "PADIEM_COM2_PYTHON": Path(sys.executable).as_posix(),
            "PADIEM_COM2_PREVIOUS_DIR": self.previous.as_posix(),
            "PADIEM_COM2_P01_APP": self.p01.as_posix(),
            "PADIEM_COM2_CHAT_APP": (self.tmp / "chat-app").as_posix(),
            "PADIEM_COM2_SS": self.fake_ss.as_posix(),
            # Bounded so a retry test finishes in seconds, not in the 30s default.
            "PADIEM_COM2_HEALTH_TIMEOUT": "4",
            "PADIEM_COM2_HEALTH_INTERVAL": "1",
            "PADIEM_COM2_UNIT_WAIT_TIMEOUT": "2",
            "PADIEM_COM2_PORT_WAIT_TIMEOUT": "2",
            "PADIEM_COM2_STOP_WAIT_TIMEOUT": "2",
            "PADIEM_COM2_WAIT_POLL_INTERVAL": "0",
        }

    # --- harness -----------------------------------------------------------

    def _git(self, cwd: str, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True
        )
        return result.stdout.strip()

    def _write(self, relative: str, text: str) -> None:
        path = self.ops / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_base(self) -> None:
        for relative, text in BASE_FILES.items():
            self._write(relative, text)
        # A scenario may need a base file of its own (an import chain the
        # queue really has) without changing what every scenario starts from.
        for relative, text in type(self).base_extra.items():
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
        # #6898's backup kit is run by the queue leg, so it gets the same fake.
        backup_install = self.ops / "deploy/host-com2/mesh-queue-backup/install.sh"
        backup_install.parent.mkdir(parents=True, exist_ok=True)
        backup_install.write_text(
            FAKE_INSTALL.format(svc="mesh-queue-backup"), encoding="utf-8"
        )

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
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=self.env, check=False,
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
            "JOURNALCTL_BIN": self.journalctl.as_posix(),
            "ORACLE_MESH_ROOT": (self.tmp / "oracle-mesh").as_posix(),
            "PYTHON_BIN": Path(sys.executable).as_posix(),
            "QUEUE_ROOT": self.queue.as_posix(),
            "QUEUE_UNIT_DIR": self.units.as_posix(),
            "EXECUTOR_UNIT_DIR": self.executor_units.as_posix(),
        }
        return subprocess.run(
            [BASH_BIN, "-c", APPLY_WRAPPER, "bash",
             (self.ops / "deploy/host-com2/deploy_from_main.sh").as_posix(), self.second],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False,
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


class DeployLockTest(DeployHarness):
    """One run at a time: a plan must not read a checkout another apply moves."""

    scenario = "chat"

    def _hold_lock(self) -> None:
        """Hold the deploy lock the way the script would, and keep it held."""
        lock = self.state / "deploy.lock"
        self.state.mkdir(parents=True, exist_ok=True)
        if shutil.which("flock"):
            try:
                import fcntl
            except ImportError:  # pragma: no cover - no flock means no fcntl
                self.skipTest("fcntl is required to hold the deploy lock")
            handle = open(lock, "a+", encoding="utf-8")
            self.addCleanup(handle.close)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        # The directory fallback needs a live PID; the holder shell owns it.
        lock_dir = lock.parent / (lock.name + ".d")
        self.addCleanup(shutil.rmtree, lock_dir, True)
        holder = subprocess.Popen(
            [
                BASH_BIN,
                "-c",
                'mkdir -p -- "$1" && printf "%s\n" "$$" > "$1/pid" && exec sleep 60',
                "bash",
                lock_dir.as_posix(),
            ],
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        pid_file = lock_dir / "pid"
        deadline = time.time() + 5
        while not pid_file.exists():
            if time.time() > deadline:
                self.fail("the lock holder did not start")
            time.sleep(0.05)

    def _plan(self) -> subprocess.CompletedProcess[str]:
        return self._run_main(
            self.second,
            "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(),
            "--chat-db", self.db.as_posix(),
        )

    def test_a_second_apply_stops_while_an_apply_holds_the_lock(self) -> None:
        self._hold_lock()
        head = self._head()
        result = self._run_main(
            self.second, "--apply",
            "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(),
            "--chat-db", self.db.as_posix(),
        )
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, out)
        self.assertIn("COM2_DEPLOY_REASON=DEPLOY_IN_PROGRESS", out)
        self.assertNotIn("COM2_DEPLOY_SUMMARY=", out)
        self.assertEqual(self._head(), head, out)
        self.assertEqual(self._calls(), [], out)

    def test_a_plan_stops_while_an_apply_holds_the_lock(self) -> None:
        # 11-07 05:34: the plan ran after the other apply had already moved HEAD
        # and reported chat:SKIP. It must stop instead of planning on that HEAD.
        self._hold_lock()
        head = self._head()
        result = self._plan()
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, out)
        self.assertIn("COM2_DEPLOY_REASON=DEPLOY_IN_PROGRESS", out)
        self.assertNotIn("COM2_DEPLOY_SUMMARY=", out)
        self.assertEqual(self._head(), head, out)

    def test_stage_only_stops_while_an_apply_holds_the_lock(self) -> None:
        self._hold_lock()
        stage = self._stage_dir()
        result = self._run_main(
            self.second, "--stage-only",
            "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(),
            "--chat-db", self.db.as_posix(),
        )
        out = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, out)
        self.assertIn("COM2_DEPLOY_REASON=DEPLOY_IN_PROGRESS", out)
        self.assertFalse((stage / self.second).exists(), out)

    def test_a_finished_plan_releases_the_lock(self) -> None:
        first = self._plan()
        out = first.stdout + first.stderr
        self.assertEqual(first.returncode, 0, out)
        second = self._plan()
        out = second.stdout + second.stderr
        self.assertEqual(second.returncode, 0, out)
        self.assertNotIn("DEPLOY_IN_PROGRESS", out)


class ChatScenarioTest(DeployHarness):
    scenario = "chat"

    def test_a_chat_only_release_never_installs_the_queue_backup_kit(self) -> None:
        # The kit belongs to the queue leg; a chat release leaves it untouched.
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            [line for line in self._calls() if line.startswith("install mesh-queue-backup")],
            [],
            self._calls(),
        )

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
            "COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY p01:SKIP b14:SKIP queue:SKIP executor:SKIP",
            result.stdout,
        )
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])

    def test_apply_moves_the_checkout_and_installs_only_the_changed_service(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:PASS p01:SKIP b14:SKIP queue:SKIP executor:SKIP", result.stdout
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
                preexec_fn=drop, capture_output=True, text=True, encoding="utf-8",
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

    def test_the_qa_smoke_env_file_feeds_the_required_gate(self) -> None:
        # A systemd-run deploy inherits nothing interactive, so the QA pair
        # reaches the AI gate only through the sourced root-only env file
        # (provision_qa_smoke_account.ps1 writes it on the host).
        self.env["FAKE_AI_MODE"] = "required"
        self.env.pop("B66_CGI_ALPHA_USERNAME", None)
        self.env.pop("B66_CGI_ALPHA_PASSWORD", None)
        qa_env = self.tmp / "qa-smoke.env"
        # Composed from fragments like the release AI-check test: a literal
        # `<key>='<value>'` line reads as a credential assignment to secret
        # scanners even though both halves are meaningless markers.
        login_field = "B66_CGI_ALPHA_" + "USERNAME"
        secret_field = "B66_CGI_ALPHA_" + "PASSWORD"
        qa_env.write_text(
            login_field + "='fixture-login'\n"
            + secret_field + "='fixture-value'\n",
            encoding="utf-8",
        )
        self.env["PADIEM_COM2_QA_SMOKE_ENV"] = qa_env.as_posix()
        result = self._run_apply()
        self.assertNotIn(
            "AI_CHECK_REQUIRED_CREDENTIALS_MISSING", result.stderr, result.stderr[:2000]
        )
        self.assertIn("ai:PASS", result.stdout)

    def test_ai_pass_has_no_error_code(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:PASS", result.stdout)

    def test_ai_credential_missing_warn_reports_skip_not_fail(self) -> None:
        # The QA identity the check signs in with lives in GitHub's grade-smoke
        # environment, never on COM2, so a warn run routinely measures nothing.
        # 11-03: that ended APPLY_EXIT=0 while the line said ai:FAIL, which reads
        # as a broken answer lane. An unattempted check says SKIP with its reason.
        self.env["FAKE_AI_CODE"] = "qa_credential_missing"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:SKIP reason=qa_credential_missing", result.stdout)
        self.assertNotIn("ai:FAIL", result.stdout)
        self.assertEqual(len([x for x in self._calls() if x.startswith("install chat")]), 1)

    def test_ai_refused_origin_warn_reports_skip(self) -> None:
        # Same class: the canary declines before sending, so nothing was measured.
        self.env["FAKE_AI_CODE"] = "invalid_chat_origin"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:SKIP reason=invalid_chat_origin", result.stdout)

    def test_ai_credential_missing_required_still_fails_and_rolls_back(self) -> None:
        # --ai-check=required asks for the guarantee, so an unattempted check is
        # a failed deploy: exit 1 and the services go back.
        self.env["FAKE_AI_CODE"] = "qa_credential_missing"
        self.env["FAKE_AI_MODE"] = "required"
        self.env["B66_CGI_ALPHA_USERNAME"] = "qa-fixture"
        self.env["B66_CGI_ALPHA_PASSWORD"] = "qa-fixture"
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ai:FAIL error_code=qa_credential_missing", result.stdout)
        self.assertIn("chat:ROLLBACK", result.stdout)

    def test_ai_unattempted_but_broken_check_stays_fail(self) -> None:
        # A check that ran and could not produce a verdict is a broken check,
        # not a missing capability, so warn must not launder it into SKIP.
        self.env["FAKE_AI_CODE"] = "ai_check_unavailable"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ai:FAIL error_code=ai_check_unavailable", result.stdout)
        self.assertNotIn("ai:SKIP", result.stdout)

    def test_a_failed_health_check_rolls_the_service_back(self) -> None:
        # The new release never becomes healthy inside the deadline, so the
        # run rolls back; the rollback start is the second start of the unit,
        # which clears the broken-release marker in the fake.
        self._fail_service("chat", 999)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:ROLLBACK p01:SKIP b14:SKIP queue:SKIP executor:SKIP", result.stdout
        )
        installs = [line for line in self._calls() if line.startswith("install chat")]
        self.assertEqual(len(installs), 2, installs)
        self.assertIn((self.previous / self.first).as_posix(), installs[1])
        self.assertIn("systemctl start padiem-chat-com2.service", self._calls())

    def test_rollback_stops_a_unit_waiting_for_an_automatic_restart(self) -> None:
        # 11-07 05:38: the failed unit sat in its Restart=always window, where
        # is-active is false. Stopping only an active unit left that restart
        # pending, and it started the new release while the installer swapped
        # links one at a time; the old app then reached for
        # app.identity_cache_metrics and the rollback failed too.
        (self.fakes / "crashed_padiem-chat-com2.service").write_text("1\n", encoding="utf-8")
        self._fail_service("chat", 999)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        calls = self._calls()
        installs = [i for i, call in enumerate(calls) if call.startswith("install chat")]
        stops = [i for i, call in enumerate(calls) if call == "systemctl stop padiem-chat-com2.service"]
        starts = [i for i, call in enumerate(calls) if call == "systemctl start padiem-chat-com2.service"]
        self.assertEqual(len(installs), 2, calls)
        self.assertEqual(len(stops), 2, calls)
        self.assertLess(stops[-1], installs[1], calls)
        self.assertLess(installs[1], starts[-1], calls)

    def test_forward_deploy_stops_a_unit_waiting_for_an_automatic_restart(self) -> None:
        # The same window on the forward path: the unit is in its Restart=always
        # wait (is-active false), so a stop that only looks at is-active leaves
        # the pending start alive while the installer replaces the code.
        (self.fakes / "state_padiem-chat-com2.service").write_text("0\n", encoding="utf-8")
        (self.fakes / "restarting_padiem-chat-com2.service").write_text("1\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self._calls()
        stop = calls.index("systemctl stop padiem-chat-com2.service")
        install = next(i for i, call in enumerate(calls) if call.startswith("install chat"))
        starts = [i for i, call in enumerate(calls) if call == "systemctl start padiem-chat-com2.service"]
        self.assertLess(stop, install, calls)
        self.assertEqual(len(starts), 1, calls)
        self.assertLess(install, starts[0], calls)

    def test_an_inactive_unit_is_stopped_but_not_started_by_the_deploy(self) -> None:
        # The apply flow starts an enabled-but-stopped unit before any deploy, so
        # this calls the deploy itself. A loaded unit still gets the stop; the
        # decision to start follows what the unit was before the work.
        (self.fakes / "state_padiem-chat-com2.service").write_text("0\n", encoding="utf-8")
        env = {
            **self.env,
            "OPS_CHECKOUT": self.ops.as_posix(),
            "SYSTEMCTL_BIN": self.systemctl.as_posix(),
            "PYTHON_BIN": Path(sys.executable).as_posix(),
            "PADIEM_COM2_READ_CHECK_USER": getpass.getuser(),
        }
        result = subprocess.run(
            [BASH_BIN, "-c", DEPLOY_CHAT_WRAPPER, "bash",
             (self.ops / "deploy/host-com2/deploy_from_main.sh").as_posix()],
            capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_CHAT_START=SKIPPED_NOT_ACTIVE_BEFORE", result.stdout)
        calls = self._calls()
        self.assertIn("systemctl stop padiem-chat-com2.service", calls)
        self.assertNotIn("systemctl start padiem-chat-com2.service", calls)

    def test_slow_chat_start_is_retried_without_rollback(self) -> None:
        (self.fakes / "fail_once_chat").write_text("2", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("HEALTH=FAIL STATUS=0"), 2)
        self.assertEqual(result.stdout.count("COM2_DEPLOY_HEALTH_CHAT_ATTEMPTS="), 1)
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:PASS", result.stdout)
        self.assertEqual(len([c for c in self._calls() if c.startswith("install chat")]), 1)

    def test_previous_checkout_is_readable_not_writable_by_service_user(self) -> None:
        import stat
        self._fail_service("chat", 999)
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
                preexec_fn=drop_privileges, capture_output=True, text=True, encoding="utf-8",
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

    def test_a_plan_reports_each_unit_state(self) -> None:
        # A unit in its Restart=always wait is `activating` in systemd even
        # though is-active already says false; the plan names the difference
        # without letting it change any decision.
        self.env["PADIEM_COM2_SYSTEMCTL"] = self.systemctl.as_posix()
        (self.fakes / "state_padiem-chat-com2.service").write_text("0\n", encoding="utf-8")
        (self.fakes / "restarting_padiem-chat-com2.service").write_text("1\n", encoding="utf-8")
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for service in ("CHAT", "P01", "B14", "QUEUE", "EXECUTOR"):
            self.assertIn(f"COM2_DEPLOY_UNIT_STATE_{service}=", result.stdout)
        self.assertIn("COM2_DEPLOY_UNIT_STATE_CHAT=activating", result.stdout)
        self.assertIn("COM2_DEPLOY_UNIT_STATE_P01=active", result.stdout)


class MigrationScenarioTest(DeployHarness):
    scenario = "migration"

    def test_a_pending_migration_selects_chat_and_requires_migration_first(self) -> None:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 3, output)
        self.assertIn(
            "COM2_DEPLOY_DECISION_CHAT=REDEPLOY reason_files=1 reason=CHANGED_PATHS",
            output,
        )
        self.assertIn("COM2_DEPLOY_MIGRATION_FIRST=YES", output)
        self.assertIn("COM2_DEPLOY_REASON=MIGRATION_FIRST", output)

    def test_a_new_migration_is_applied_after_a_backup_then_the_run_continues(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_CHAT_MIGRATION_APPLIED=002_new_owner.sql", result.stdout)
        self.assertNotIn("COM2_DEPLOY_MIGRATION_FIRST=YES", result.stderr)
        backups = sorted(self.db.parent.glob(self.db.name + ".pre-deploy-*"))
        self.assertEqual(len(backups), 1, backups)

        def ledger_names(path: Path) -> set[str]:
            con = sqlite3.connect("file:%s?mode=ro" % path.as_posix(), uri=True)
            try:
                return {row[0] for row in con.execute(
                    "SELECT name FROM padiem_local_migration_ledger")}
            finally:
                con.close()

        self.assertNotIn("002_new_owner.sql", ledger_names(backups[0]))
        self.assertIn("002_new_owner.sql", ledger_names(self.db))
        self.assertIn("systemctl is-enabled", self.log.read_text(encoding="utf-8"))


class DeployScopeScenarioTest(DeployHarness):
    """Test files and docs do not select services; runtime inputs still do."""

    scenario = "tests_only"

    def setUp(self) -> None:
        scenarios = {
            "test_code_plus_test_redeploys_and_counts_only_code": "code_and_test",
            "test_documentation_only_skips": "docs_only",
            "test_documentation_only_apply_keeps_the_checkout_where_it_is": "docs_only",
            "test_runtime_config_lock_requirements_and_units_select_services": "runtime_config",
            "test_a_common_systemd_policy_change_selects_all_services": "common_unit_policy",
            "test_a_shared_core_change_selects_chat_and_p01": "shared_runtime",
            "test_a8eff99_to_a1fdec4_actual_test_path_manifest_skips_queue_p01_b14": "historical_test_paths",
        }
        self.scenario = scenarios.get(self._testMethodName, "tests_only")
        super().setUp()

    def _dry_run(self) -> str:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def test_test_config_example_docs_and_repo_metadata_only_skip(self) -> None:
        output = self._dry_run()
        self.assertIn(
            "COM2_DEPLOY_EXCLUDED_COUNTS=tests:8 docs:1 env_example:1 repo_meta:2 unmapped:0",
            output,
        )
        for service in ("CHAT", "P01", "B14", "QUEUE"):
            self.assertIn(
                f"COM2_DEPLOY_DECISION_{service}=SKIP reason_files=0 reason=NO_DEPLOY_PATHS",
                output,
            )
        self.assertIn("COM2_DEPLOY_NO_SERVICE_CHANGES=YES", output)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP",
            output,
        )

    def test_code_plus_test_redeploys_and_counts_only_code(self) -> None:
        output = self._dry_run()
        self.assertIn(
            "COM2_DEPLOY_DECISION_CHAT=REDEPLOY reason_files=1 reason=CHANGED_PATHS",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_EXCLUDED_COUNTS=tests:1 docs:0 env_example:0 repo_meta:0 unmapped:0",
            output,
        )
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY", output)

    def test_documentation_only_skips(self) -> None:
        output = self._dry_run()
        self.assertIn("COM2_DEPLOY_EXCLUDED_COUNTS=tests:0 docs:2", output)
        self.assertIn("COM2_DEPLOY_DECISION_CHAT=SKIP reason_files=0", output)
        self.assertIn("COM2_DEPLOY_NO_SERVICE_CHANGES=YES", output)

    def test_documentation_only_apply_keeps_the_checkout_where_it_is(self) -> None:
        result = self._run_apply()
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("COM2_DEPLOY_NO_SERVICE_CHANGES=YES", output)
        self.assertNotIn("CHECKOUT_ONLY", output)
        self.assertEqual(self._head(), self.first)
        self.assertEqual(self._calls(), [])

    def test_runtime_config_lock_requirements_and_units_select_services(self) -> None:
        output = self._dry_run()
        for service, count in (("CHAT", 2), ("P01", 1), ("B14", 1), ("QUEUE", 1)):
            self.assertIn(
                f"COM2_DEPLOY_DECISION_{service}=REDEPLOY reason_files={count}",
                output,
            )
        self.assertIn("COM2_DEPLOY_EXCLUDED_COUNTS=tests:0 docs:0 env_example:1", output)

    def test_a_common_systemd_policy_change_selects_all_services(self) -> None:
        output = self._dry_run()
        for service in ("CHAT", "P01", "B14", "QUEUE"):
            self.assertIn(
                f"COM2_DEPLOY_DECISION_{service}=REDEPLOY reason_files=1",
                output,
            )

    def test_a_shared_core_change_selects_chat_and_p01(self) -> None:
        output = self._dry_run()
        self.assertIn(
            "COM2_DEPLOY_DECISION_CHAT=REDEPLOY reason_files=1 reason=CHANGED_PATHS",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_DECISION_P01=REDEPLOY reason_files=1 reason=CHANGED_PATHS+RUNNING_CODE_MISMATCH",
            output,
        )

    def test_a8eff99_to_a1fdec4_actual_test_path_manifest_skips_queue_p01_b14(self) -> None:
        output = self._dry_run()
        self.assertIn(
            "COM2_DEPLOY_EXCLUDED_COUNTS=tests:14 docs:0 env_example:1 repo_meta:2 unmapped:0",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_DECISION_CHAT=REDEPLOY reason_files=1 reason=CHANGED_PATHS",
            output,
        )
        for service in ("P01", "B14", "QUEUE"):
            self.assertIn(
                f"COM2_DEPLOY_DECISION_{service}=SKIP reason_files=0",
                output,
            )


class CheckoutOnlyScenarioTest(DeployHarness):
    """A change to the deploy script alone still has to reach the production checkout."""

    scenario = "deploy_script_only"

    def _dry_run(self) -> str:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def test_a_script_only_apply_moves_the_checkout_and_touches_no_service(self) -> None:
        result = self._run_apply()
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn(
            "COM2_DEPLOY_CHANGED=deploy/host-com2/deploy_from_main.sh", output
        )
        self.assertIn(
            "COM2_DEPLOY_CHECKOUT_ONLY=YES reason=DEPLOY_SCRIPT_CHANGED", output
        )
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:SKIP executor:SKIP",
            output,
        )
        self.assertEqual(self._head(), self.second)
        # The rollback snapshot is what the next plan reads the old commit from.
        self.assertIn(
            f"COM2_DEPLOY_PREVIOUS_CHECKOUT={self.previous.as_posix()}/{self.first}",
            output,
        )
        self.assertTrue((self.previous / self.first).is_dir())
        self.assertEqual(
            [
                call for call in self._calls()
                if call.startswith(("systemctl start", "systemctl stop", "install "))
            ],
            [],
        )

    def test_a_script_only_plan_reports_the_checkout_would_move(self) -> None:
        output = self._dry_run()
        self.assertIn(
            "COM2_DEPLOY_CHECKOUT_ONLY=WOULD reason=DEPLOY_SCRIPT_CHANGED", output
        )
        self.assertIn(
            "적용하면 체크아웃만 새 SHA로 넘어가고, 다음 계획부터 새 스크립트가 쓰입니다.", output
        )
        self.assertIn("COM2_DEPLOY_NO_SERVICE_CHANGES=YES", output)
        self.assertEqual(self._head(), self.first)


class P01ScenarioTest(DeployHarness):
    scenario = "p01"

    def test_p01_rolls_back_to_the_previous_release_snapshot(self) -> None:
        self._install_fails("p01")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:ROLLBACK b14:SKIP queue:SKIP executor:SKIP", result.stdout
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
        # The old release is healthy by construction, so the rollback start
        # (the second start of the unit) passes the same contract.
        self.assertIn("p01:ROLLBACK", result.stdout)
        self.assertIn("COM2_DEPLOY_HEALTH_P01_ROLLBACK_ATTEMPTS=", result.stdout)
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

    def setUp(self) -> None:
        super().setUp()
        # A hand copy this script cannot prove: the first apply displaces it.
        self.b14.mkdir()

    def test_b14_runs_from_the_mirror_and_keeps_the_operator_copy(self) -> None:
        (self.b14 / "operator-marker").write_text("hand staged\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:PASS queue:SKIP executor:SKIP", result.stdout
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
        # A rollback target that cannot be imported is not a rollback.
        self.assertTrue((self.b14.resolve() / "padiem_ai_core" / "pc_work_metrics.py").is_file())
        self.assertIn("B14_SHARED_MODULE=", result.stdout)
        # The registry loader is part of the tree the unit boots from.
        self.assertTrue((self.b14.resolve() / "padiem_control_plane" / "models_registry.py").is_file())
        self.assertIn("B14_CONTROL_PLANE=", result.stdout)
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


class StartupLadderTest(DeployHarness):
    """#6460 후속 — 11-02 B14 롤백의 재발 방지 계약.

    배포 전환 때 B14는 "unreachable:URLError 2회 → 30초 만료 → 자동 롤백"이었고,
    같은 트리를 단독 기동하면 1.0초 만에 200이었다. 수동 기록: attempt 1
    listen=0 → attempt 2 listen=1 health=200. 즉 앱이 아니라 순서의 문제였다:
    재시작 직후 포트가 열리기 전에 프로브가 돌았다. 이 클래스는 그 순서를
    고정한다 — 유닛 active → 포트 리슨 → 헬스 계약, 그리고 재시작 전
    이전 프로세스의 완전한 종료 확인.
    """

    scenario = "b14"

    def test_a_slow_bind_reads_as_a_slow_start_then_passes(self) -> None:
        # The manual 11-02 record: attempt 1 listen=0, attempt 2 listen=1,
        # health=200. Seven polls of not-listening still end in a PASS: the
        # port stage waits, the health contract is only probed after the bind.
        (self.fakes / "ss_delay_8789").write_text("7", encoding="utf-8")
        self.env["PADIEM_COM2_WAIT_POLL_INTERVAL"] = "0.5"
        self.env["PADIEM_COM2_PORT_WAIT_TIMEOUT"] = "10"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_UNIT_B14_ACTIVE", result.stdout)
        self.assertIn("COM2_DEPLOY_PORT_B14_LISTENING", result.stdout)
        self.assertIn("b14:PASS", result.stdout)
        polls = int((self.fakes / "calls_ss_delay_8789").read_text().strip())
        self.assertGreaterEqual(polls, 7)
        # The ladder order is the whole fix: active, then listening, then health.
        self.assertLess(
            result.stdout.index("COM2_DEPLOY_UNIT_B14_ACTIVE"),
            result.stdout.index("COM2_DEPLOY_PORT_B14_LISTENING"),
        )
        self.assertLess(
            result.stdout.index("COM2_DEPLOY_PORT_B14_LISTENING"),
            result.stdout.index("COM2_DEPLOY_HEALTH_B14_ATTEMPTS="),
        )

    def test_a_port_that_never_opens_rolls_back(self) -> None:
        (self.fakes / "ss_hide_8789").write_text("1", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_PORT_B14_LISTENING_TIMEOUT", result.stdout)
        self.assertIn("b14:ROLLBACK", result.stdout)
        # The rollback start (the second start of the unit) clears the broken
        # release, and the previous release binds the watched port again — the
        # rollback itself is verified healthy. A b14 rollback re-points the
        # link, so there is exactly one install.
        self.assertIn("COM2_DEPLOY_HEALTH_B14_ROLLBACK_ATTEMPTS=", result.stdout)
        self.assertIn("COM2_DEPLOY_UNIT_B14_ROLLBACK_ACTIVE", result.stdout)
        self.assertIn("COM2_DEPLOY_PORT_B14_ROLLBACK_LISTENING", result.stdout)
        installs = [line for line in self._calls() if line.startswith("install b14")]
        self.assertEqual(len(installs), 1, installs)

    def test_health_that_never_passes_rolls_back(self) -> None:
        self._fail_service("b14", 999)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_B14_ATTEMPTS=", result.stdout)
        self.assertIn("b14:ROLLBACK", result.stdout)
        self.assertIn("COM2_DEPLOY_HEALTH_B14_ROLLBACK_ATTEMPTS=", result.stdout)

    def test_start_waits_for_the_previous_mainpid_to_release(self) -> None:
        # A wedged MainPID (Restart=always churn) must be caught before the new
        # process is started: the ladder refuses and says which stage failed.
        (self.fakes / "mainpid_padiem-b14.service").write_text("12345\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("COM2_DEPLOY_MAINPID_B14_GONE_TIMEOUT", result.stdout)
        self.assertIn("b14:ROLLBACK_FAILED", result.stdout)
        # The start that never happened is not in the log at all.
        self.assertEqual(self._started("padiem-b14.service"), 0, self._calls())

    def test_the_down_check_passes_when_the_previous_process_is_already_gone(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_MAINPID_B14_GONE", result.stdout)
        self.assertIn("COM2_DEPLOY_PORT_B14_RELEASED", result.stdout)
        self.assertIn("b14:PASS", result.stdout)


class MeshQueueScenarioTest(DeployHarness):
    scenario = "queue"

    def test_queue_deploy_refreshes_installed_health_check(self) -> None:
        installed = self.queue / "health_check.sh"
        installed.write_text("#!/usr/bin/env bash\necho stale\n", encoding="utf-8")
        installed.chmod(0o755)

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stderr)
        source = self._stage() / "apps/padiem-mesh-queue/deploy/health_check.sh"
        self.assertEqual(installed.read_bytes(), source.read_bytes())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o755)

    def test_queue_code_is_staged_from_the_mirror_and_restarts(self) -> None:
        (self.queue / "queue.env").write_text("MESH_QUEUE_DB_PATH=/keep\n", encoding="utf-8")
        (self.queue / "queue.sqlite3").write_text("data", encoding="utf-8")
        (self.queue / "src").mkdir()
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_SERVICES=queue", result.stdout)
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:SKIP queue:PASS executor:SKIP", result.stdout
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

    def test_the_queue_leg_installs_the_backup_kit(self) -> None:
        # #6898's kit is preview-only by default; the deploy is the one place that
        # passes --apply, so a queue release leaves the host's backup script and
        # its timer matching the code it just staged.
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        backups = [line for line in self._calls() if line.startswith("install mesh-queue-backup")]
        self.assertEqual(backups, ["install mesh-queue-backup --apply"], self._calls())
        # The kit installs units only: nothing in it starts or enables them.
        self.assertNotIn("enable", " ".join(self._calls()).replace("is-enabled", ""))

    def test_a_slow_queue_start_is_not_reported_as_a_broken_release(self) -> None:
        self._fail_health_once("queue")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_QUEUE_ATTEMPTS=2", result.stdout)
        self.assertIn("queue:PASS", result.stdout)

    def test_queue_ok_marker_with_exit_zero_passes(self) -> None:
        (self.fakes / "queue_health_output").write_text(
            "MESH_QUEUE_HEALTH=OK pending_unclaimed=0 pending_claimed=0 received=0\n",
            encoding="utf-8",
        )
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("queue:PASS", result.stdout)
        self.assertEqual(self._started("padiem-mesh-queue.service"), 1, self._calls())

    def test_non_ok_marker_with_exit_zero_enters_queue_rollback(self) -> None:
        (self.fakes / "queue_health_output").write_text(
            "MESH_QUEUE_HEALTH=UNREACHABLE curl=7\n", encoding="utf-8"
        )
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("queue:ROLLBACK", result.stdout)
        self.assertEqual(self._started("padiem-mesh-queue.service"), 2, self._calls())
        self.assertEqual((self.queue / "service.py").read_text(encoding="utf-8"), "# queue\n")

    def test_a_broken_queue_rolls_its_code_back_and_stays_started(self) -> None:
        self._fail_service("queue", 20)
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("queue:ROLLBACK_FAILED", result.stdout)
        self.assertEqual(
            (self.queue / "service.py").read_text(encoding="utf-8"), "# queue\n"
        )
        self.assertEqual(self._started("padiem-mesh-queue.service"), 2, self._calls())



CHANGES["queue_imported_chat"] = (
    # #6794's pairing store: changed for the queue, mapped only to chat.
    "apps/padiem-chat/app/pc_device_pairing_store.py",
    "PAIRING_TAG = 2\n",
)


QUEUE_INSTALLED = {
    "padiem-mesh-queue.service": "[Service]\nExecStart=/opt/padiem/mesh-queue/venv/bin/python service.py\n",
    "padiem-mesh-queue-health.service": "[Service]\nExecStart=/opt/padiem/mesh-queue/health_check.sh\n",
    "padiem-mesh-queue-health.timer": "[Timer]\nOnUnitActiveSec=5min\n",
    "provision_service_secret.sh": "#!/usr/bin/env bash\necho provision\n",
}


class QueueInstallerSyncTest(DeployHarness):
    """The files the queue's installer installs follow the deployed commit.

    deploy_from_main.sh's queue leg mirrored code only, so the main unit, the
    health unit and timer, and provision_service_secret.sh stayed at whatever the
    last hand run of apps/padiem-mesh-queue/deploy/install.sh wrote (#6892
    follow-up). Only a differing file is replaced, the copy it replaces is kept
    as .bak-<sha>, and only a changed unit reloads systemd.
    """

    scenario = "queue"
    base_extra = {
        f"apps/padiem-mesh-queue/deploy/{name}": text
        for name, text in QUEUE_INSTALLED.items()
    }

    def _install_stale(self) -> None:
        for name in QUEUE_INSTALLED:
            # install.sh puts the units in the unit directory and the
            # provisioner at the queue root.
            target = self._installed(name)
            target.write_text(f"# stale {name}\n", encoding="utf-8")
            target.chmod(0o604 if name.endswith(".sh") else 0o644)
        (self.queue / "queue.env").write_text("MESH_QUEUE_DB_PATH=/keep\n", encoding="utf-8")
        (self.queue / "service-secret.txt").write_text("keep-secret\n", encoding="utf-8")

    def _installed(self, name: str) -> Path:
        return self.units / name if not name.endswith(".sh") else self.queue / name

    def _source(self, name: str) -> Path:
        # The checkout carries these from the base commit; the run mirrors the
        # same bytes into the channel staging directory.
        return self.ops / "apps/padiem-mesh-queue/deploy" / name

    def test_identical_installed_files_are_not_touched(self) -> None:
        for name in QUEUE_INSTALLED:
            target = self.units / name
            target.write_bytes(self._source(name).read_bytes())
            target.chmod(0o640)
        (self.queue / "provision_service_secret.sh").write_bytes(
            self._source("provision_service_secret.sh").read_bytes()
        )

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_QUEUE_UNITS=SAME", result.stdout)
        self.assertNotIn("systemctl daemon-reload", self._calls())
        self.assertEqual(list(self.units.glob("*.bak-*")), [])
        self.assertEqual(
            (self.units / "padiem-mesh-queue.service").stat().st_mode & 0o777, 0o640
        )

    def test_a_changed_file_is_backed_up_and_copied(self) -> None:
        self._install_stale()
        sh_mode = self._installed("provision_service_secret.sh").stat().st_mode & 0o777

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "COM2_DEPLOY_QUEUE_UNITS=UPDATED:padiem-mesh-queue.service,"
            "padiem-mesh-queue-health.service,padiem-mesh-queue-health.timer,"
            "provision_service_secret.sh",
            result.stdout,
        )
        for name in QUEUE_INSTALLED:
            target = self._installed(name)
            self.assertEqual(target.read_bytes(), self._source(name).read_bytes(), name)
            backup = target.with_name(target.name + ".bak-" + self.second)
            self.assertEqual(backup.read_text(encoding="utf-8"), f"# stale {name}\n", name)
        # The installed mode and owner are the host's, not the mirror's.
        self.assertEqual(
            (self.units / "padiem-mesh-queue.service").stat().st_mode & 0o777, 0o644
        )
        self.assertEqual(
            self._installed("provision_service_secret.sh").stat().st_mode & 0o777, sh_mode
        )
        # A changed unit needs exactly one reload; the queue's state is untouched.
        self.assertEqual(self._calls().count("systemctl daemon-reload"), 1, self._calls())
        self.assertEqual(
            (self.queue / "queue.env").read_text(encoding="utf-8"), "MESH_QUEUE_DB_PATH=/keep\n"
        )
        self.assertEqual(
            (self.queue / "service-secret.txt").read_text(encoding="utf-8"), "keep-secret\n"
        )

    def test_a_rollback_puts_the_installed_files_back(self) -> None:
        self._install_stale()
        (self.fakes / "queue_health_output").write_text(
            "MESH_QUEUE_HEALTH=UNREACHABLE curl=7\n", encoding="utf-8"
        )

        result = self._run_apply()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("queue:ROLLBACK", result.stdout)
        self.assertIn("COM2_DEPLOY_QUEUE_UNITS_ROLLBACK=RESTORED:4", result.stdout)
        for name in QUEUE_INSTALLED:
            target = self._installed(name)
            self.assertEqual(target.read_text(encoding="utf-8"), f"# stale {name}\n", name)
        # Forward and back: a unit changed both times.
        self.assertEqual(self._calls().count("systemctl daemon-reload"), 2, self._calls())
        self.assertEqual((self.queue / "service.py").read_text(encoding="utf-8"), "# queue\n")


class QueueImportedModuleScenarioTest(DeployHarness):
    """A Chat module the queue imports is queue code (#6892).

    stage_queue_code links apps/padiem-chat/app, packages/padiem-ai-core and
    packages/padiem-control-plane into the queue root, so the queue process runs
    those modules. #6794 changed them and two days of deploys still printed
    queue:SKIP, because service_for_path names only chat for those paths.
    """

    scenario = "queue_imported_chat"
    base_extra = {
        # The chain production has: a queue module imports the Chat routes
        # module, which imports the pairing store #6794 changed.
        "apps/padiem-mesh-queue/queue_chat_link.py": (
            "from app.oracle_mesh_read_return_routes import PAIRING_TAG\n"
        ),
        "apps/padiem-chat/app/oracle_mesh_read_return_routes.py": (
            "from app.pc_device_pairing_store import PAIRING_TAG\n"
        ),
        "apps/padiem-chat/app/pc_device_pairing_store.py": "PAIRING_TAG = 1\n",
        # Nothing imports this one, so a change here is chat's alone.
        "apps/padiem-chat/app/unrelated_chat_module.py": "UNRELATED = 1\n",
    }

    def _dry_run(self, sha: str) -> str:
        result = self._run_main(
            sha, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def test_the_store_6794_changed_selects_the_queue(self) -> None:
        output = self._dry_run(self.second)
        self.assertIn(
            "COM2_DEPLOY_QUEUE_IMPORTED=apps/padiem-chat/app/pc_device_pairing_store.py",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_DECISION_QUEUE=REDEPLOY reason_files=1 reason=CHANGED_PATHS",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY p01:SKIP b14:SKIP queue:WOULD_DEPLOY executor:SKIP",
            output,
        )

    def test_a_chat_module_the_queue_never_imports_keeps_the_queue_skipped(self) -> None:
        # On top of the deployed commit, so the push is a fast-forward.
        self._git(str(self.ops), "checkout", "-q", self.second)
        self._write("apps/padiem-chat/app/unrelated_chat_module.py", "UNRELATED = 2\n")
        sha = self._commit("unrelated chat change")
        self._git(str(self.ops), "push", "-q", "origin", "HEAD:main")
        # Back to the deployed commit: the run compares origin/main to HEAD.
        self._git(str(self.ops), "checkout", "-q", self.second)
        output = self._dry_run(sha)
        self.assertIn("COM2_DEPLOY_DECISION_CHAT=REDEPLOY", output)
        self.assertIn("COM2_DEPLOY_DECISION_QUEUE=SKIP reason_files=0", output)


CHANGES["executor"] = (
    "apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py",
    "import padiem_ai_core\n\n# executor 2\n",
)


class OracleMeshExecutorScenarioTest(DeployHarness):
    """The executor is a deployment target (#6892 follow-up).

    It ran from /opt/padiem/oracle-mesh/kagent-src, a hand copy of 11-01 that no
    deploy updated, so a kagent fix merged to main never reached the process that
    does the PC reads. The tree is a commit directory with the unit's PYTHONPATH
    path pointing at it now, and a change to kagent or to a module kagent imports
    selects it whether or not service_for_path names that path.
    """

    scenario = "executor"
    base_extra = {
        "apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py": (
            "import padiem_ai_core\n\n# executor\n"
        ),
        # The unit source this repository carries for the executor (#6892
        # follow-up ②); the host had the only copy before it.
        "deploy/host-com2/oracle-mesh/padiem-oracle-mesh-executor.service.example": (
            (REPO / "deploy/host-com2/oracle-mesh/"
             "padiem-oracle-mesh-executor.service.example").read_text(encoding="utf-8")
        ),
    }

    def setUp(self) -> None:
        super().setUp()
        # The tree the unit runs today: a hand copy, with the one module this
        # repository does not track.
        self.oracle = self.tmp / "oracle-mesh"
        self.live = self.oracle / "kagent-src"
        (self.live / "padiem_agent").mkdir(parents=True)
        (self.live / "padiem_agent" / "marker.py").write_text(
            "AGENT = 1\n", encoding="utf-8"
        )
        # The plan reads the same tree the apply wrapper points the script at.
        self.env["PADIEM_COM2_ORACLE_MESH_ROOT"] = self.oracle.as_posix()

    def _dry(self) -> str:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def _release(self) -> Path:
        return self.oracle / "src" / self.second

    def test_a_kagent_change_selects_the_executor(self) -> None:
        output = self._dry()
        # The hand copy in setUp is not the recorded release directory, so the
        # running-code comparison selects the executor too.
        self.assertIn(
            "COM2_DEPLOY_DECISION_EXECUTOR=REDEPLOY reason_files=1 "
            "reason=CHANGED_PATHS+RUNNING_CODE_MISMATCH",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:WOULD_DEPLOY b14:SKIP queue:SKIP "
            "executor:WOULD_DEPLOY",
            output,
        )

    def test_a_module_the_executor_imports_selects_it_too(self) -> None:
        self._git(str(self.ops), "checkout", "-q", self.second)
        # The link is on the recorded release, so only the import list can
        # select the executor here.
        release = self.oracle / "src" / self.second
        release.parent.mkdir(parents=True, exist_ok=True)
        self.live.rename(release)
        self.live.symlink_to(release, target_is_directory=True)
        # The fixture executor imports the Core package itself, so the one
        # module both this repository and the import list carry is its __init__.
        self._write("packages/padiem-ai-core/padiem_ai_core/__init__.py", "# core 2\n")
        sha = self._commit("core package the executor imports")
        self._git(str(self.ops), "push", "-q", "origin", "HEAD:main")
        self._git(str(self.ops), "checkout", "-q", self.second)
        result = self._run_main(
            sha, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        # The executor imports the Core package, so its modules are its code:
        # the path maps to chat and p01, and the import list selects it too.
        self.assertIn("COM2_DEPLOY_EXECUTOR_RUNNING_CODE=MATCH", output)
        self.assertIn(
            "COM2_DEPLOY_EXECUTOR_IMPORTED=packages/padiem-ai-core/padiem_ai_core/__init__.py",
            output,
        )
        self.assertIn("COM2_DEPLOY_DECISION_EXECUTOR=REDEPLOY", output)

    def test_a_rolled_back_link_selects_the_executor_again(self) -> None:
        # 11-06 22:28: the deploy rolled the executor back to a displaced copy
        # and still moved the checkout to that commit, so the old..new diff was
        # empty and the executor was skipped while it ran the older code.
        self._git(str(self.ops), "checkout", "-q", self.second)
        displaced = self.oracle / "kagent-src.displaced-20261106T222917"
        self.live.rename(displaced)
        self.live.symlink_to(displaced, target_is_directory=True)

        output = self._dry()

        self.assertIn("COM2_DEPLOY_EXECUTOR_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", output)
        self.assertIn(
            "COM2_DEPLOY_DECISION_EXECUTOR=REDEPLOY reason_files=0 "
            "reason=RUNNING_CODE_MISMATCH",
            output,
        )
        self.assertIn(
            "COM2_DEPLOY_SUMMARY=chat:SKIP p01:WOULD_DEPLOY b14:SKIP queue:SKIP "
            "executor:WOULD_DEPLOY",
            output,
        )

    def test_a_link_on_the_recorded_release_is_skipped(self) -> None:
        self._git(str(self.ops), "checkout", "-q", self.second)
        release = self.oracle / "src" / self.second
        release.parent.mkdir(parents=True, exist_ok=True)
        self.live.rename(release)
        self.live.symlink_to(release, target_is_directory=True)

        output = self._dry()

        self.assertIn("COM2_DEPLOY_EXECUTOR_RUNNING_CODE=MATCH", output)
        self.assertIn("COM2_DEPLOY_DECISION_EXECUTOR=SKIP reason_files=0", output)

    def test_the_executor_runs_from_a_commit_directory(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        release = self._release()
        self.assertTrue((release / "kagent" / "local_agent_oracle_mesh_executor.py").is_file())
        self.assertTrue((release / "padiem_ai_core" / "__init__.py").is_file())
        # The module this repository does not track is carried forward.
        self.assertTrue((release / "padiem_agent" / "marker.py").is_file())
        self.assertEqual(self.live.resolve(), release.resolve())
        # The hand copy is displaced, never deleted: it is the rollback copy.
        displaced = list(self.oracle.glob("kagent-src.displaced-*"))
        self.assertEqual(len(displaced), 1, displaced)
        self.assertTrue((displaced[0] / "padiem_agent" / "marker.py").is_file())
        self.assertEqual(
            self._started("padiem-oracle-mesh-executor.service"), 1, self._calls()
        )
        self.assertIn("COM2_DEPLOY_EXECUTOR_TRACEBACKS=0", result.stdout)
        self.assertIn(
            "COM2_DEPLOY_DECISION_EXECUTOR=REDEPLOY reason_files=1", result.stdout
        )
        self.assertIn("executor:PASS", result.stdout)

    def test_active_executor_does_not_require_deployer_python_imports(self) -> None:
        # The service venv can supply dependencies absent from the deployer's
        # Python. The systemd fake represents an already running process.
        self._git(str(self.ops), "checkout", "-q", self.second)
        self._write(
            "apps/korean-ai-code-agent/src/kagent/local_agent_oracle_mesh_executor.py",
            "import dependency_only_in_executor_venv\n",
        )
        self.second = self._commit("executor venv dependency")
        self._git(str(self.ops), "push", "-q", "origin", "HEAD:main")
        self._git(str(self.ops), "checkout", "-q", "--detach", self.first)

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_EXECUTOR_ATTEMPTS=1", result.stdout)
        self.assertIn("executor:PASS", result.stdout)

    def test_executor_without_a_main_process_fails_health(self) -> None:
        (self.fakes / "mainpid_padiem-oracle-mesh-executor.service").write_text(
            "0\n", encoding="utf-8"
        )
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_HEALTH_EXECUTOR_ATTEMPTS=", result.stdout)
        self.assertIn("executor:ROLLBACK_FAILED", result.stdout)

    def _installed_unit(self) -> Path:
        return self.executor_units / "padiem-oracle-mesh-executor.service"

    def _install_unit(self) -> str:
        # The unit the host runs today: the measured directives, plus a host
        # setting this repository does not know (the drop-in's queue origin).
        text = (
            "[Service]\n"
            "User=padiem-mesh\n"
            "Restart=always\n"
            "Environment=ORACLE_MESH_QUEUE_ORIGIN=http://127.0.0.1:8797\n"
        )
        self._installed_unit().write_text(text, encoding="utf-8")
        self._installed_unit().chmod(0o640)
        return text

    def _example_text(self) -> str:
        return (self.ops / "deploy/host-com2/oracle-mesh/"
                "padiem-oracle-mesh-executor.service.example").read_text(encoding="utf-8")

    def test_a_differing_unit_is_reported_and_left_alone(self) -> None:
        installed = self._install_unit()

        result = self._run_apply()

        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        drift = next(
            line for line in result.stdout.splitlines() if "EXECUTOR_UNIT_DRIFT=" in line
        )
        keys = drift.split("YES:", 1)[1].split(",")
        # The unit has directives the repository's copy does not carry, and the
        # copy carries directives the host does not. An identical value is not
        # drift.
        self.assertIn("Environment", keys, drift)
        self.assertIn("ExecStart", keys, drift)
        self.assertNotIn("User", keys, drift)
        self.assertIn("COM2_DEPLOY_EXECUTOR_UNITS=CONFIRM_ONLY", result.stdout)
        self.assertEqual(self._installed_unit().read_text(encoding="utf-8"), installed)
        self.assertEqual(list(self.executor_units.glob("*.bak-*")), [])
        self.assertEqual(self._calls().count("systemctl daemon-reload"), 0)
        self.assertIn("executor:PASS", result.stdout)

    def test_the_sync_flag_copies_and_backs_up_the_unit(self) -> None:
        installed = self._install_unit()
        self.env = {**self.env, "PADIEM_COM2_EXECUTOR_UNIT_SYNC": "1"}

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "COM2_DEPLOY_EXECUTOR_UNITS=UPDATED:padiem-oracle-mesh-executor.service",
            result.stdout,
        )
        self.assertEqual(self._installed_unit().read_text(encoding="utf-8"),
                         self._example_text())
        backup = self._installed_unit().with_name(
            "padiem-oracle-mesh-executor.service.bak-" + self.second
        )
        self.assertEqual(backup.read_text(encoding="utf-8"), installed)
        # The installed mode is the host's, not the example's.
        self.assertEqual(self._installed_unit().stat().st_mode & 0o777, 0o640)
        self.assertEqual(self._calls().count("systemctl daemon-reload"), 1, self._calls())

    def test_a_rollback_puts_the_installed_unit_back(self) -> None:
        installed = self._install_unit()
        self.env = {**self.env, "PADIEM_COM2_EXECUTOR_UNIT_SYNC": "1"}
        (self.fakes / "journal_traceback").write_text("1\n", encoding="utf-8")

        result = self._run_apply()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("executor:ROLLBACK", result.stdout)
        self.assertIn(
            "COM2_DEPLOY_EXECUTOR_UNITS_ROLLBACK=RESTORED:padiem-oracle-mesh-executor.service",
            result.stdout,
        )
        self.assertEqual(self._installed_unit().read_text(encoding="utf-8"), installed)
        # Forward and back: the unit changed both times.
        self.assertEqual(self._calls().count("systemctl daemon-reload"), 2, self._calls())

    def test_a_traceback_after_start_puts_the_previous_copy_back(self) -> None:
        (self.fakes / "journal_traceback").write_text("1\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_EXECUTOR_TRACEBACKS=1", result.stdout)
        self.assertIn("executor:ROLLBACK", result.stdout)
        self.assertIn("COM2_DEPLOY_HEALTH_EXECUTOR_ROLLBACK_ATTEMPTS=", result.stdout)
        self.assertEqual(
            self.live.resolve(),
            list(self.oracle.glob("kagent-src.displaced-*"))[0].resolve(),
        )


class MigrationServiceUserGitTest(DeployHarness):
    """The pending-migration read belongs to the account that fetched the tree.

    11-03 the first COM2 redeploy failed twice on the same seam. First the
    database owner had no ``safe.directory`` for the production checkout; that
    was scoped away, and the run then still could not read the object store,
    because the script fetches under ``umask 077`` and the pack index it wrote
    was unreadable to the service user — git reported the migration file as
    missing. A permission the writer cannot have is not fixed by trusting it
    more, so the read moved out of the database leg entirely: the fetching
    account reads one file, and the database owner receives only its bytes.
    """

    scenario = "migration"

    def _git_logging_bin(self) -> Path:
        """A `git` that records its argv, then runs the real git."""
        directory = self.tmp / "git-bin"
        directory.mkdir()
        log = self.tmp / "git-argv.log"
        real = shutil.which("git") or "/usr/bin/git"
        wrapper = directory / "git"
        wrapper.write_text(
            "#!/usr/bin/env bash\n"
            'printf "%s\n" "$*" >> "' + log.as_posix() + '"\n'
            'exec "' + real + '" "$@"\n',
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return directory

    def test_the_migration_read_happens_once_in_the_script_and_none_in_the_writer(self) -> None:
        wrapper_dir = self._git_logging_bin()
        self.env = {
            **self.env,
            "PATH": wrapper_dir.as_posix() + os.pathsep + os.environ.get("PATH", ""),
        }
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_CHAT_MIGRATION_APPLIED=002_new_owner.sql", result.stdout)

        calls = [
            line
            for line in (self.tmp / "git-argv.log").read_text(encoding="utf-8").splitlines()
            if line
        ]
        # The import lists read code with `git show` too; the migration read is
        # the one this test is about.
        shows = [
            line
            for line in calls
            if " show " in " " + line + " " and "apps/padiem-chat/migrations/" in line
        ]
        # Exactly one read of the pending file, and it carries no per-command
        # trust exemption: the reading account already owns the object store.
        self.assertEqual(len(shows), 1, calls)
        self.assertNotIn("safe.directory", shows[0])
        # The operator's global config is never the mechanism, and the leg that
        # writes the database never reaches for git at all.
        script = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("config --global", script)
        function = script.split("apply_pending_chat_migrations() {", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("subprocess", function)
        self.assertIn("sql = sys.stdin.read()", function)


SIDECAR_SOURCES = [
    "deploy/host-com2/file-lane/check_config.py",
    "deploy/host-com2/file-lane/health.py",
    "deploy/host-com2/file-lane/padiem-file-lane.service",
    "deploy/host-com2/boot-recovery/wsl/boot_recovery.py",
    "deploy/host-com2/boot-recovery/wsl/boot-recovery.sh",
    "deploy/host-com2/boot-recovery/wsl/padiem-boot-recovery.service",
    "deploy/host-com2/connector-watch/connector_watch_host.py",
    ".github/scripts/connector_lane_watch.py",
    "deploy/host-com2/connector-watch/padiem-connector-watch.service",
    "deploy/host-com2/connector-watch/padiem-connector-watch.timer",
    "deploy/host-com2/offsite-backup/offsite.py",
    "deploy/host-com2/offsite-backup/padiem-offsite-backup.service",
    "deploy/host-com2/offsite-backup/padiem-offsite-backup.timer",
    "deploy/host-com2/cron/run-cron.sh",
    "deploy/host-com2/cron/run-expired-purge.sh",
    "deploy/host-com2/cron/status-cron.sh",
    "deploy/host-com2/cron/check_config_cron.py",
    "deploy/host-com2/cron/README.md",
    "deploy/host-com2/restart-policy/10-padiem-restart.conf",
    "deploy/host-com2/restart-policy/units.txt",
]

# The installed path each installer writes, without the leading slash so the
# test can point the report at a throwaway root. A new installer copy belongs
# in this map and in report_sidecar_drift's table.
SIDECAR_INSTALLED = {
    "deploy/host-com2/file-lane/check_config.py": "opt/padiem/file-lane/check_config.py",
    "deploy/host-com2/file-lane/health.py": "opt/padiem/file-lane/health.py",
    "deploy/host-com2/file-lane/padiem-file-lane.service": "etc/systemd/system/padiem-file-lane.service",
    "deploy/host-com2/boot-recovery/wsl/boot_recovery.py": "opt/padiem/boot-recovery/boot_recovery.py",
    "deploy/host-com2/boot-recovery/wsl/boot-recovery.sh": "opt/padiem/boot-recovery/boot-recovery.sh",
    "deploy/host-com2/boot-recovery/wsl/padiem-boot-recovery.service": "etc/systemd/system/padiem-boot-recovery.service",
    "deploy/host-com2/connector-watch/connector_watch_host.py": "opt/padiem/connector-watch/connector_watch_host.py",
    ".github/scripts/connector_lane_watch.py": "opt/padiem/connector-watch/connector_lane_watch.py",
    "deploy/host-com2/connector-watch/padiem-connector-watch.service": "etc/systemd/system/padiem-connector-watch.service",
    "deploy/host-com2/connector-watch/padiem-connector-watch.timer": "etc/systemd/system/padiem-connector-watch.timer",
    "deploy/host-com2/offsite-backup/offsite.py": "opt/padiem/offsite-backup/offsite.py",
    "deploy/host-com2/offsite-backup/padiem-offsite-backup.service": "etc/systemd/system/padiem-offsite-backup.service",
    "deploy/host-com2/offsite-backup/padiem-offsite-backup.timer": "etc/systemd/system/padiem-offsite-backup.timer",
    "deploy/host-com2/cron/run-cron.sh": "opt/padiem/chat-com2/run-cron.sh",
    "deploy/host-com2/cron/run-expired-purge.sh": "opt/padiem/chat-com2/run-expired-purge.sh",
    "deploy/host-com2/cron/status-cron.sh": "opt/padiem/chat-com2/status-cron.sh",
    "deploy/host-com2/cron/check_config_cron.py": "opt/padiem/chat-com2/check_config_cron.py",
    "deploy/host-com2/cron/README.md": "opt/padiem/chat-com2/README-cron.md",
}


class SidecarDriftReportTest(DeployHarness):
    """Installers the deploy never runs keep their own copy on the host.

    file-lane, boot-recovery, the restart drop-in, connector-watch,
    offsite-backup and cron each install their files by hand, so a change to
    main leaves the installed copy stale until someone remembers to run that
    installer (#6892 follow-up). The deploy reports the difference once and
    changes nothing.
    """

    scenario = "chat"
    base_extra = {
        path: (REPO / path).read_text(encoding="utf-8") for path in SIDECAR_SOURCES
    }

    def setUp(self) -> None:
        super().setUp()
        self.host = self.tmp / "host"
        self.env["PADIEM_COM2_INSTALLED_ROOT"] = self.host.as_posix()

    def _installed_pairs(self) -> list[tuple[str, str]]:
        pairs = list(SIDECAR_INSTALLED.items())
        units = (REPO / "deploy/host-com2/restart-policy/units.txt").read_text(
            encoding="utf-8"
        )
        for unit in units.splitlines():
            unit = unit.strip()
            if not unit or unit.startswith("#"):
                continue
            pairs.append((
                "deploy/host-com2/restart-policy/10-padiem-restart.conf",
                f"etc/systemd/system/{unit}.d/padiem-restart.conf",
            ))
        return pairs

    def _blob(self, path: str) -> bytes:
        # What git archive puts in the staged mirror: the commit's bytes,
        # not this checkout's line endings.
        done = subprocess.run(
            ["git", "-C", self.ops.as_posix(), "show", f"{self.second}:{path}"],
            capture_output=True, check=True,
        )
        return done.stdout

    def _install_all(self) -> None:
        for source, target in self._installed_pairs():
            path = self.host / target
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self._blob(source))

    def test_matching_installed_copies_report_none(self) -> None:
        self._install_all()
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("COM2_DEPLOY_AUX_DRIFT=NONE", result.stdout)
        self.assertIn("chat:PASS", result.stdout)

    def test_one_stale_copy_is_named_and_left_alone(self) -> None:
        self._install_all()
        stale = self.host / "etc/systemd/system/padiem-connector-watch.timer"
        stale.write_text("# stale\n", encoding="utf-8")
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "COM2_DEPLOY_AUX_DRIFT=connector-watch:etc/systemd/system/"
            "padiem-connector-watch.timer",
            result.stdout,
        )
        # Reported, never repaired: the stale copy is still there.
        self.assertEqual(stale.read_text(encoding="utf-8"), "# stale\n")

    def test_production_cron_missing_and_stale_are_reported_even_with_staging(self) -> None:
        self._install_all()
        prod = self.host / "opt/padiem/chat-com2"
        staging = self.host / "opt/padiem/chat-staging"
        staging.mkdir(parents=True)
        for name in ("run-cron.sh", "status-cron.sh"):
            shutil.copyfile(prod / name, staging / name)
        (prod / "run-cron.sh").unlink()
        (prod / "status-cron.sh").write_text("# stale\n", encoding="utf-8")

        result = self._run_apply()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("cron:opt/padiem/chat-com2/run-cron.sh=NOT_INSTALLED", result.stdout)
        self.assertIn("cron:opt/padiem/chat-com2/status-cron.sh", result.stdout)
        self.assertNotIn("cron:opt/padiem/chat-com2/status-cron.sh=NOT_INSTALLED", result.stdout)
        self.assertNotIn("cron:opt/padiem/chat-staging/", result.stdout)
        self.assertEqual((prod / "status-cron.sh").read_text(encoding="utf-8"), "# stale\n")

class ScriptBoundaryTest(unittest.TestCase):
    def test_the_ladder_defaults_to_four_minutes_and_an_env_value_wins(self) -> None:
        """11-06: a measured cold import took 56 s; 30 s rolled a good release back."""
        text = SCRIPT.read_text(encoding="utf-8")
        for name, var, default in (
            ("PADIEM_COM2_PORT_WAIT_TIMEOUT", "port_wait_timeout", "240"),
            ("PADIEM_COM2_HEALTH_TIMEOUT", "health_timeout", "240"),
        ):
            # The script's own assignment line, run by bash: unset gives the
            # default, an exported value is used verbatim.
            line = f'{var}=${{{name}:-{default}}}'
            self.assertIn(line, text)
            unset = subprocess.run(
                [BASH_BIN, "-c", f'unset {name}; {line}; printf %s "${{{var}}}"'],
                capture_output=True, text=True,
            )
            self.assertEqual(unset.returncode, 0, unset.stderr)
            self.assertEqual(unset.stdout, default)
            overridden = subprocess.run(
                [BASH_BIN, "-c", f'{line}; printf %s "${{{var}}}"'],
                capture_output=True, text=True, env=dict(os.environ, **{name: "7"}),
            )
            self.assertEqual(overridden.stdout, "7", overridden.stderr)

    def test_start_probes_are_given_four_minutes_by_default(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("health_timeout=${PADIEM_COM2_HEALTH_TIMEOUT:-240}", text)
        self.assertIn("port_wait_timeout=${PADIEM_COM2_PORT_WAIT_TIMEOUT:-240}", text)
        # chat, p01 and b14 walk the shared readiness ladder (unit active ->
        # port listening -> health contract); the queue keeps its own probe.
        # The stop and the "old process is gone" proof are one helper call, so a
        # path cannot stop the unit and then skip the wait.
        for label, unit, port in (
            ("CHAT", "CHAT_UNIT", "chat_port"),
            ("P01", "P01_UNIT", "p01_port"),
            ("B14", "B14_UNIT", "b14_port"),
            ("CHAT_ROLLBACK", "CHAT_UNIT", "chat_port"),
            ("P01_ROLLBACK", "P01_UNIT", "p01_port"),
            ("B14_ROLLBACK", "B14_UNIT", "b14_port"),
        ):
            self.assertIn(f'wait_service_ready {label} ', text)
            self.assertIn(f'with_service_stopped "${unit}" {label} "${port}"', text)
        for label, unit in (("QUEUE", "QUEUE_UNIT"), ("QUEUE_ROLLBACK", "QUEUE_UNIT"),
                            ("EXECUTOR", "EXECUTOR_UNIT"),
                            ("EXECUTOR_ROLLBACK", "EXECUTOR_UNIT")):
            self.assertIn(f'with_service_stopped "${unit}" {label}', text)
        self.assertIn('wait_service_ready P01_ROLLBACK "$P01_UNIT" "$p01_port"', text)
        for label in ("QUEUE", "QUEUE_ROLLBACK"):
            self.assertIn(f"wait_for_health {label} ", text)
        self.assertNotIn("wait_chat_health", text)
        # No single-shot probe is left behind a start or a rollback.
        self.assertNotIn(
            chr(10) + '    "$python_bin" "$staged/deploy/host-com2/p01/health.py"', text
        )
        self.assertNotIn('"$python_bin" "$ops_checkout/deploy/host-com2/b14/health.py"', text)
        # Process cleanup is unit- and PID-based, never name-pattern kills.
        self.assertNotIn("pkill", text)
        self.assertNotIn("killall", text)

    def test_the_script_only_mutates_behind_apply(self) -> None:
        text = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("systemctl enable", "wrangler", "openssl", "curl "):
            self.assertNotIn(forbidden, text)
        for required in ("--apply", "MIGRATION_FIRST", "ROLLBACK", "CHAT_DB_UNREADABLE"):
            self.assertIn(required, text)

    def test_the_readable_probe_does_not_depend_on_where_the_script_was_launched(self) -> None:
        # 11-03: three deploys stopped on SOURCE_PERMISSIONS_PREVIOUS with FILES=1
        # DIRS=1 for both trees. Neither tree was unreadable — the script had been
        # launched from /root (and state_dir is 0700 too), so the service account's
        # find could not restore its initial working directory, exited non-zero, and
        # the helpers' `|| files=1` fallback reported that as unreadable source.
        text = SCRIPT.read_text(encoding="utf-8")
        helper = text[text.index("probe_as_user() {"):text.index("read_check_method() {")]
        self.assertIn('( cd / && runuser -u "$user" -- "$@" )', helper)
        # Nothing else drops to the check account with a bare runuser.
        self.assertEqual(text.count('runuser -u "$user" --'), 1)
        for name in ("read_check_method", "unreadable_files", "unreachable_dirs"):
            block = text[text.index(f"{name}() " + "{"):]
            block = block[:block.index("\n}\n")]
            self.assertIn("probe_as_user", block, name)
            self.assertNotIn("runuser", block, name)


if __name__ == "__main__":
    unittest.main()


class ChatB14RunningCodeTest(DeployHarness):
    """#7028 follow-up: Chat and B14 rollbacks are visible to the next plan."""

    scenario = "chat"

    def setUp(self) -> None:
        super().setUp()
        self.chat_app = self.tmp / "chat-app"
        self.env["PADIEM_COM2_CHAT_APP"] = self.chat_app.as_posix()
        self.env["PADIEM_COM2_B14_APP"] = self.b14.as_posix()
        # The deploy compares real paths with the shell's own readlink; a
        # drive-letter spelling never resolves a link there, so give the run the
        # /c/ spelling it produces.
        for key in ("PADIEM_COM2_PREVIOUS_DIR", "PADIEM_COM2_CHAT_APP", "PADIEM_COM2_B14_APP"):
            self.env[key] = self._msys(self.env[key])

    @staticmethod
    def _msys(path: str) -> str:
        if len(path) > 2 and path[1] == ":" and path[2] == "/":
            return "/" + path[0].lower() + path[2:]
        return path

    def _dry_run(self) -> str:
        result = self._run_main(
            self.second, "--ops-checkout", self.ops.as_posix(),
            "--state-dir", self.state.as_posix(), "--chat-db", self.db.as_posix(),
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        return output

    def _tree(self, root: Path, sha: str, relative: str) -> Path:
        target = root / sha / relative
        target.mkdir(parents=True, exist_ok=True)
        (target / "marker").write_text(sha + "\n", encoding="utf-8")
        return target

    def _point(self, link: Path, target: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target, target_is_directory=True)

    def test_a_chat_rollback_link_is_selected_again(self) -> None:
        # The checkout records the new commit, the unit runs the rollback copy.
        self._git(str(self.ops), "checkout", "-q", self.second)
        rolled_back = self._tree(self.previous, self.first, "apps/padiem-chat/app")
        self._point(self.chat_app, rolled_back)

        output = self._dry_run()

        self.assertIn("COM2_DEPLOY_CHAT_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", output)
        self.assertIn(
            "COM2_DEPLOY_DECISION_CHAT=REDEPLOY reason_files=0 "
            "reason=RUNNING_CODE_MISMATCH",
            output,
        )
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:WOULD_DEPLOY", output)

    def test_a_chat_link_on_the_recorded_release_is_skipped(self) -> None:
        self._git(str(self.ops), "checkout", "-q", self.second)
        current = self._tree(self._stage().parent, self.second, "apps/padiem-chat/app")
        self._point(self.chat_app, current)

        output = self._dry_run()

        self.assertIn("COM2_DEPLOY_CHAT_RUNNING_CODE=MATCH", output)
        self.assertIn("COM2_DEPLOY_DECISION_CHAT=SKIP reason_files=0", output)

    def test_a_b14_rollback_link_is_selected_again(self) -> None:
        self._git(str(self.ops), "checkout", "-q", self.second)
        rolled_back = self._tree(self.previous, self.first, "apps/korean-ai-platform")
        self._point(self.b14, rolled_back)

        output = self._dry_run()

        self.assertIn("COM2_DEPLOY_B14_RUNNING_CODE=DIFF_OR_UNVERIFIABLE", output)
        self.assertIn(
            "COM2_DEPLOY_DECISION_B14=REDEPLOY reason_files=0 "
            "reason=RUNNING_CODE_MISMATCH",
            output,
        )
        self.assertIn("COM2_DEPLOY_SUMMARY=chat:SKIP p01:SKIP b14:WOULD_DEPLOY", output)

    def test_a_b14_link_on_the_recorded_release_is_skipped(self) -> None:
        self._git(str(self.ops), "checkout", "-q", self.second)
        current = self._tree(self._stage().parent, self.second, "apps/korean-ai-platform")
        self._point(self.b14, current)

        output = self._dry_run()

        self.assertIn("COM2_DEPLOY_B14_RUNNING_CODE=MATCH", output)
        self.assertIn("COM2_DEPLOY_DECISION_B14=SKIP reason_files=0", output)


class ToolSerializationVerdictTest(DeployHarness):
    """#7162: #7155's check prints the ENV_FILE line before the verdict.

    The deploy used to prefix-match the whole captured output, so the first
    line (TOOLS_SERIALIZATION_ENV_FILE=...) never matched PASS* and every
    result became tools_serialization:ERROR. These tests drive the real apply
    path with the check's exact two-line shape.
    """

    scenario = "chat"
    base_extra = {
        ".github/scripts/post_deploy_tool_serialization_check.py": (
            "import os\n"
            "import sys\n"
            "print('TOOLS_SERIALIZATION_ENV_FILE=applied_vars=32')\n"
            "verdict = os.environ.get('FAKE_TOOLS_VERDICT', 'PASS')\n"
            "if verdict == 'SILENT':\n"
            "    raise SystemExit(3)\n"
            "print('TOOLS_SERIALIZATION=' + verdict)\n"
            "raise SystemExit({'PASS': 0, 'FAIL': 1}.get(verdict, 2))\n"
        ),
    }

    def setUp(self) -> None:
        super().setUp()
        # The venv interpreter gate: reuse the running interpreter.
        self.env["PADIEM_COM2_CHAT_VENV_PYTHON"] = Path(sys.executable).as_posix()

    def test_the_env_file_line_does_not_turn_a_pass_into_error(self) -> None:
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TOOLS_SERIALIZATION=PASS", result.stdout)
        self.assertIn("tools_serialization:PASS", result.stdout)
        self.assertNotIn("tools_serialization:ERROR", result.stdout)

    def test_a_fail_verdict_still_stops_the_deploy(self) -> None:
        self.env["FAKE_TOOLS_VERDICT"] = "FAIL"
        result = self._run_apply()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tools_serialization:FAIL", result.stdout)

    def test_an_error_verdict_continues_with_the_warning(self) -> None:
        self.env["FAKE_TOOLS_VERDICT"] = "ERROR"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tools_serialization:ERROR", result.stdout)

    def test_a_crash_without_a_verdict_is_reported_as_a_harness_error(self) -> None:
        self.env["FAKE_TOOLS_VERDICT"] = "SILENT"
        result = self._run_apply()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("TOOLS_SERIALIZATION_ERROR=no_verdict_line", result.stdout)
        self.assertIn("tools_serialization:ERROR", result.stdout)
