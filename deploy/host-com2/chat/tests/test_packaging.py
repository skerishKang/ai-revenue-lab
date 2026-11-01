"""Offline packaging checks; never install/start a host service."""
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Packaging(unittest.TestCase):
    def test_installer_is_read_only_by_default_and_bash_syntax_valid(self):
        # Relative name + cwd: the checkout path itself may be non-ASCII.
        subprocess.run(["bash", "-n", "install.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("CHAT_COM2_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("TUNNEL_CHANGE=NO", result.stdout)
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("rm -rf", source)

    def test_units_listen_on_loopback_only_and_never_name_the_production_host(self):
        unit = (HERE / "padiem-chat-com2.service").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("--port 8798", unit)
        self.assertNotIn("0.0.0.0", unit)
        self.assertNotIn("chat.padiem.net", unit)
        for name in (
            "padiem-chat-com2-health.service", "padiem-chat-com2-health.timer",
            "padiem-chat-com2-backup.service", "padiem-chat-com2-backup.timer",
        ):
            text = (HERE / name).read_text(encoding="utf-8")
            self.assertNotIn("0.0.0.0", text)
            self.assertNotIn("chat.padiem.net", text)
        tunnel = (HERE / "cloudflared-chat-com2.example.yml").read_text(encoding="utf-8")
        self.assertIn("hostname: chat-com2.padiem.net", tunnel)
        self.assertIn("http://127.0.0.1:8798", tunnel)

    def test_requirements_are_exact_pins_with_hashes(self):
        text = (HERE / "requirements.txt").read_text(encoding="utf-8")
        pins = [line for line in text.splitlines() if line and not line.startswith(("#", " "))]
        self.assertTrue(pins)
        for line in pins:
            self.assertRegex(line, r"^[a-z0-9-]+==\d")
            self.assertTrue(line.endswith("\\"))

    def test_env_example_carries_names_only(self):
        text = (HERE / ".env.example").read_text(encoding="utf-8")
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            speed_defaults = {"PADIEM_CHAT_AUTH_CACHE_SECONDS": "30",
                              "PADIEM_CHAT_SQLITE_READERS": "2"}
            if name in speed_defaults:
                self.assertEqual(value, speed_defaults[name])
                continue
            self.assertIn(
                value, ("", "1", "true", "false", "mock", "off", "600",
                        "https://chat-com2.padiem.net", "/mnt/d/padiem/chat-com2",
                        "/mnt/d/padiem/chat-com2/MAINTENANCE"),
                name,
            )

    def test_environment_file_mode_is_forced_private(self):
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertIn("chmod 0600", source)
        self.assertIn("chown root:root", source)

    def test_worker_launcher_and_backup_follow_the_configured_data_directory(self):
        unit = (HERE / "padiem-chat-com2.service").read_text(encoding="utf-8")
        self.assertIn("-m app.local_server --host 127.0.0.1 --port 8798", unit)
        self.assertIn("ReadWritePaths=-/opt/padiem/chat-com2/data", unit)
        backup = (HERE / "padiem-chat-com2-backup.service").read_text(encoding="utf-8")
        self.assertIn("EnvironmentFile=/opt/padiem/chat-com2/.env", backup)
        self.assertIn("--db ${PADIEM_CHAT_LOCAL_DATA_DIR}/chat.sqlite3", backup)
        self.assertIn("--dest ${PADIEM_CHAT_LOCAL_DATA_DIR}/backups", backup)


class CheckConfig(unittest.TestCase):
    def _full_env(self, data):
        return {
            "PADIEM_CHAT_CPYTHON_HOST": "1",
            "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2.padiem.net",
            "PADIEM_CHAT_LOCAL_DATA_DIR": str(data),
            "PADIEM_CHAT_AUTH_MODE": "password",
            "PADIEM_CHAT_COOKIE_SECURE": "true",
            "PADIEM_CHAT_SESSION_SECRET": "x" * 40,
            "PADIEM_CHAT_RUNTIME_MODE": "mock",
        }

    def test_ready_accepts_the_parallel_host_shape_only(self):
        module = load("check_config")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            module.DATA = data
            with unittest.mock.patch.dict(os.environ, self._full_env(data), clear=True):
                self.assertTrue(module.ready())
            for broken in (
                {"PADIEM_LOCAL_DEV": "1"},
                {"PADIEM_CHAT_PUBLIC_BASE_URL": "http://chat-com2.padiem.net"},
                {"PADIEM_CHAT_COOKIE_SECURE": "false"},
                {"PADIEM_CHAT_SESSION_SECRET": "short"},
                {"PADIEM_CHAT_RUNTIME_MODE": "b14"},
                {"PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example"},
            ):
                environment = self._full_env(data)
                environment.update(broken)
                with unittest.mock.patch.dict(os.environ, environment, clear=True):
                    self.assertFalse(module.ready(), broken)

    def test_linux_data_location_is_allowed_and_other_locations_are_refused(self):
        module = load("check_config")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            module.LINUX_DATA = data
            with unittest.mock.patch.dict(os.environ, self._full_env(data), clear=True):
                self.assertTrue(module.ready())
            module.LINUX_DATA = data / "different"
            with unittest.mock.patch.dict(os.environ, self._full_env(data), clear=True):
                self.assertFalse(module.ready())

    def test_multiple_workers_must_pass_the_same_storage_guard_as_launcher(self):
        module = load("check_config")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            module.DATA = data
            environment = {**self._full_env(data), "PADIEM_CHAT_WORKERS": "2"}
            with unittest.mock.patch.dict(os.environ, environment, clear=True), \
                 unittest.mock.patch.object(sys, "path", [str(ROOT / "apps/padiem-chat"), *sys.path]):
                from app import local_server
                with unittest.mock.patch.object(local_server, "validate_worker_configuration", return_value=2) as guard:
                    self.assertTrue(module.ready())
                    guard.assert_called_once_with()
                with unittest.mock.patch.object(local_server, "validate_worker_configuration",
                        side_effect=RuntimeError("multiworker_local_filesystem_required")):
                    self.assertFalse(module.ready())
            with unittest.mock.patch.dict(os.environ, {**environment, "PADIEM_CHAT_WORKERS": "0"}, clear=True):
                self.assertFalse(module.ready())


class Health(unittest.TestCase):
    def test_health_rejects_non_loopback_and_reads_status_ok(self):
        module = load("health")
        self.assertFalse(module.check("http://example.com/health")[0])
        self.assertFalse(module.check("http://127.0.0.1:8798/not-health")[0])
        self.assertFalse(module.check("https://127.0.0.1:8798/health")[0])

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps({"status": "ok"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
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
            db_path = root / "chat.sqlite3"
            db = sqlite3.connect(db_path)
            for table in module.TABLES:
                db.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT)")
                db.execute(f"INSERT INTO {table} VALUES ('one', 'private row text')")
            db.commit()
            db.close()

            dest = root / "backups"
            dest.mkdir()
            for stale in ("chat-20200101T000000Z.sqlite3", "chat-20200102T000000Z.sqlite3"):
                (dest / stale).write_bytes(b"old")

            with unittest.mock.patch("sys.stdout") as output:
                self.assertEqual(module.main(["--db", str(db_path), "--dest", str(dest), "--keep", "2"]), 0)
                printed = "".join(str(call.args[0]) for call in output.write.call_args_list if call.args)
            self.assertIn("CHAT_COM2_BACKUP=PASS", printed)
            self.assertNotIn("private row text", printed)
            kept = sorted(path.name for path in dest.glob("chat-*.sqlite3"))
            self.assertEqual(len(kept), 2)
            self.assertNotIn("chat-20200101T000000Z.sqlite3", kept)


if __name__ == "__main__":
    unittest.main()
