"""#6737 — the restore smoke script's contract, run against the real tool.

The script is sourced here (its `main` is guarded), so each helper is exercised
in the same shell the COM2 run uses. One test drives the real
`offsite.py restore` with a test-key envelope and proves the target is a FILE:
the first version passed a directory and raised IsADirectoryError on COM2.

Nothing here reads production data, opens a socket beyond loopback, or prints a
secret value. Paths that both bash and a Windows Python must see (the restore
target) are only exercised on POSIX; the rest of the contract runs everywhere.
"""
from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "deploy/host-com2/offsite-backup/run_live_chat_restore.sh"
TOOL = REPO / "deploy/host-com2/offsite-backup/offsite.py"
BASH = shutil.which("bash")
SMOKE_PORT = 18798

SPEC = importlib.util.spec_from_file_location("offsite_backup_script_test", TOOL)
offsite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(offsite)

SECRET_KEY_HEX = "ab" * 32
MONDAY = datetime(2026, 11, 2, 5, 10, tzinfo=timezone.utc)


def _make_db(path: Path, rows: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO t (value) VALUES (?)", [(f"row-{index}",) for index in range(rows)]
        )
        connection.commit()
    finally:
        connection.close()


def _crypto_available() -> bool:
    try:
        offsite._load_crypto()
    except Exception:
        return False
    return True


@unittest.skipUnless(BASH, "bash is required to source the restore script")
class RestoreScriptContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # --- harness -------------------------------------------------------------

    def _bash(self, body: str, extra_env: dict[str, str] | None = None):
        env = dict(os.environ)
        env["PADIEM_RESTORE_PYTHON"] = sys.executable
        env.pop("PADIEM_CHAT_LOCAL_DATA_DIR", None)
        env.update(extra_env or {})
        return subprocess.run(
            [BASH, "-c", "source " + shlex.quote(str(SCRIPT)) + "\n" + body],
            cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
        )

    def _prepare_backup(self) -> dict[str, str]:
        if not _crypto_available():
            self.skipTest("cryptography is not installed in this interpreter")
        key_file = self.root / "offsite.key"
        key_file.write_text(SECRET_KEY_HEX, encoding="utf-8")
        os.chmod(key_file, 0o600)
        backups = self.root / "backups"
        backups.mkdir()
        _make_db(backups / "chat-20261102T042000Z.sqlite3", 300)
        env = {
            "OFFSITE_R2_DIR": str(self.root / "r2"),
            "OFFSITE_STATE_DIR": str(self.root / "state"),
            "COM2_OFFSITE_KEY_FILE": str(key_file),
            "COM2_OFFSITE_KEY_ID": "com2-2026-11",
            "OFFSITE_CHAT_BACKUP_DIR": str(backups),
        }
        results = offsite.run_upload(dict(env), services=["chat"], now=MONDAY)
        self.assertEqual(results[0]["backup_id"], "20261102")
        env["PADIEM_LIVE_BACKUP_DATE"] = "20261102"
        return env

    # --- checks --------------------------------------------------------------

    def test_script_parses(self):
        parsed = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(parsed.returncode, 0, parsed.stderr)

    def test_restore_target_name_is_chat_sqlite3(self):
        done = self._bash("restore_target_path /tmp/example\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "/tmp/example/chat.sqlite3")

    def test_restore_target_is_a_file_the_chat_host_opens(self):
        env = self._prepare_backup()
        data_dir = self.root / "chat-data"
        # bash runs the restore; the tool it starts is this host's Python, so the
        # data dir is handed over in the shell's own path form.
        shell_dir = str(data_dir)
        if os.name == "nt" and shutil.which("cygpath"):
            shell_dir = subprocess.run(
                ["cygpath", "-u", str(data_dir)], capture_output=True, text=True, encoding="utf-8"
            ).stdout.strip()
        body = (
            "repo_root=" + shlex.quote(str(REPO)) + "\n"
            "restore_into " + shlex.quote(shell_dir) + "\n"
        )
        done = self._bash(body, env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("IsADirectoryError", done.stdout + done.stderr)
        target = data_dir / "chat.sqlite3"
        self.assertTrue(target.is_file())
        connection = sqlite3.connect(target)
        try:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM t").fetchone()[0], 300)
        finally:
            connection.close()
        self.assertIn("restore_smoke_timing restore_ms=", done.stdout)
        # The tool's own PASS line proves offsite.py ran, not a stub.
        self.assertIn("OFFSITE_RESTORE=PASS", done.stdout)
        self.assertNotIn(SECRET_KEY_HEX, done.stdout + done.stderr)

    def test_production_and_foreign_targets_are_refused(self):
        targets = (
            ("/var/lib/padiem-chat/chat-data/chat.sqlite3", "target_is_production_path"),
            ("/mnt/d/padiem/chat-com2/chat.sqlite3", "target_is_production_path"),
            ("relative/chat.sqlite3", "target_not_absolute"),
        )
        for candidate, reason in targets:
            done = self._bash("refuse_unisolated_target " + shlex.quote(candidate) + "\n")
            self.assertNotEqual(done.returncode, 0, candidate)
            self.assertIn("reason=" + reason, done.stderr)
        # An isolated folder under the temp root is allowed.
        done = self._bash(
            'WORK="$(mktemp -d)"\n'
            'export TMPDIR="$WORK"\n'
            'mkdir "$WORK/isolated"\n'
            'refuse_unisolated_target "$WORK/isolated"\n'
        )
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_busy_smoke_port_fails_instead_of_moving(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", SMOKE_PORT))
            sock.listen(1)
            done = self._bash(f"require_free_port {SMOKE_PORT}\n")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"reason=port_busy_{SMOKE_PORT}", done.stderr)

    def test_every_upstream_is_a_closed_loopback_port(self):
        body = (
            'export_smoke_env "$PWD/chat-data"\n'
            'printf "%s|%s|%s|%s|%s\\n" "$PC_QUEUE_ORIGIN" "$PADIEM_CHAT_B14_BASE_URL" '
            '"$PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN" "$PADIEM_CHAT_ORCHESTRATION_ENABLED" '
            '"$NO_PROXY"\n'
        )
        done = self._bash(body)
        self.assertEqual(done.returncode, 0, done.stderr)
        queue, b14, p01, enabled, no_proxy = done.stdout.strip().split("|")
        self.assertEqual(queue, "http://127.0.0.1:18797")
        self.assertEqual(b14, "http://127.0.0.1:18789")
        self.assertEqual(p01, "http://127.0.0.1:18811")
        self.assertEqual(enabled, "false")
        self.assertIn("127.0.0.1", no_proxy)
        self.assertNotIn("https://", done.stdout)

    def test_env_file_dollar_values_stay_literal_and_never_print(self):
        secret = 'ab$cd`echo`"q'
        body = (
            'WORK="$(mktemp -d)"\n'
            "cat > \"$WORK/com2.env\" <<'ENVEOF'\n"
            "# values are read, never sourced\n"
            "export SMOKE_TOKEN=" + secret + "\n"
            "SMOKE_PLAIN=ok\n"
            "ENVEOF\n"
            'load_env_file "$WORK/com2.env"\n'
            'printf "plain=%s len=%s\\n" "$SMOKE_PLAIN" "${#SMOKE_TOKEN}"\n'
            "case \"$SMOKE_TOKEN\" in *'$cd'*) echo dollar_literal=yes;; esac\n"
        )
        done = self._bash(body)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("plain=ok", done.stdout)
        self.assertIn(f"len={len(secret)}", done.stdout)
        self.assertIn("dollar_literal=yes", done.stdout)
        self.assertNotIn("ab$cd", done.stdout + done.stderr)
        self.assertNotIn("echo`", done.stdout + done.stderr)

    def test_verification_reports_integrity_foreign_keys_ledger_and_rows(self):
        database = self.root / "restored.sqlite3"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
            )
            connection.execute(
                "CREATE TABLE padiem_local_migration_ledger "
                "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO padiem_local_migration_ledger VALUES "
                "('001_a.sql', 'x'), ('002_b.sql', 'y')"
            )
            connection.execute("INSERT INTO child (parent_id) VALUES (99)")
            connection.commit()
        finally:
            connection.close()
        done = self._bash("verify_restored_db " + shlex.quote(str(database)) + "\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("restore_check integrity=ok foreign_key_violations=1 tables=3", done.stdout)
        self.assertIn("ledger_last=002_b.sql", done.stdout)
        self.assertIn("restore_check_rows ", done.stdout)

    def test_shutdown_proves_the_port_is_closed(self):
        body = (
            f'"{sys.executable}" -m http.server {SMOKE_PORT} --bind 127.0.0.1 '
            ">/dev/null 2>&1 &\n"
            "SERVER_PID=$!\n"
            "sleep 1\n"
            "stop_smoke_server\n"
        )
        done = self._bash(body)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(f"restore_smoke_port_closed=true port={SMOKE_PORT}", done.stdout)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", SMOKE_PORT))


if __name__ == "__main__":
    unittest.main()
