"""Offline staging packaging checks; never install/start a host service."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StagingPackaging(unittest.TestCase):
    def test_installer_is_read_only_by_default_and_bash_syntax_valid(self):
        subprocess.run(["bash", "-n", "install-staging.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install-staging.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("CHAT_STAGING_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("QUEUE_CHANGE=NO", result.stdout)
            self.assertIn("TUNNEL_CHANGE=NO", result.stdout)
        source = (HERE / "install-staging.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        self.assertNotIn("rm -rf", source)
        self.assertIn("QUEUE_SECRET_UNREADABLE", source)

    def test_unit_is_loopback_8801_only_and_never_names_production(self):
        unit = (HERE / "padiem-chat-staging.service").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1", unit)
        self.assertIn("--port 8801", unit)
        self.assertNotIn("0.0.0.0", unit)
        self.assertNotIn("chat.padiem.net", unit)
        self.assertNotIn("8798", unit)
        self.assertIn("ReadWritePaths=/mnt/d/padiem/chat-staging", unit)
        self.assertIn("ReadOnlyPaths=/opt/padiem/mesh-queue-staging", unit)
        self.assertIn("EnvironmentFile=/opt/padiem/chat-staging/.env", unit)

    def test_env_example_carries_names_only_and_the_staging_contract(self):
        text = (HERE / ".env.staging.example").read_text(encoding="utf-8")
        values = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            values[name] = value
            self.assertIn(
                value,
                ("", "1", "true", "false", "mock", "off", "600", "com2",
                 "https://chat-com2-staging.padiem.net",
                 "/mnt/d/padiem/chat-staging",
                 "/mnt/d/padiem/chat-staging/MAINTENANCE",
                 "http://127.0.0.1:8830",
                 "/opt/padiem/mesh-queue-staging/service-secret.txt"),
                name,
            )
        self.assertEqual(values["PC_QUEUE_BACKEND"], "com2")
        self.assertEqual(values["PC_QUEUE_ORIGIN"], "http://127.0.0.1:8830")
        self.assertEqual(values["PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP"], "1")
        self.assertEqual(values["PADIEM_CHAT_SHARED_LOGIN_ENABLED"], "true")
        self.assertEqual(
            values["PC_QUEUE_SERVICE_SECRET_FILE"],
            "/opt/padiem/mesh-queue-staging/service-secret.txt",
        )
        self.assertEqual(values["PADIEM_CHAT_LOCAL_DATA_DIR"], "/mnt/d/padiem/chat-staging")

    def test_scripts_are_staging_only_and_bash_syntax_valid(self):
        for name in ("start-staging.sh", "stop-staging.sh", "status-staging.sh"):
            subprocess.run(["bash", "-n", name], cwd=HERE, check=True)
        start = (HERE / "start-staging.sh").read_text(encoding="utf-8")
        self.assertIn("padiem-chat-staging.service", start)
        self.assertIn("padiem-mesh-queue-staging.service", start)
        self.assertIn("8801", start)
        self.assertNotIn("systemctl enable", start)
        self.assertNotIn("systemctl restart", start)
        self.assertNotIn("padiem-chat-com2.service", start)
        stop = (HERE / "stop-staging.sh").read_text(encoding="utf-8")
        self.assertIn("padiem-chat-staging.service", stop)
        self.assertNotIn("systemctl disable", stop)
        self.assertNotIn("padiem-mesh-queue-staging.service", stop)


class StagingCheckConfig(unittest.TestCase):
    def _full_env(self, data, secret):
        return {
            "PADIEM_CHAT_CPYTHON_HOST": "1",
            "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2-staging.padiem.net",
            "PADIEM_CHAT_LOCAL_DATA_DIR": str(data),
            "PADIEM_CHAT_AUTH_MODE": "password",
            "PADIEM_CHAT_COOKIE_SECURE": "true",
            "PADIEM_CHAT_SESSION_SECRET": "x" * 40,
            "PADIEM_CHAT_RUNTIME_MODE": "mock",
            "PADIEM_CHAT_SHARED_LOGIN_ENABLED": "true",
            "PC_QUEUE_BACKEND": "com2",
            "PC_QUEUE_ORIGIN": "http://127.0.0.1:8830",
            "PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP": "1",
            "PC_QUEUE_SERVICE_SECRET_FILE": str(secret),
        }

    def test_ready_accepts_the_staging_shape_only(self):
        module = load("check_config_staging")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            secret = data / "queue-service-secret.txt"
            secret.write_text("x" * 32, encoding="utf-8")
            module.DATA = data
            with unittest.mock.patch.dict(os.environ, self._full_env(data, secret), clear=True):
                self.assertTrue(module.ready())
            for broken in (
                {"PADIEM_LOCAL_DEV": "1"},
                {"PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net"},
                {"PADIEM_CHAT_COOKIE_SECURE": "false"},
                {"PADIEM_CHAT_SESSION_SECRET": "short"},
                {"PADIEM_CHAT_RUNTIME_MODE": "b14"},
                {"PADIEM_CHAT_SHARED_LOGIN_ENABLED": "false"},
                {"PC_QUEUE_BACKEND": "d1"},
                {"PC_QUEUE_ORIGIN": "http://127.0.0.1:8797"},
                {"PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP": "0"},
                {"PC_QUEUE_SERVICE_SECRET": "inline-secret-is-not-allowed"},
                {"PC_QUEUE_SERVICE_SECRET_FILE": str(data / "missing.txt")},
                {"PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example"},
            ):
                environment = self._full_env(data, secret)
                environment.update(broken)
                with unittest.mock.patch.dict(os.environ, environment, clear=True):
                    self.assertFalse(module.ready(), broken)


if __name__ == "__main__":
    unittest.main()
