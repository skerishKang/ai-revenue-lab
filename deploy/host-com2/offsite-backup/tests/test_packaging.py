"""Offline packaging checks for the offsite-backup kit; never install anything."""
import re
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def test_installer_is_read_only_by_default_and_never_touches_the_key(self):
        subprocess.run(["bash", "-n", "install.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("OFFSITE_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("KEY_CREATED=NO", result.stdout)
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        # The installer checks the key exists and its mode; it never creates,
        # reads or prints the key value.
        self.assertNotIn("token_hex", source)
        self.assertNotIn("/dev/urandom", source)
        self.assertNotIn("cat /etc/padiem/offsite-backup.key", source)

    def test_unit_and_timer_are_bounded(self):
        unit = (HERE / "padiem-offsite-backup.service").read_text(encoding="utf-8")
        self.assertIn("EnvironmentFile=/etc/padiem/offsite-backup.env", unit)
        self.assertIn("ReadOnlyPaths=/mnt/d/padiem /opt/padiem/backups", unit)
        self.assertIn("ReadWritePaths=/var/lib/padiem-offsite-backup", unit)
        self.assertIn("ProtectSystem=strict", unit)
        self.assertNotIn("0.0.0.0", unit)
        timer = (HERE / "padiem-offsite-backup.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=*-*-* 05:10:00", timer)
        self.assertIn("Persistent=true", timer)

    def test_env_example_carries_paths_names_and_numbers_only(self):
        text = (HERE / "offsite-backup.env.example").read_text(encoding="utf-8")
        allowed = {
            "", "7", "4", "com2-2026-11",
            "/etc/padiem/offsite-backup.key",
            "/etc/padiem/r2-offsite-token-id",
            "/etc/padiem/r2-offsite-token-secret",
            "/var/lib/padiem-offsite-backup",
            "/opt/padiem/backups/mesh-queue",
            "/mnt/d/padiem/chat-com2/backups",
            "/mnt/d/padiem/broker/backups",
            "https://<ACCOUNT_ID>.r2.cloudflarestorage.com",
        }
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            name, _, value = line.partition("=")
            self.assertIn(value, allowed, name)

    def test_requirements_are_exact_pins_with_hashes(self):
        text = (HERE / "requirements.txt").read_text(encoding="utf-8")
        pins = [line for line in text.splitlines() if line and not line.startswith(("#", " "))]
        self.assertEqual(len(pins), 3)
        for line in pins:
            self.assertRegex(line, r"^[a-z0-9-]+==\d")
            self.assertTrue(line.endswith("\\"))

    def test_the_tool_never_prints_the_key_and_keeps_the_envelope(self):
        source = (HERE / "offsite.py").read_text(encoding="utf-8")
        self.assertIn("PADIEM-CBE1", (HERE.parents[2] / "scripts" / "ops" / "com2_backup.py").read_text(encoding="utf-8"))
        for line in source.splitlines():
            if "print(" in line:
                lowered = line.lower()
                self.assertNotIn("secret", lowered, line)
                self.assertNotIn("token", lowered, line)
        self.assertIn("decrypt_payload", source)
        self.assertIn("integrity_check", source)
        # A key file path is read, never written.
        self.assertNotIn("write_text(hex", source)


if __name__ == "__main__":
    unittest.main()
