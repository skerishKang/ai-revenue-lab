"""Offline packaging checks for the restart-policy drop-in (#4953 A)."""
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = HERE.parent


class Packaging(unittest.TestCase):
    def test_dropin_is_exactly_the_reviewed_policy(self):
        text = (POLICY / "10-padiem-restart.conf").read_text(encoding="utf-8")
        self.assertEqual(
            text,
            "[Unit]\nStartLimitIntervalSec=0\n\n[Service]\nRestart=always\nRestartSec=10\n",
        )

    def test_units_list_covers_com2_lanes_and_excludes_timers_and_oneshots(self):
        names = [
            line.strip() for line in (POLICY / "units.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for expected in (
            "padiem-mesh-queue.service", "padiem-file-lane.service",
            "padiem-oracle-mesh-executor.service", "padiem-connector-watch.service",
            "padiem-chat-com2.service", "padiem-broker.service",
            "cloudflared.service", "meshcentral.service",
            # 컴2's tunnel and MeshCentral units carry these names; a host applies only
            # the ones it actually has and reports the rest as SKIPPED_MISSING.
            "cloudflared-padiem.service", "padiem-meshcentral.service",
        ):
            self.assertIn(expected, names)
        self.assertFalse([name for name in names if name.endswith(".timer")])
        self.assertNotIn("padiem-boot-recovery.service", names)

    def test_installer_is_dry_run_by_default_and_never_touches_a_running_unit(self):
        subprocess.run(["bash", "-n", "install.sh"], cwd=POLICY, check=True)
        result = subprocess.run(
            ["bash", "install.sh"], cwd=POLICY, check=True, text=True,
            capture_output=True, encoding="utf-8",
        )
        self.assertIn("RESTART_POLICY=DRY_RUN", result.stdout)
        self.assertIn("START_SERVICE=NO", result.stdout)
        self.assertIn("RESTART_SERVICE=NO", result.stdout)
        self.assertIn("UNIT=padiem-chat-com2.service", result.stdout)
        source = (POLICY / "install.sh").read_text(encoding="utf-8")
        for forbidden in ("systemctl start", "systemctl restart", "systemctl stop",
                          "systemctl enable", "systemctl disable"):
            self.assertNotIn(forbidden, source)
        # Only existing units receive a drop-in; a missing one is reported.
        self.assertIn("SKIPPED_MISSING", source)
        self.assertIn("daemon-reload", source)


if __name__ == "__main__":
    unittest.main()
