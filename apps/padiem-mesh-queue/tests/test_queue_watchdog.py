"""#5881 follow-on — the queue notices its own silence, and the deploy agrees with the code.

Two things are proved here and neither re-implements a rule.

The counting first: a health read that stops answering must reach the documented exit
code, an answer that comes back must reset the count, and the deadline is held by a
thread waiting on the result. A SQLite call that blocks inside the engine cannot be
interrupted from the cooperative path, so a watchdog that only ran there would never
fire on the single failure it exists for.

The shape second: the unit file, the installer and the runbook name the same
`MESH_QUEUE_*` keys the service reads. A renamed key is otherwise discovered by whoever
restarts the service at 04:35.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
DOCS = QUEUE.parents[1] / "docs" / "operations"
DEPLOY = QUEUE / "deploy"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.d1_sqlite import SqliteD1, connect  # noqa: E402
from schema import apply  # noqa: E402
from service import (  # noqa: E402
    EXIT_UNRESPONSIVE, LIVENESS_ANSWERED, LIVENESS_FAILED, LIVENESS_FAILURES_BEFORE_RESTART,
    liveness_check, liveness_rounds,
)

#: The keys app_from_environment must keep reading. A parse that loses one of these is
#: a broken parse, not a missing feature - the real set is read out of the code below.
CORE_KEYS = frozenset({
    "MESH_QUEUE_DB_PATH", "MESH_QUEUE_CHANNEL_SECRET_FILE",
    "MESH_QUEUE_OWNERSHIP_MAP_FILE", "MESH_QUEUE_EXECUTION_MODE",
    "MESH_QUEUE_SERVICE_SECRET_FILE",
    # #82: the read-only lane-status leg, optional at install.
    "MESH_QUEUE_WATCH_READ_SECRET_FILE",
})


def code_keys():
    """Which MESH_QUEUE_* names the service actually reads - read from the service.

    Hand-copying the list is how a contract goes quiet: #82 added
    MESH_QUEUE_WATCH_READ_SECRET_FILE and a copied list would simply have stopped
    covering it. The parse fails loudly instead.
    """

    source = (QUEUE / "service.py").read_text(encoding="utf-8")
    found = frozenset(re.findall(r'"(MESH_QUEUE_[A-Z_]+)"', source))
    assert CORE_KEYS <= found, "the key parse lost the core keys: %s" % sorted(
        CORE_KEYS - found)
    return found
#: Keys the deploy and backup scripts set or print that are not read by the service.
OPS_KEYS = frozenset({
    "MESH_QUEUE_BACKUP_DIR", "MESH_QUEUE_BACKUP_KEEP", "MESH_QUEUE_STEP",
    "MESH_QUEUE_ACTIVE", "MESH_QUEUE_TIMER_ACTIVE", "MESH_QUEUE_SECRET",
    "MESH_QUEUE_BACKUP", "MESH_QUEUE_BACKUP_KEPT", "MESH_QUEUE_VENV",
    "MESH_QUEUE_IMPORT", "MESH_QUEUE_HEALTH", "MESH_QUEUE_HEALTH_URL",
    "MESH_QUEUE_HEALTH_TIMEOUT_SECONDS",
})


class _Stop(Exception):
    """Raised from the injected sleep so an endless loop can be observed and ended."""


class _Stuck:
    """A store that never answers — the wedge the watchdog exists for."""

    def __init__(self):
        self.held = threading.Event()

    def prepare(self, _sql):
        return self

    async def all(self):
        self.held.wait()
        return []


class _Broken:
    """A store that answers with an error: a missing table, an unreadable file."""

    def prepare(self, _sql):
        raise RuntimeError("no such table: oracle_mesh_dispatch")


def _store(tmp_path):
    """The production connection, not a bare sqlite3.connect: the liveness read runs
    on the watchdog's thread, and only `connect()` opens the database cross-thread."""

    connection = connect(str(tmp_path / "queue.sqlite3"))
    apply(connection)
    return SqliteD1(connection)


def _verdicts(*answers):
    """A check() stand-in that replays the given verdicts, then repeats the last."""

    seen = []

    def check(_database, **_kwargs):
        verdict = answers[len(seen)] if len(seen) < len(answers) else answers[-1]
        seen.append(verdict)
        return verdict

    check.rounds = seen
    return check


def _stop_after(count):
    def sleep(_interval):
        if len(sleep.rounds) >= count:
            raise _Stop("the plan is exhausted")
        sleep.rounds.append(1)

    sleep.rounds = []
    return sleep


def test_a_healthy_store_is_answered(tmp_path):
    database = _store(tmp_path)
    try:
        assert liveness_check(database) == LIVENESS_ANSWERED
    finally:
        database.connection.close()


def test_a_store_that_raises_is_failed():
    assert liveness_check(_Broken()) == LIVENESS_FAILED


def test_a_store_that_blocks_is_failed_within_wall_time():
    stuck = _Stuck()
    started = time.monotonic()
    verdict = liveness_check(stuck, deadline=0.2)
    elapsed = time.monotonic() - started
    assert verdict == LIVENESS_FAILED
    assert elapsed < 5.0, "the bound is wall-clock: it must not wait for the wedge"
    stuck.held.set()


def test_three_fails_in_a_row_exit_with_the_documented_code():
    exits = []

    def give_up(_code):
        exits.append(_code)
        raise _Stop("the watchdog has done its one job")

    check = _verdicts(LIVENESS_FAILED)
    try:
        liveness_rounds(None, sleep=_stop_after(LIVENESS_FAILURES_BEFORE_RESTART + 2),
                        exit_process=give_up, check=check)
    except _Stop:
        pass
    assert exits == [EXIT_UNRESPONSIVE]
    assert len(check.rounds) == LIVENESS_FAILURES_BEFORE_RESTART


def test_two_fails_alone_do_not_restart_anything():
    exits = []
    check = _verdicts(LIVENESS_FAILED)
    sleeper = _stop_after(LIVENESS_FAILURES_BEFORE_RESTART - 1)
    try:
        liveness_rounds(None, sleep=sleeper, exit_process=exits.append, check=check)
    except _Stop:
        pass
    assert exits == []
    assert len(check.rounds) == LIVENESS_FAILURES_BEFORE_RESTART - 1


def test_an_answer_resets_the_count():
    """fail, fail, answered, fail, fail must not restart: only three in a row may."""

    exits = []
    check = _verdicts(LIVENESS_FAILED, LIVENESS_FAILED, LIVENESS_ANSWERED,
                      LIVENESS_FAILED, LIVENESS_FAILED)
    try:
        liveness_rounds(None, sleep=_stop_after(5), exit_process=exits.append,
                        check=check)
    except _Stop:
        pass
    assert exits == []
    assert len(check.rounds) == 5


def test_the_unit_and_installer_name_the_keys_the_code_reads():
    unit = (DEPLOY / "padiem-mesh-queue.service").read_text(encoding="utf-8")
    installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    runbook = (DOCS / "COM2_PC_DISPATCH_QUEUE_CUTOVER_20261029.md").read_text(
        encoding="utf-8")

    assert "EnvironmentFile=/opt/padiem/mesh-queue/queue.env" in unit
    assert "Restart=always" in unit and "StartLimitIntervalSec=0" in unit
    assert re.search(r"^User=padiem-mesh$", unit, re.M)
    assert "UMask=0077" in unit

    named = set(re.findall(r"\bMESH_QUEUE_[A-Z_]+", installer + runbook))
    read = code_keys()
    unknown = named - read - OPS_KEYS
    assert not unknown, "deploy names a key the service does not read: %s" % sorted(unknown)
    missing = read - named
    assert not missing, "the service reads a key the deploy never sets: %s" % sorted(missing)


def test_install_sh_installs_every_unit_and_script_in_deploy():
    """A file that ships in deploy/ and is never installed is a file nobody runs."""

    installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    for path in sorted(DEPLOY.iterdir()):
        if path.name.endswith((".service", ".timer")):
            assert path.name in installer, "%s is never installed" % path.name
            assert "systemctl enable" in installer
        elif path.name.endswith(".sh") and path.name != "install.sh":
            assert path.name in installer, "%s is never copied to the host" % path.name


def test_deploy_scripts_parse_as_bash_and_are_lf_only():
    """A deploy file is read by Linux: CRLF or a syntax error is found there, not here."""

    for script in sorted(DEPLOY.iterdir()):
        raw = script.read_bytes()
        assert b"\r" not in raw, "%s carries CRLF into a systemd/bash path" % script.name
        if not script.name.endswith(".sh"):
            continue
        bash = shutil.which("bash")
        if bash is None:
            continue
        result = subprocess.run([bash, "-n", str(script)],
                                capture_output=True, text=True)
        assert result.returncode == 0, "%s: %s" % (script.name, result.stderr.strip())
        assert result.stderr.strip() == "", "%s: %s" % (script.name, result.stderr.strip())


def test_the_migration_dir_is_found_in_both_layouts_and_can_be_overridden(tmp_path):
    """The installed copy sits at $ROOT/schema.py, one level above the Chat app link."""

    import os

    import schema

    # Repository layout: the Chat app is one level up, exactly as the module path says.
    assert (schema.migration_dir() / "047_oracle_mesh_dispatch.sql").is_file()

    # Installed layout: $ROOT/app -> <chat>/app, and ../migrations through that link.
    root = tmp_path / "queue"
    chat = tmp_path / "chat"
    (chat / "app").mkdir(parents=True)
    (chat / "migrations").mkdir()
    (root).mkdir()
    (root / "app").symlink_to(chat / "app")
    assert schema.migration_dir(root) == (chat / "migrations").resolve()

    # An explicit override wins over both layouts.
    previous = os.environ.get("MESH_QUEUE_MIGRATIONS_DIR")
    os.environ["MESH_QUEUE_MIGRATIONS_DIR"] = str(chat / "migrations")
    try:
        assert schema.migration_dir() == chat / "migrations"
    finally:
        if previous is None:
            os.environ.pop("MESH_QUEUE_MIGRATIONS_DIR", None)
        else:
            os.environ["MESH_QUEUE_MIGRATIONS_DIR"] = previous


def test_the_suite_runs_in_ci_and_needs_no_credential():
    """A cutover gate that only ever ran on one laptop is not a gate."""

    workflow = (QUEUE.parents[1] / ".github" / "workflows"
                / "com2-mesh-queue-contract-tests.yml").read_text(encoding="utf-8")
    assert "python -m pytest -q apps/padiem-mesh-queue/tests" in workflow
    assert '- "apps/padiem-mesh-queue/**"' in workflow
    assert "secrets." not in workflow, "this lane is offline; a secret makes it not so"
    assert "${{ secrets" not in workflow and "CLOUDFLARE_API_TOKEN" not in workflow
    assert "wrangler" not in workflow


def test_the_installer_hands_the_backup_dir_to_the_service_user():
    """backup.sh writes as the service user; a root-owned parent fails with no-file."""

    installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "install -d -m 0700 -o \"$ACCOUNT\" -g \"$ACCOUNT\" /opt/padiem/backups/mesh-queue" in installer


def test_the_installer_protects_the_tree_it_copies_from():
    """`--delete` against a source checked out under the install root deletes the source.

    컴2 runs the queue from a worktree at $ROOT/src precisely so the shared checkout and
    the other units' sources stay untouched, so the installer has to exclude that
    directory and refuse any other nested source instead of discovering it on a re-run.
    """

    installer = (DEPLOY / "install.sh").read_text(encoding="utf-8")
    assert "--delete" in installer
    assert "--exclude /src" in installer
    assert "source_nested_refused" in installer


def test_the_service_listens_on_loopback_only():
    service_source = (QUEUE / "service.py").read_text(encoding="utf-8")

    assert re.search(r'host="127\.0\.0\.1"', service_source)
    assert 'host="0.0.0.0"' not in service_source


def test_an_installed_secret_file_is_owner_readable_and_no_wider(tmp_path):
    """The provisioner's promise, checked on a real file: 0600 or nothing."""

    script = (DEPLOY / "provision_service_secret.sh").read_text(encoding="utf-8")
    assert "umask 077" in script and 'chmod 600 "$TARGET"' in script
    assert 'echo "$value"' not in script and "cat \"$TARGET\"" not in script
