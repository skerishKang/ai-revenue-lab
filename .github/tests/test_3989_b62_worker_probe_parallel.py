"""#3989: keep four REAL Worker/Pyodide probes under one concurrent, fail-closed job."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
SCRIPTS = ROOT / ".github/scripts"
RUNNER = SCRIPTS / "b62_worker_probe_parallel.sh"
PROBES = {
    "timeout": ("WORKER_TIMEOUT_RUNTIME_PASS", 8787, 9231, ".runtime-timeout-probe.toml"),
    "web_transport": ("WORKER_WEB_TRANSPORT_PASS", 8788, 9232, ".runtime-web-transport-probe.toml"),
    "p01_binding": ("WORKER_P01_BINDING_COMPOSITION_PASS", 8789, 9233, ".runtime-p01-binding-probe.toml"),
    "r2_read": ("WORKER_R2_OBJECTBODY_READ_PASS", 8790, 9234, ".runtime-r2-read-probe.toml"),
}


class WorkerProbeParallelContract(unittest.TestCase):
    def test_all_original_real_runtime_probes_retained(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Real Worker/Pyodide probes (all four, parallel, fail-closed)", workflow)
        self.assertIn("bash ../../.github/scripts/b62_worker_probe_parallel.sh", workflow)
        self.assertIn("test_3989_b62_worker_probe_parallel.py", workflow)
        self.assertIn("Prove Core vendored for Python Worker", workflow)
        self.assertIn("Python Worker bundle dry-run", workflow)
        self.assertNotIn("      - name: Real Worker/Pyodide timeout runtime probe", workflow)
        self.assertEqual(len({item[1] for item in PROBES.values()}), 4)
        self.assertEqual(len({item[2] for item in PROBES.values()}), 4)
        for name, (marker, port, inspector, config) in PROBES.items():
            script = (SCRIPTS / f"b62_worker_probe_{name}.sh").read_text(encoding="utf-8")
            self.assertIn("npx --yes wrangler@4.130.0 dev", script)
            self.assertIn(f"--port {port}", script)
            self.assertIn(f"--inspector-port {inspector}", script)
            self.assertIn(config, script)
            self.assertIn("trap cleanup EXIT", script)
            self.assertIn(marker, script)
            self.assertIn("set -euo pipefail", script)
            self.assertIn("exit 1", script)
        self.assertIn("Pywrangler dependency sync from committed pylock", workflow)
        self.assertLess(
            workflow.index("Pywrangler dependency sync from committed pylock"),
            workflow.index("Real Worker/Pyodide probes (all four, parallel, fail-closed)"),
        )
        self.assertLess(
            workflow.index("Real Worker/Pyodide probes (all four, parallel, fail-closed)"),
            workflow.index("Python Worker bundle dry-run"),
        )

    def test_runner_waits_for_every_child_and_fails_if_one_fails(self):
        with tempfile.TemporaryDirectory(prefix="b62-worker-parallel-") as directory:
            temp = Path(directory)
            marker = temp / "started.log"
            scripts = []
            for i in range(4):
                script = temp / f"probe{i}.sh"
                script.write_text(
                    "#!/usr/bin/env bash\n"
                    f"printf '%s\\n' 'probe{i}' >> '{marker}'\n"
                    "exit 7\n" if i == 2 else
                    "#!/usr/bin/env bash\n"
                    f"printf '%s\\n' 'probe{i}' >> '{marker}'\n"
                    "exit 0\n",
                    encoding="utf-8",
                )
                scripts.append(str(script))
            failure = subprocess.run(
                ["bash", str(RUNNER), *scripts], capture_output=True, text=True,
                cwd=temp, timeout=15, check=False,
            )
            self.assertNotEqual(failure.returncode, 0)
            self.assertIn("B62_WORKER_PROBES=FAIL", failure.stderr)
            self.assertIn("B62_WORKER_PROBE_2=FAIL", failure.stderr)
            self.assertIn("B62_WORKER_PROBE_COUNT=4", failure.stdout)
            self.assertEqual(set(marker.read_text(encoding="utf-8").splitlines()),
                             {f"probe{i}" for i in range(4)})
            self.assertIn("B62_WORKER_PROBE_0=PASS", failure.stdout)
            self.assertIn("B62_WORKER_PROBE_3=PASS", failure.stdout)
            for script in scripts:
                Path(script).write_text("exit 0\n", encoding="utf-8")
            passed = subprocess.run(
                ["bash", str(RUNNER), *scripts], capture_output=True, text=True,
                cwd=temp, timeout=15, check=False,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)
            self.assertIn("B62_WORKER_PROBES=PASS", passed.stdout)

    def test_runner_fails_on_invalid_or_missing_probe_argument(self):
        for args in [["x"], ["/tmp/b62-not-existent-probe.sh"] * 4]:
            with self.subTest(args=args):
                result = subprocess.run(
                    ["bash", str(RUNNER), *args], capture_output=True,
                    text=True, timeout=10, check=False,
                )
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
