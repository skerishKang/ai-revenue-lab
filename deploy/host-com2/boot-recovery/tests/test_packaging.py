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
            "cloudflared.service", "meshcentral.service",
            "padiem-offsite-backup.timer", "padiem-chat-com2-backup.timer",
            "padiem-broker-backup.timer",
        ):
            self.assertIn(expected, names)
        health = {entry["name"] for entry in data["health"]}
        self.assertIn("chat", health)
        self.assertIn("broker", health)

    def test_self_check_never_restarts_anything(self):
        source = (HERE / "wsl" / "boot_recovery.py").read_text(encoding="utf-8")
        for forbidden in ("systemctl restart", "systemctl start", "systemctl stop", "systemctl enable"):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("sqlite3", source)


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
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, f"{name}: {result.stderr or result.stdout}")


if __name__ == "__main__":
    unittest.main()
