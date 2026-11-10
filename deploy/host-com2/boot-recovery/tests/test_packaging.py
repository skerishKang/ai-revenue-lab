"""Offline packaging checks for the boot-recovery kit; changes nothing on any host."""
import json
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


class Packaging(unittest.TestCase):
    def test_installer_is_dry_run_default_and_does_not_start_or_enable(self):
        subprocess.run(["bash", "-n", "install.sh"], cwd=HERE, check=True)
        for arguments in ([], ["--dry-run"]):
            result = subprocess.run(
                ["bash", "install.sh", *arguments],
                cwd=HERE, check=True, text=True, capture_output=True, encoding="utf-8",
            )
            self.assertIn("BOOT_RECOVERY_INSTALL=DRY_RUN", result.stdout)
            self.assertIn("START_SERVICE=NO", result.stdout)
            self.assertIn("ENABLE_SERVICE=NO", result.stdout)
            self.assertIn("WINDOWS_TASK_CHANGE=NO", result.stdout)
        source = (HERE / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)

    def test_windows_task_script_is_dry_run_unless_apply(self):
        source = (HERE / "windows" / "register-boot-task.ps1").read_text(encoding="utf-8")
        self.assertIn("if (-not $Apply)", source)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", source)
        self.assertIn('UserId "SYSTEM"', source)
        self.assertIn("BOOT_TASK=DRY_RUN", source)
        # Registration happens only after the Apply gate.
        self.assertLess(source.index("if (-not $Apply)"), source.index("Register-ScheduledTask"))

    def test_active_hours_and_wslconfig_checks_are_read_only_by_default(self):
        hours = (HERE / "windows" / "check-active-hours.ps1").read_text(encoding="utf-8")
        self.assertIn("if (-not $Apply)", hours)
        self.assertLess(hours.index("if (-not $Apply)"), hours.index("New-ItemProperty"))
        # 대표 결정 2026-11-08: the nightly restart window is 04:00-10:00, the
        # narrowest the platform allows (active hours are capped at 18h), and a
        # signed-in session must not hold the restart back.
        self.assertIn("$StartHour = 10", hours)
        self.assertIn("$EndHour = 4", hours)
        self.assertIn("NoAutoRebootWithLoggedOnUsers", hours)
        self.assertIn("RESTART_WINDOW=PASS", hours)
        self.assertLess(hours.index("if (-not $Apply)"),
                        hours.index("-Name NoAutoRebootWithLoggedOnUsers -PropertyType"))
        wsl = (HERE / "windows" / "check-wslconfig.ps1").read_text(encoding="utf-8")
        self.assertIn("vmIdleTimeout", wsl)
        self.assertIn("existing file left untouched", wsl)
        self.assertIn("systemd", wsl)

    def test_unit_order_and_notifier_names(self):
        unit = (HERE / "wsl" / "padiem-boot-recovery.service").read_text(encoding="utf-8")
        self.assertIn("After=multi-user.target network-online.target", unit)
        self.assertIn("EnvironmentFile=-/opt/padiem/boot-recovery/.env", unit)
        env = (HERE / "wsl" / "boot-recovery.env.example").read_text(encoding="utf-8")
        for name in ("B66_ALERT_TELEGRAM_BOT_TOKEN", "B66_ALERT_TELEGRAM_CHAT_ID",
                     "B66_ALERT_DISCORD_WEBHOOK_URL"):
            self.assertIn(name, env)
        for line in env.splitlines():
            if line and not line.startswith("#"):
                _, _, value = line.partition("=")
                self.assertIn(value, ("", "240"), line)

    def test_units_example_covers_the_com2_lanes_and_is_valid_json(self):
        data = json.loads((HERE / "wsl" / "units.json.example").read_text(encoding="utf-8"))
        names = {entry["unit"] for entry in data["units"]}
        for expected in (
            "padiem-mesh-queue.service", "padiem-file-lane.service",
            "padiem-oracle-mesh-executor.service", "padiem-connector-watch.service",
            "padiem-chat-com2.service", "padiem-broker.service",
            "cloudflared-padiem.service", "cloudflared-chat-com2.service",
            "padiem-meshcentral.service",
            "padiem-offsite-backup.timer", "padiem-chat-com2-backup.timer",
            "padiem-broker-backup.timer",
        ):
            self.assertIn(expected, names)
        health = {entry["name"] for entry in data["health"]}
        self.assertIn("chat", health)
        # #6895 patrol: connector-watch.service is Type=oneshot fired by its
        # timer, so it is inactive between runs and must never be a required
        # service check; the timer carries the requirement.
        by_name = {entry["unit"]: entry for entry in data["units"]}
        self.assertTrue(by_name["padiem-p01.service"]["required"])
        self.assertFalse(by_name["padiem-b14.service"]["required"])
        self.assertFalse(by_name["padiem-connector-watch.service"]["required"])
        self.assertTrue(by_name["padiem-connector-watch.timer"]["required"])

    def test_self_check_never_restarts_anything(self):
        source = (HERE / "wsl" / "boot_recovery.py").read_text(encoding="utf-8")
        for forbidden in ("systemctl restart", "systemctl start", "systemctl stop", "systemctl enable"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("sqlite3", source)

    def test_restart_and_backup_defaults_match_the_shipped_files(self):
        """The window policy and the backup anchors live in the shipped files.

        #7404: the one-pager and the runbook moved to the private operations
        records, so the window/backup rules are asserted against the deploy
        files that actually run them.
        """
        hours = (HERE / "windows" / "check-active-hours.ps1").read_text(encoding="utf-8")
        self.assertIn("$StartHour = 10", hours)
        self.assertIn("$EndHour = 4", hours)
        self.assertIn("NoAutoRebootWithLoggedOnUsers", hours)
        boot = (HERE / "wsl" / "boot_recovery.py").read_text(encoding="utf-8")
        self.assertIn("padiem-chat-com2-backup.timer", boot)
        offsite = (HERE.parent / "offsite-backup" / "offsite.py").read_text(encoding="utf-8")
        self.assertIn('"/mnt/d/padiem/chat-com2/backups"', offsite)
        restore = (HERE.parent / "offsite-backup" / "run_live_chat_restore.sh").read_text(
            encoding="utf-8")
        self.assertIn("offsite.py restore", restore)


class PowerShellSyntax(unittest.TestCase):
    def test_powershell_files_parse_when_pwsh_is_available(self):
        executable = None
        for candidate in ("pwsh", "powershell"):
            try:
                subprocess.run([candidate, "-NoProfile", "-Command", "exit 0"],
                               check=True, capture_output=True)
                executable = candidate
                break
            except (OSError, subprocess.CalledProcessError):
                continue
        if executable is None:
            self.skipTest("no PowerShell runtime on this runner")
        for name in ("register-boot-task.ps1", "check-active-hours.ps1", "check-wslconfig.ps1"):
            path = HERE / "windows" / name
            script = (
                "$errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile("
                f"'{path.as_posix()}', [ref]$null, [ref]$errors) | Out-Null; "
                "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 } exit 0"
            )
            result = subprocess.run([executable, "-NoProfile", "-Command", script],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr or result.stdout}")


if __name__ == "__main__":
    unittest.main()
