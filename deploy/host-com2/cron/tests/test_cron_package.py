"""Offline packaging checks for the COM2 cron timer; never install/start a service.

The bash child renders into a *relative* directory inside this package folder: a
bash started from Python can be a different installation (MSYS vs WSL) whose
absolute roots differ, and absolute paths would then point at two places. No
host unit is installed, no timer is started and Cloudflare is never contacted.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = sys.executable
SCHEDULE = "*-*-* *:00/15:00"
MARKERS = ("===SERVICE===", "===TIMER===", "===APP===")


def load_gate():
    spec = importlib.util.spec_from_file_location("check_config_cron", HERE / "check_config_cron.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_bash(script, *arguments, env=None):
    return subprocess.run(
        ["bash", script, *arguments],
        cwd=HERE,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def bash_script(body):
    return subprocess.run(
        ["bash", "-c", body],
        cwd=HERE,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def render(profile, schedule=SCHEDULE):
    work = f".cron-render-{os.getpid()}"
    shutil.rmtree(HERE / work, ignore_errors=True)
    script = "\n".join([
        "set -euo pipefail",
        f"bash install-cron.sh --profile {profile} --schedule '{schedule}' "
        f'--render-dir "{work}/units" --app-root "{work}/app" --apply',
        'echo "===SERVICE==="',
        f'cat "{work}/units/"*.service',
        'echo "===TIMER==="',
        f'cat "{work}/units/"*.timer',
        'echo "===APP==="',
        f'ls -1 "{work}/app"',
    ])
    result = bash_script(script)
    sections, current = {}, None
    for line in result.stdout.splitlines():
        if line in MARKERS:
            current = line.strip("=")
            sections[current] = []
        elif current:
            sections[current].append(line)
    app_files = [line.strip() for line in sections.get("APP", []) if line.strip()]
    shutil.rmtree(HERE / work, ignore_errors=True)
    return (
        result,
        "\n".join(sections.get("SERVICE", [])),
        "\n".join(sections.get("TIMER", [])),
        app_files,
    )


class ShellPackaging(unittest.TestCase):
    def test_scripts_are_syntax_valid(self):
        for script in ("run-cron.sh", "install-cron.sh", "status-cron.sh"):
            subprocess.run(["bash", "-n", script], cwd=HERE, check=True)

    def test_installer_dry_run_by_default_and_never_changes_state(self):
        result = run_bash("install-cron.sh", "--profile", "staging", "--schedule", SCHEDULE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CRON_INSTALL=DRY_RUN", result.stdout)
        self.assertIn("START_SERVICE=NO", result.stdout)
        self.assertIn("ENABLE_SERVICE=NO", result.stdout)
        self.assertIn("CLOUDFLARE_CHANGE=NO", result.stdout)
        self.assertIn("ENV_FILE_EDIT=NO", result.stdout)

        source = (HERE / "install-cron.sh").read_text(encoding="utf-8")
        self.assertNotIn("systemctl start", source)
        self.assertNotIn("systemctl enable", source)
        self.assertIn("daemon-reload", source)

    def test_installer_refuses_without_a_schedule(self):
        result = run_bash("install-cron.sh", "--profile", "staging")
        self.assertEqual(result.returncode, 2)
        self.assertIn("reason=CRON_SCHEDULE_REQUIRED", result.stderr)
        self.assertIn("dashboard-owned", result.stderr)

        missing = run_bash("install-cron.sh", "--profile", "nowhere", "--schedule", SCHEDULE)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("reason=profile_missing", missing.stderr)

    def test_staging_render_is_profile_scoped(self):
        result, service, timer, app_files = render("staging")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertIn("Type=oneshot", service)
        self.assertIn("User=padiem-chat", service)
        self.assertIn("EnvironmentFile=/opt/padiem/chat-staging/.env", service)
        self.assertIn("Environment=CRON_PROFILE=staging", service)
        # --app-root is a relative test directory, so this check is structural:
        # the unit runs the app venv python against the copied gate and runner.
        self.assertIn("/venv/bin/python", service)
        self.assertIn("check_config_cron.py", service)
        self.assertIn("run-cron.sh", service)
        self.assertIn("ReadWritePaths=/mnt/d/padiem/chat-staging", service)
        self.assertIn("RuntimeDirectory=padiem-chat-cron", service)
        self.assertNotIn("8797", service)
        self.assertNotIn("chat-com2", service)
        self.assertNotIn("0.0.0.0", service)

        self.assertIn(f"OnCalendar={SCHEDULE}", timer)
        self.assertIn("Persistent=false", timer)
        self.assertIn("Unit=padiem-chat-cron-staging.service", timer)

        for copied in ("run-cron.sh", "check_config_cron.py", "status-cron.sh", "README-cron.md"):
            self.assertIn(copied, app_files)

    def test_production_render_uses_com2_paths_and_queue(self):
        result, service, timer, _app_files = render("production")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertIn("EnvironmentFile=/opt/padiem/chat-com2/.env", service)
        self.assertIn("ReadWritePaths=/mnt/d/padiem/chat-com2", service)
        self.assertIn("Environment=CRON_EXPECTED_QUEUE_ORIGIN=http://127.0.0.1:8797", service)
        self.assertIn("Environment=CRON_PROFILE=production", service)
        self.assertNotIn("chat-staging", service)
        self.assertIn("Unit=padiem-chat-cron-com2.service", timer)

    def test_status_script_is_read_only(self):
        source = (HERE / "status-cron.sh").read_text(encoding="utf-8")
        for forbidden in ("systemctl start", "systemctl enable", "systemctl stop", "rm -f"):
            self.assertNotIn(forbidden, source)
        self.assertIn("padiem-chat-cron-staging", source)
        self.assertIn("padiem-chat-cron-com2", source)

    def test_env_example_carries_names_only(self):
        text = (HERE / "cron.env.example").read_text(encoding="utf-8")
        filled = [
            line.split("=", 1)[0]
            for line in text.splitlines()
            if line and not line.startswith("#") and "=" in line and not line.endswith("=")
        ]
        # Only the two reviewed constants may carry a value.
        self.assertEqual(
            sorted(filled),
            ["PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED", "PADIEM_CHAT_CPYTHON_HOST"],
        )


class ConfigGate(unittest.TestCase):
    def _env(self, data_root, profile="staging", **overrides):
        base = {
            "CRON_PROFILE": profile,
            "PADIEM_CHAT_CPYTHON_HOST": "1",
            "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "true",
            "PADIEM_CHAT_LOCAL_DATA_DIR": str(data_root),
            "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2-staging.padiem.net",
            "PADIEM_CHAT_SESSION_SECRET": "x" * 40,
            "PC_QUEUE_ORIGIN": "http://127.0.0.1:8830",
            "CRON_EXPECTED_DATA_ROOT": str(data_root),
            "CRON_EXPECTED_QUEUE_ORIGIN": "http://127.0.0.1:8830",
        }
        base.update(overrides)
        return {key: value for key, value in base.items() if value is not None}

    def _ready(self, env, data_root):
        module = load_gate()
        module.PROFILES["staging"]["data_root"] = str(data_root)
        module.PROFILES["production"]["data_root"] = str(data_root)
        saved = dict(os.environ)
        os.environ.clear()
        os.environ.update(env)
        try:
            return module.ready()
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_staging_shape_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._ready(self._env(tmp), tmp), (True, "ready"))

    def test_production_shape_is_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(
                tmp, profile="production",
                **{
                    "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat.padiem.net",
                    "PC_QUEUE_ORIGIN": "http://127.0.0.1:8797",
                    "CRON_EXPECTED_QUEUE_ORIGIN": "http://127.0.0.1:8797",
                },
            )
            self.assertEqual(self._ready(env, tmp), (True, "ready"))

    def test_refusals_are_stable_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                ({"CRON_PROFILE": "nowhere"}, "profile_unknown"),
                ({"PADIEM_CHAT_CPYTHON_HOST": "0"}, "host_flag_off"),
                ({"PADIEM_LOCAL_DEV": "1"}, "local_dev_on"),
                ({"PADIEM_CHAT_LOCAL_DATA_DIR": "/tmp/elsewhere"}, "data_root_mismatch"),
                ({"CRON_EXPECTED_DATA_ROOT": "/mnt/d/padiem/chat-com2"}, "unit_data_root_mismatch"),
                ({"PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "false"}, "automation_scheduler_disabled"),
                ({"PADIEM_CHAT_PUBLIC_BASE_URL": "http://chat-com2-staging.padiem.net"}, "public_origin_mismatch"),
                ({"PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2-staging.padiem.net/"}, "public_origin_mismatch"),
                ({"PADIEM_CHAT_SESSION_SECRET": "short"}, "session_secret_short"),
                ({"PC_QUEUE_ORIGIN": "http://127.0.0.1:8797"}, "queue_origin_mismatch"),
                ({"CRON_EXPECTED_QUEUE_ORIGIN": "http://127.0.0.1:8831"}, "unit_queue_origin_mismatch"),
            ]
            for override, expected in cases:
                with self.subTest(reason=expected):
                    ok, reason = self._ready(self._env(tmp, **override), tmp)
                    self.assertFalse(ok)
                    self.assertEqual(reason, expected)

    def test_missing_data_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "not-there")
            self.assertEqual(self._ready(self._env(missing), missing), (False, "data_root_unusable"))

    def test_cli_prints_reason_without_values(self):
        secret = "s" * 40
        env = {
            "PATH": os.environ.get("PATH", ""),
            "CRON_PROFILE": "nowhere",
            "PADIEM_CHAT_SESSION_SECRET": secret,
        }
        result = subprocess.run(
            [PY, "check_config_cron.py"],
            cwd=HERE, text=True, capture_output=True, encoding="utf-8",
            errors="replace", env=env,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("CRON_CONFIG_READY=0 reason=profile_unknown", result.stdout)
        self.assertNotIn(secret, result.stdout + result.stderr)


@unittest.skipUnless(shutil.which("flock"), "flock is provided by util-linux")
class TickRunner(unittest.TestCase):
    TICK = """
set -uo pipefail
work=.cron-tick-$$
rm -rf "$work"
mkdir -p "$work/app/venv/bin"
cat > "$work/app/venv/bin/python" <<'FAKE'
#!/usr/bin/env bash
sleep {sleep}
echo "FAKE_LOCAL_CRON=${{*:-none}}"
exit {exit_code}
FAKE
chmod +x "$work/app/venv/bin/python"
export CRON_PROFILE=staging
export CRON_APP_ROOT="$work/app"
export CRON_LOCK_FILE="$work/cron.lock"
export CHAT_CRON_PYTHON="$work/app/venv/bin/python"
{body}
rm -rf "$work"
"""

    def _script(self, body, sleep=0.0, exit_code=0):
        return self.TICK.format(sleep=sleep, exit_code=exit_code, body=body)

    def test_second_tick_is_skipped_while_the_first_runs(self):
        body = "\n".join([
            'bash run-cron.sh > "$work/first.log" 2>&1 &',
            "first=$!",
            "sleep 0.4",
            "bash run-cron.sh",
            'echo "SECOND_RC=$?"',
            "wait $first",
            'echo "===FIRST==="',
            'cat "$work/first.log"',
        ])
        result = bash_script(self._script(body, sleep=1.2))
        out = result.stdout
        self.assertIn("CHAT_CRON_RUN=SKIPPED reason=previous_run_active", out)
        self.assertIn("SECOND_RC=0", out)
        self.assertIn("===FIRST===", out)
        self.assertIn("CHAT_CRON_TICK=START profile=staging", out)
        self.assertIn("FAKE_LOCAL_CRON=-m app.local_cron --once", out)
        self.assertIn("CHAT_CRON_TICK=END profile=staging status=0", out)

    def test_failure_status_is_reported_and_propagated(self):
        body = "\n".join(["bash run-cron.sh", 'echo "RC=$?"'])
        result = bash_script(self._script(body, exit_code=3))
        self.assertIn("CHAT_CRON_TICK=END profile=staging status=3", result.stdout)
        self.assertIn("RC=3", result.stdout)

    def test_missing_app_root_does_not_claim_a_tick(self):
        body = "\n".join([
            'export CRON_APP_ROOT="$work/not-there"',
            "bash run-cron.sh",
            'echo "RC=$?"',
        ])
        result = bash_script(self._script(body))
        combined = result.stdout + result.stderr
        self.assertIn("reason=app_root_missing", combined)
        self.assertIn("RC=1", result.stdout)
        self.assertNotIn("status=0", result.stdout)

    def test_runner_never_touches_cloudflare_or_units(self):
        source = (HERE / "run-cron.sh").read_text(encoding="utf-8")
        for forbidden in ("systemctl", "wrangler", "cloudflare", "deploy"):
            self.assertNotIn(forbidden, source.lower())


class CutoverRules(unittest.TestCase):
    def test_readme_states_the_double_tick_order(self):
        text = (HERE / "README.md").read_text(encoding="utf-8")
        self.assertIn("Cloudflare side off", text)
        self.assertIn("COM2 timer on", text)
        self.assertIn("Rollback", text)
        self.assertIn("not preventable by this package", text)
        self.assertIn("PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED", text)
        self.assertIn("wrangler.toml", text)
        self.assertIn("no `[triggers]`", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
