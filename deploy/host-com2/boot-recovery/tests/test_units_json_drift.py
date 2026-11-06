"""Read-only tests for the boot-recovery units.json drift report."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
CHECKER = HERE / "wsl" / "check_units_json_drift.py"
INSTALLER = HERE / "install.sh"


class UnitsJsonDrift(unittest.TestCase):
    def write_config(self, path: Path, units: list[dict[str, object]]) -> None:
        path.write_text(json.dumps({"units": units}), encoding="utf-8")

    def compare(self, server: Path, example: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(server), str(example)],
            check=True,
            text=True,
            capture_output=True,
            encoding="utf-8",
        )

    def test_equal_unit_names_and_required_values_report_no_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server-units.json"
            example = root / "units.json.example"
            units = [
                {"unit": "padiem-chat-com2.service", "required": True},
                {"unit": "padiem-broker.service", "required": False},
            ]
            self.write_config(server, units)
            self.write_config(example, list(reversed(units)))

            result = self.compare(server, example)

        self.assertEqual(result.stdout, "UNITS_JSON_DRIFT=NO\n")

    def test_different_units_or_required_values_are_reported_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "server-units.json"
            example = root / "units.json.example"
            old_units = [
                {"unit": "padiem-chat-com2.service", "required": False},
                {"unit": "padiem-old.service", "required": True},
            ]
            new_units = [
                {"unit": "padiem-chat-com2.service", "required": True},
                {"unit": "padiem-new.service", "required": False},
            ]
            self.write_config(server, old_units)
            self.write_config(example, new_units)
            original_server = server.read_bytes()

            result = self.compare(server, example)

            self.assertEqual(server.read_bytes(), original_server)

        self.assertIn("UNITS_JSON_DRIFT=YES\n", result.stdout)
        self.assertIn(
            'unit="padiem-chat-com2.service" SERVER_REQUIRED=false EXAMPLE_REQUIRED=true',
            result.stdout,
        )
        self.assertIn(
            'unit="padiem-new.service" SERVER_REQUIRED=MISSING EXAMPLE_REQUIRED=false',
            result.stdout,
        )
        self.assertIn(
            'unit="padiem-old.service" SERVER_REQUIRED=true EXAMPLE_REQUIRED=MISSING',
            result.stdout,
        )

    def test_missing_server_file_reports_drift_and_expected_required_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = root / "not-installed-yet.json"
            example = root / "units.json.example"
            self.write_config(
                example,
                [{"unit": "padiem-chat-com2.service", "required": True}],
            )

            result = self.compare(server, example)

        self.assertIn("UNITS_JSON_DRIFT=YES\n", result.stdout)
        self.assertIn(
            'unit="padiem-chat-com2.service" SERVER_REQUIRED=MISSING EXAMPLE_REQUIRED=true',
            result.stdout,
        )
        self.assertFalse(server.exists())

    def test_installer_seeds_only_a_missing_file_then_runs_the_comparison(self):
        source = INSTALLER.read_text(encoding="utf-8")
        seed = 'if [[ ! -e "$app/units.json" ]]; then install -m 0644'

        self.assertIn(seed, source)
        self.assertIn('"$app/units.json" "$here/wsl/units.json.example"', source)
        self.assertLess(source.index(seed), source.index("check_units_json_drift.py"))


if __name__ == "__main__":
    unittest.main()
