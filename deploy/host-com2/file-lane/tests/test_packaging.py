"""Offline packaging checks; never install/start a host service."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Packaging(unittest.TestCase):
    def test_installer_is_read_only_by_default_and_bash_syntax_valid(self):
        subprocess.run(["bash", "-n", str(HERE / "install.sh")], check=True)
        for arguments in [[], ["--dry-run"]]:
            result = subprocess.run(["bash", str(HERE / "install.sh"), *arguments], check=True, text=True, capture_output=True)
            self.assertIn("FILE_LANE_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("TUNNEL_CHANGE=NO", result.stdout)
        source = (HERE / "install.sh").read_text()
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("rm -rf", source)
        self.assertIn('if [[ ! -e "$app/.env" ]]', source)
        self.assertIn("--require-hashes", source)
        self.assertIn('"$source_root/packages/padiem-ai-core"', source)

    def test_checkout_paths_avoid_windows_reserved_device_names(self):
        self.assertEqual(HERE.relative_to(ROOT).parts, ("deploy", "host-com2", "file-lane"))
        reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}
        for path in HERE.rglob("*"):
            for part in path.relative_to(ROOT).parts:
                self.assertNotIn(part.split(".")[0].upper(), reserved)

    def test_unit_matches_the_actual_host_contract(self):
        source = (HERE / "padiem-file-lane.service").read_text()
        for value in ["EnvironmentFile=/opt/padiem/file-lane/.env", "Environment=FILE_LANE_ROOT=/mnt/d/padiem/file-lane",
                      "Environment=FILE_LANE_PORT=8788", "Restart=always", "User=padiem-file-lane",
                      "ExecStart=/opt/padiem/file-lane/venv/bin/python -m padiem_file_lane",
                      "ConditionPathIsMountPoint=/mnt/d", "ReadWritePaths=/mnt/d/padiem/file-lane"]:
            self.assertIn(value, source)
        self.assertNotIn("8789", source)
        self.assertNotIn("oracle-mesh", source)
        self.assertNotIn("cloudflared", source)

    def test_systemd_unit_syntax_without_installing_or_starting_it(self):
        binary = shutil.which("systemd-analyze")
        if not binary:
            self.skipTest("systemd-analyze unavailable on this development host")
        with tempfile.TemporaryDirectory() as temporary:
            unit = Path(temporary) / "padiem-file-lane.service"
            # Verify actual unit directives. Only substitute the interpreter
            # path so verify can find an executable on a non-COM2 CI runner.
            unit.write_text((HERE / unit.name).read_text().replace("/opt/padiem/file-lane/venv/bin/python", sys.executable))
            result = subprocess.run([binary, "verify", "--man=no", str(unit)], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_environment_example_has_only_names_and_no_values(self):
        assignments = (HERE / ".env.example").read_text().splitlines()
        self.assertEqual(set(assignments), {"FILE_LANE_TICKET_SECRET=", "FILE_LANE_ALLOWED_ORIGINS="})

    def test_preflight_checks_settings_without_printing_values(self):
        module = load("check_config")
        private = "offline-test-never-print-this-value-000000000000"
        env = {"FILE_LANE_TICKET_SECRET": private, "FILE_LANE_ROOT": "/mnt/d/padiem/file-lane",
               "FILE_LANE_HOST": "127.0.0.1", "FILE_LANE_PORT": "8788"}
        with patch.dict(os.environ, env, clear=True), patch.object(module.Path, "is_dir", return_value=True), patch.object(module.os, "access", return_value=True):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertTrue(module.ready())
                with patch.dict(os.environ, {"FILE_LANE_TICKET_SECRET": ""}):
                    self.assertFalse(module.ready())
                with patch.dict(os.environ, {"FILE_LANE_ROOT": "/tmp/not-the-hdd"}):
                    self.assertFalse(module.ready())
                with patch.dict(os.environ, {"FILE_LANE_HOST": "0.0.0.0"}):
                    self.assertFalse(module.ready())
            self.assertNotIn(private, output.getvalue())

    def test_health_is_one_read_only_request_and_never_echoes_body(self):
        private = "fixture-document-header-never-print"
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                self.send_response(self.server.response_status)
                self.send_header("X-Fixture", private)
                if self.server.response_status == 302:
                    self.send_header("Location", "https://not-contacted.example/" + private)
                self.end_headers()
                self.wfile.write(self.server.response_body)
            def log_message(self, *args):
                pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.response_body = b'{"ok":true}'
        server.response_status = 200
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            target = f"http://127.0.0.1:{server.server_port}/health"
            cases = [(200, b'{"ok":true}', True), (200, private.encode(), False), (302, private.encode(), False)]
            for index, (status, body, expected) in enumerate(cases, 1):
                server.response_status, server.response_body = status, body
                result = subprocess.run([sys.executable, str(HERE / "health.py"), "--url", target], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0 if expected else 1)
                self.assertEqual(json.loads(result.stdout), {"health_ok": expected, "status_code": status})
                self.assertEqual(requests, ["/health"] * index)  # no retry/redirect
                self.assertNotIn(target, result.stdout + result.stderr)
                self.assertNotIn(private, result.stdout + result.stderr)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_health_refuses_credential_urls_and_unapproved_plaintext(self):
        module = load("health")
        for value in ["https://user:private@example.test/health", "http://example.test/health", "https://example.test/health?token=private"]:
            with patch.object(module.urllib.request, "build_opener") as opener:
                self.assertEqual(module.check(value), (False, 0))
                opener.assert_not_called()

    def test_runtime_requirements_match_the_committed_service_lock(self):
        result = subprocess.run(["uv", "export", "--project", "apps/padiem-file-lane", "--frozen", "--no-dev", "--no-emit-project", "--no-emit-package", "padiem-ai-core", "--no-header"],
                                cwd=ROOT, check=True, capture_output=True, text=True)
        self.assertEqual((HERE / "requirements.txt").read_text(), result.stdout)


if __name__ == "__main__":
    unittest.main()
