"""#5784 PR-3: the B14 COM2 bundle and its runbook stay consistent.

These are host artifacts, so the failure mode worth preventing is quiet
inconsistency: a unit that starts the port the ingress does not publish, a log
rotation path that no longer matches the unit, an install script that gained a
`systemctl start`, a secret value that arrived in a committed file, or a runbook
that lost the step-ownership split. Each is asserted here rather than trusted.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# The directory is host-com2, not com2: a path component named exactly ``com2``
# is a reserved Windows device name, which git for Windows refuses to index with
# core.protectNTFS (the default) and which ordinary Windows file APIs cannot
# open. The repository is worked on from Windows machines, so the bundle lives
# under a name every platform can read.
BUNDLE = ROOT / "deploy" / "host-com2" / "b14"
RUNBOOK = ROOT / "docs/operations/B14_COM2_RUNBOOK.md"
INVENTORY = ROOT / "docs/architecture/COM2_MIGRATION_INVENTORY_20261025.md"
ENV_EXAMPLE = ROOT / "apps/korean-ai-platform/b14.env.example"

CREDENTIAL_NAMES = tuple(
    "PADIEM_B14_CREDENTIAL_%02d" % index for index in range(1, 15)
) + ("PADIEM_B14_SERVICE_PROOF_SECRET", "PADIEM_GRAFANA_OTLP_TOKEN")
APP_PORT = "8789"


class B14Com2Bundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = (BUNDLE / "padiem-b14.service.example").read_text(encoding="utf-8")
        cls.dropin = (BUNDLE / "20-log-to-file.conf.example").read_text(encoding="utf-8")
        cls.logrotate = (BUNDLE / "logrotate.conf.example").read_text(encoding="utf-8")
        cls.ingress = (BUNDLE / "cloudflared-config.example.yml").read_text(encoding="utf-8")
        cls.install = (BUNDLE / "install.sh").read_text(encoding="utf-8")
        cls.health = (BUNDLE / "health.py").read_text(encoding="utf-8")
        cls.runbook = RUNBOOK.read_text(encoding="utf-8")

    def test_unit_runs_the_adapter_entry_on_the_declared_port(self):
        self.assertIn("ExecStart=/opt/padiem/b14/venv/bin/python /opt/padiem/b14/app/asgi.py", self.unit)
        self.assertIn("Environment=B14_PORT=%s" % APP_PORT, self.unit)
        self.assertIn("Environment=B14_HOST=127.0.0.1", self.unit)
        self.assertIn("EnvironmentFile=-/opt/padiem/b14/env/b14.env", self.unit)
        self.assertIn("WorkingDirectory=/opt/padiem/b14/app", self.unit)
        # Static account, not DynamicUser: the COM2 host rejected the
        # DynamicUser + SupplementaryGroups pair with 216/217.
        self.assertIn("User=padiem-b14", self.unit)
        self.assertIn("Group=padiem-b14", self.unit)
        self.assertNotIn("\nDynamicUser=", self.unit)
        self.assertNotIn("\nSupplementaryGroups=", self.unit)
        self.assertIn("Restart=always", self.unit)
        self.assertIn("ProtectSystem=strict", self.unit)
        # The ledger and logs stay on the declared host paths, not on C:.
        self.assertIn("Environment=B14_CALL_LEDGER_PATH=/opt/padiem/b14/ledger/", self.unit)
        self.assertIn("ReadWritePaths=/opt/padiem/b14/ledger /opt/padiem/b14/logs", self.unit)

    def test_no_credential_value_is_committed_anywhere_in_the_bundle(self):
        text_suffixes = {".example", ".sh", ".py", ".yml", ".conf"}
        # A bundle directory is for host files, not for build output.
        stray = sorted(
            str(path.relative_to(BUNDLE))
            for path in BUNDLE.rglob("*")
            if path.is_file() and path.suffix not in text_suffixes
        )
        self.assertEqual([], stray)
        offenders = []
        for path in sorted(BUNDLE.rglob("*")):
            if not path.is_file() or path.suffix not in text_suffixes:
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                for name in CREDENTIAL_NAMES:
                    if re.search(r"\b%s\s*=\s*\S" % name, line):
                        offenders.append((path.name, name))
        self.assertEqual([], offenders)
        self.assertNotIn("store_id", self.unit + self.install + self.ingress)
        self.assertNotIn("secret_name", self.unit + self.install + self.ingress)

    def test_file_log_mode_and_rotation_agree_with_the_unit(self):
        self.assertIn("StandardOutput=append:/opt/padiem/b14/logs/b14.log", self.dropin)
        self.assertIn("/opt/padiem/b14/logs/*.log {", self.logrotate)
        for directive in ("daily", "rotate 7", "maxsize 50M", "compress", "delaycompress",
                          "missingok", "notifempty", "copytruncate"):
            self.assertIn(directive, self.logrotate)

    def test_ingress_publishes_b14_beside_the_file_lane_in_one_config(self):
        self.assertIn("hostname: b14.padiem.net", self.ingress)
        self.assertIn("service: http://127.0.0.1:%s" % APP_PORT, self.ingress)
        self.assertIn("hostname: files.padiem.net", self.ingress)
        self.assertIn("service: http://127.0.0.1:8788", self.ingress)
        self.assertIn("service: http_status:404", self.ingress)
        # The catch-all must stay last, or every unknown host gets proxied.
        self.assertTrue(self.ingress.rstrip().endswith("http_status:404"))
        self.assertNotIn("tunnel:", self.ingress)

    def test_install_script_never_starts_enables_or_overwrites(self):
        self.assertNotIn("systemctl start", self.install)
        self.assertNotIn("systemctl enable", self.install)
        self.assertNotIn("systemctl restart", self.install)
        self.assertIn("foreign_target", self.install)
        self.assertIn("NO_SERVICE_STARTED=YES", self.install)
        self.assertIn("NO_CREDENTIAL_WRITTEN=YES", self.install)
        self.assertIn("linux_required", self.install)
        self.assertIn("root_required", self.install)
        self.assertIn("asgi_entry_missing", self.install)
        self.assertIn("set -euo pipefail", self.install)

    def test_health_probe_asks_the_same_service_the_unit_starts(self):
        self.assertIn("http://127.0.0.1:%s/health" % APP_PORT, self.health)
        self.assertIn("PADIEM_COM2_B14_HEALTH_V1", self.health)
        self.assertIn('"korean-ai-platform"', self.health)
        # A demo-mode answer is reported as a problem, never as a healthy B14.
        self.assertIn("demo_mode_true", self.health)

    def test_runbook_names_the_owners_and_the_inventoried_secret_names(self):
        self.assertIn("docs/architecture/COM2_MIGRATION_INVENTORY_20261025.md", self.runbook)
        for step in range(1, 6):
            self.assertIn("## Step %d — " % step, self.runbook)
        for actor in ("컴2 아스트라", "Owner", "게이트"):
            self.assertIn(actor, self.runbook)
        self.assertIn("PADIEM_B14_CREDENTIAL_01", self.runbook)
        self.assertIn("PADIEM_B14_CREDENTIAL_14", self.runbook)
        self.assertIn("PADIEM_B14_SERVICE_PROOF_SECRET", self.runbook)
        self.assertIn("B14_UPSTREAM_MODE", self.runbook)
        self.assertIn("cloudflared tunnel --config", self.runbook)
        self.assertIn("`PUBLIC_SERVICES`를 확장", self.runbook)

    def test_inventory_row_records_the_pr_progress(self):
        inventory = INVENTORY.read_text(encoding="utf-8")
        row = next(line for line in inventory.splitlines()
                   if line.startswith("| `ai-revenue-korean-ai-platform`") and "진행:" in line)
        self.assertIn("#5897", row)
        self.assertIn("#5900", row)

    def test_the_inventory_row_is_the_name_source_the_bundle_follows(self):
        inventory = INVENTORY.read_text(encoding="utf-8")
        row = next(line for line in inventory.splitlines()
                   if "`ai-revenue-korean-ai-platform`" in line and "Secrets Store" in line)
        for name in CREDENTIAL_NAMES:
            self.assertIn("`%s`" % name, row)
        self.assertEqual(16, len(CREDENTIAL_NAMES))
        # PR-1 (#5897) ships the name-only example. Asserting it when present keeps
        # this bundle reviewable on its own branch while still pinning the coupling
        # once both land.
        if ENV_EXAMPLE.is_file():
            env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
            for name in CREDENTIAL_NAMES:
                self.assertIn("%s=" % name, env_example)
                self.assertNotRegex(env_example, r"%s=\S" % name)


if __name__ == "__main__":
    unittest.main()
