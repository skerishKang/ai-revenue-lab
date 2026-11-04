"""Offline packaging checks for the mesh-queue-backup kit; never install anything."""
import re
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def test_installer_is_dry_run_by_default_and_never_starts_or_enables(self):
        subprocess.run(["bash", "-n", "install.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("MESH_QUEUE_BACKUP_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("DB_TOUCHED=NO", result.stdout)
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        # The kit never touches the queue database; the script's own read-only
        # SQLite access is the only path to it.
        self.assertNotIn("sqlite3", source)

    def test_backup_script_matches_the_host_contract(self):
        script = (HERE / "backup.sh").read_text(encoding="utf-8")
        # Configuration comes from the three environment names and their
        # documented defaults — never from embedded credentials or hosts.
        for name in ("MESH_QUEUE_DB_PATH", "MESH_QUEUE_BACKUP_DIR", "MESH_QUEUE_BACKUP_KEEP"):
            self.assertIn(name, script)
        self.assertIn("VACUUM INTO", script)
        self.assertIn("PRAGMA integrity_check", script)
        self.assertIn("mode=ro", script)
        for secret_mark in ("password", "token", "secret", "api_key"):
            self.assertNotRegex(script.lower(), secret_mark)

    def test_unit_and_timer_match_the_installed_host_files(self):
        unit = (HERE / "padiem-mesh-queue-backup.service").read_text(encoding="utf-8")
        self.assertIn("Type=oneshot", unit)
        self.assertIn("User=padiem-mesh", unit)
        self.assertIn("ExecStart=/opt/padiem/mesh-queue/backup.sh", unit)
        self.assertNotIn("0.0.0.0", unit)
        timer = (HERE / "padiem-mesh-queue-backup.timer").read_text(encoding="utf-8")
        self.assertIn("OnCalendar=04:35", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("WantedBy=timers.target", timer)

    def test_readme_carries_the_restore_checklist_line(self):
        readme = (HERE / "README.md").read_text(encoding="utf-8")
        self.assertIn("백업 스크립트 존재와 실행 권한 확인", readme)
        self.assertIn("install.sh --apply", readme)


if __name__ == "__main__":
    unittest.main()
