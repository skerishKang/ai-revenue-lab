"""Offline packaging checks for padiem-broker; never install/start a host service."""
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Packaging(unittest.TestCase):
    def test_installer_is_read_only_by_default_and_bash_syntax_valid(self):
        subprocess.run(["bash", "-n", "install.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("BROKER_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("TUNNEL_CHANGE=NO", result.stdout)
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("rm -rf", source)

    def test_unit_is_loopback_only_and_imports_the_checkout(self):
        unit = (HERE / "padiem-broker.service").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("--port 8799", unit)
        self.assertNotIn("0.0.0.0", unit)
        self.assertIn("Environment=PYTHONPATH=/opt/padiem/broker:/opt/padiem/broker/src", unit)

    def test_backup_verifies_before_rotation_and_never_touches_the_pepper(self):
        source = (HERE / "backup.py").read_text(encoding="utf-8")
        self.assertIn("VACUUM INTO", source)
        self.assertIn("integrity_check", source)
        self.assertLess(source.index("integrity_check"), source.index("backups[:-keep]"))
        # The docstring may name the pepper, but no code path may read it.
        self.assertNotIn("LOCAL_AGENT_BROKER_PEPPER", source)
        self.assertNotIn("PEPPER_FILE", source)
        unit = (HERE / "padiem-broker-backup.service").read_text(encoding="utf-8")
        self.assertNotIn("secrets/", unit)

    def test_secret_provisioning_never_prints_values(self):
        subprocess.run(["bash", "-n", "provision_secrets.sh"], cwd=HERE, check=True)
        source = (HERE / "provision_secrets.sh").read_text(encoding="utf-8")
        self.assertIn("umask 077", source)
        self.assertIn("chmod 0600", source)
        self.assertIn("secrets.token_hex(32)", source)
        self.assertIn("VALUES_PRINTED=NO", source)
        self.assertNotIn("echo $(", source)

    def test_requirements_are_exact_pins_with_hashes(self):
        text = (HERE / "requirements.txt").read_text(encoding="utf-8")
        pins = [line for line in text.splitlines() if line and not line.startswith(("#", " "))]
        self.assertTrue(pins)
        for line in pins:
            self.assertRegex(line, r"^[a-z0-9-]+==\d")
            self.assertTrue(line.endswith("\\"))

    def test_env_example_carries_paths_and_names_only(self):
        text = (HERE / ".env.example").read_text(encoding="utf-8")
        allowed = {
            "", "false", "0",
            "/opt/padiem/broker/secrets/rpc_ingress_secret",
            "/opt/padiem/broker/secrets/pepper",
            "/mnt/d/padiem/broker/broker.sqlite3",
        }
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            _, _, value = line.partition("=")
            self.assertIn(value, allowed, line)


class CheckConfig(unittest.TestCase):
    def _env(self, data):
        return {
            "PADIEM_BROKER_RPC_INGRESS_SECRET": "x" * 40,
            "LOCAL_AGENT_BROKER_PEPPER_FILE": str(data.parent / "pepper-test-file"),
            "LOCAL_AGENT_BROKER_AUTHORITY_REF": "control-plane.local-agent-broker.test.v1",
            "PADIEM_BROKER_DB_PATH": str(data / "broker.sqlite3"),
        }

    def test_ready_requires_both_secrets_and_a_writable_data_dir(self):
        module = load("check_config")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            (data.parent / "pepper-test-file").write_text("y" * 40)
            (data.parent / "pepper-test-file").chmod(0o600)
            module.DATA = data
            with unittest.mock.patch.dict(os.environ, self._env(data), clear=True):
                self.assertTrue(module.ready())
            for broken in (
                {"PADIEM_BROKER_RPC_INGRESS_SECRET": "short"},
                {"LOCAL_AGENT_BROKER_PEPPER_FILE": ""},
                {"LOCAL_AGENT_BROKER_PEPPER": "y" * 40},
                {"LOCAL_AGENT_BROKER_PEPPER_FILE": str(data / "broker.sqlite3")},
                {"LOCAL_AGENT_BROKER_AUTHORITY_REF": ""},
                {"PADIEM_BROKER_DB_PATH": "/tmp/elsewhere.sqlite3"},
            ):
                environment = self._env(data)
                environment.update(broken)
                with unittest.mock.patch.dict(os.environ, environment, clear=True):
                    self.assertFalse(module.ready(), broken)


class Health(unittest.TestCase):
    def test_health_rejects_non_loopback_and_reads_status_ok(self):
        module = load("health")
        self.assertFalse(module.check("http://example.com/health")[0])
        self.assertFalse(module.check("https://127.0.0.1:8799/health")[0])

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"status": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            ok, status = module.check(f"http://127.0.0.1:{server.server_port}/health")
        finally:
            server.server_close()
        self.assertTrue(ok)
        self.assertEqual(status, 200)


class Backup(unittest.TestCase):
    def test_backup_snapshots_verifies_and_rotates(self):
        module = load("backup")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "broker.sqlite3"
            db = sqlite3.connect(db_path)
            for table in module.TABLES:
                if table == "local_agent_command_material":
                    db.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT, expires_at TEXT)")
                    db.execute(f"INSERT INTO {table} VALUES ('one', 'private row text', '2000-01-01T00:00:00Z')")
                else:
                    db.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT)")
                    db.execute(f"INSERT INTO {table} VALUES ('one', 'private row text')")
            db.commit()
            db.close()
            dest = root / "backups"
            dest.mkdir()
            for stale in ("broker-20200101T000000Z.sqlite3", "broker-20200102T000000Z.sqlite3"):
                (dest / stale).write_bytes(b"old")
            with unittest.mock.patch("sys.stdout") as output:
                self.assertEqual(module.main(["--db", str(db_path), "--dest", str(dest), "--keep", "2"]), 0)
                printed = "".join(str(call.args[0]) for call in output.write.call_args_list if call.args)
            self.assertIn("BROKER_BACKUP=PASS", printed)
            self.assertNotIn("private row text", printed)
            kept = sorted(path.name for path in dest.glob("broker-*.sqlite3"))
            self.assertEqual(len(kept), 2)
            snapshot = sqlite3.connect(dest / kept[-1])
            try:
                self.assertEqual(snapshot.execute("SELECT COUNT(*) FROM local_agent_command_material").fetchone()[0], 0)
            finally:
                snapshot.close()
            live = sqlite3.connect(db_path)
            try:
                self.assertEqual(live.execute("SELECT COUNT(*) FROM local_agent_command_material").fetchone()[0], 1)
            finally:
                live.close()


if __name__ == "__main__":
    unittest.main()
