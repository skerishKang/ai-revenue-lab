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
PREWARM = SCRIPTS / "b62_worker_prewarm_overlap.sh"
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
            # Real probes execute concurrently on one runner. Separate ports
            # alone did not prevent workerd SQLite lock collisions (#3989).
            # Every invocation must receive a unique mktemp-backed local state
            # directory and remove only that directory at exit.
            self.assertIn('PERSIST_DIR="$(mktemp -d ', script)
            self.assertIn(f"b62-worker-{name}-state.XXXXXXXX", script)
            self.assertIn('--persist-to "$PERSIST_DIR"', script)
            self.assertIn('rm -rf -- "$PERSIST_DIR"', script)
            self.assertIn(config, script)
            self.assertIn("trap cleanup EXIT", script)
            self.assertIn(marker, script)
            self.assertIn("set -euo pipefail", script)
            self.assertIn("exit 1", script)
        self.assertIn("b62_worker_prewarm_overlap.sh", workflow)
        self.assertIn('B62_WORKER_NPX_PREWARMED=1', PREWARM.read_text(encoding="utf-8"))
        self.assertIn('B62_WORKER_NPX_PREWARM=VERIFIED_PRIOR_STEP', RUNNER.read_text(encoding="utf-8"))
        self.assertIn('npx --yes wrangler@4.130.0 --version', PREWARM.read_text(encoding="utf-8"))
        self.assertIn('uv run --locked pywrangler sync --force', PREWARM.read_text(encoding="utf-8"))
        self.assertIn("B62_WORKER_OVERLAP=FAIL", PREWARM.read_text(encoding="utf-8"))
        self.assertIn("B62_WORKER_OVERLAP=PASS", PREWARM.read_text(encoding="utf-8"))
        self.assertIn("Pywrangler dependency sync from committed pylock", workflow)
        self.assertLess(
            workflow.index("Pywrangler dependency sync from committed pylock"),
            workflow.index("Real Worker/Pyodide probes (all four, parallel, fail-closed)"),
        )
        self.assertLess(
            workflow.index("Real Worker/Pyodide probes (all four, parallel, fail-closed)"),
            workflow.index("Python Worker bundle dry-run"),
        )

    def test_each_real_probe_reports_phase_boundaries_without_changing_assertions(self):
        # Linux CI phase markers distinguish Workerd/Pyodide start from the
        # actual HTTP and Python assertion work, with no probe or gate skipped.
        phases = ("START", "WORKER_LAUNCHED", "READY",
                  "REQUEST_START", "RESPONSE", "ASSERT_PASS")
        for name, (success, _, _, _) in PROBES.items():
            with self.subTest(name=name):
                source_path = SCRIPTS / f"b62_worker_probe_{name}.sh"
                script = source_path.read_text(encoding="utf-8")
                label = name.upper()
                self.assertIn(f"B62_PROBE_TIMING_LABEL={label}", script)
                self.assertIn("B62_WORKER_PHASE_%s_%s_MS=%s", script)
                self.assertIn('$(date +%s%3N)', script)
                positions = [script.index(f"b62_probe_mark {p}") for p in phases]
                self.assertEqual(positions, sorted(positions))
                self.assertLess(script.index("b62_probe_mark READY"), script.index("HTTP_CODE="))
                self.assertLess(script.index("b62_probe_mark RESPONSE"), script.index("if [ \"$HTTP_CODE\" != \"200\" ]"))
                self.assertLess(script.index(success), script.index("b62_probe_mark ASSERT_PASS"))
                self.assertIn("if [ \"$READY\" -ne 1 ]; then", script)
                self.assertIn("if [ \"$HTTP_CODE\" != \"200\" ]; then", script)
                syntax = subprocess.run(["bash", "-n", str(source_path)],
                                        capture_output=True, text=True, timeout=5,
                                        check=False)
                self.assertEqual(syntax.returncode, 0, syntax.stderr)

    def test_real_probe_wrangle_process_group_cleanup_contract(self):
        # npm's pinned npx process is a parent; Workerd remains a descendant.
        # A probe-local new session ensures group signals cannot kill the
        # GitHub runner, its sibling probes, or other CI workloads.
        for name in PROBES:
            with self.subTest(probe=name):
                script = (SCRIPTS / f"b62_worker_probe_{name}.sh").read_text(encoding="utf-8")
                self.assertIn("setsid npx --yes wrangler@4.130.0 dev", script)
                self.assertEqual(script.count('kill -TERM -- "-$WORKER_PID"'), 1)
                self.assertEqual(script.count('kill -KILL -- "-$WORKER_PID"'), 1)
                self.assertIn('wait "$WORKER_PID" 2>/dev/null || true', script)
                self.assertLess(script.index('kill -TERM -- "-$WORKER_PID"'),
                                script.index('kill -KILL -- "-$WORKER_PID"'))
                self.assertIn("trap cleanup EXIT", script)
                self.assertIn('rm -rf -- "$PERSIST_DIR"', script)
                syntax = subprocess.run(
                    ["bash", "-n", str(SCRIPTS / f"b62_worker_probe_{name}.sh")],
                    capture_output=True, text=True, timeout=5, check=False,
                )
                self.assertEqual(syntax.returncode, 0, syntax.stderr)

    @unittest.skipUnless(os.name == "posix", "GitHub Actions Worker runner uses Linux")
    def test_setsid_isolates_probe_processes_from_parent_test_runner(self):
        # Real offline OS canary: no Wrangler/network/paid backend is contacted.
        # The simulated process tree shares one isolated PGID, distinct from
        # this Python test runner. Signal it and enforce a bounded shutdown.
        import signal

        proc = subprocess.Popen(
            ["setsid", "bash", "-c", 'sleep 30 & echo "$BASHPID $!"; wait'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            assert proc.stdout is not None
            launcher, child = map(int, proc.stdout.readline().strip().split())
            self.assertEqual(proc.pid, launcher)
            self.assertEqual(os.getpgid(proc.pid), proc.pid)
            self.assertEqual(os.getpgid(child), proc.pid)
            self.assertNotEqual(os.getpgid(os.getpid()), proc.pid)
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
            # A zombie is harmless and is awaiting init reaping; a runnable
            # descendant would be a resource leak after Wrangler exits.
            status = subprocess.run(
                ["ps", "-o", "stat=", "-p", str(child)],
                capture_output=True, text=True, timeout=3, check=False,
            )
            self.assertTrue(
                status.returncode != 0 or status.stdout.strip().startswith("Z"),
                status.stdout,
            )
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()

    def test_cold_cache_npx_preflight_fails_closed_before_any_real_probe(self):
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn("npx --yes wrangler@4.130.0 --version", runner)
        self.assertIn("B62_WORKER_NPX_PREWARM=FAIL", runner)
        self.assertIn("B62_WORKER_NPX_PREWARM=PASS", runner)
        self.assertLess(
            runner.index("npx --yes wrangler@4.130.0 --version"),
            runner.index("for index in 0 1 2 3; do"),
        )
        # A failed first-use package install must NOT start four real Workers.
        # Provide a failing synthetic npx; never contact npm/Cloudflare.
        with tempfile.TemporaryDirectory(prefix="b62-npx-prewarm-") as directory:
            temp = Path(directory)
            fake = temp / "npx"
            fake.write_text("#!/bin/sh\nexit 17\n", encoding="utf-8")
            fake.chmod(0o755)
            env = os.environ.copy()
            env.pop("B62_WORKER_NPX_PREWARMED", None)
            env["PATH"] = str(temp) + os.pathsep + env.get("PATH", "")
            result = subprocess.run(
                ["bash", str(RUNNER)], capture_output=True, text=True,
                cwd=temp, env=env, timeout=12, check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("B62_WORKER_NPX_PREWARM=FAIL", result.stderr)
            self.assertNotIn("B62_WORKER_PROBE_0=", result.stdout + result.stderr)
            self.assertNotIn("B62_WORKER_PROBES=PASS", result.stdout + result.stderr)

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


    def _offline_overlap(self, *, vendor_exit=0, version="4.130.0"):
        # Both independent preparations must begin before either finishes.
        # No network, uv, npm, Wrangler, Production or Worker invoked.
        with tempfile.TemporaryDirectory(prefix="b62-worker-prewarm-") as directory:
            temp = Path(directory)
            marker = temp / "interleaving"
            envfile = temp / "github-env"
            uv = temp / "uv"
            uv.write_text(
                "#!/usr/bin/env bash\n"
                'test "$*" = "run --locked pywrangler sync --force" || exit 41\n'
                'printf "vendor:start\\n" >> "$MARKER"\n'
                "sleep 0.3\n"
                'printf "vendor:finish\\n" >> "$MARKER"\n'
                f"exit {vendor_exit}\n", encoding="utf-8",
            )
            npx = temp / "npx"
            npx.write_text(
                "#!/usr/bin/env bash\n"
                'test "$*" = "--yes wrangler@4.130.0 --version" || exit 42\n'
                'printf "wrangler:start\\n" >> "$MARKER"\n'
                "sleep 0.3\n"
                'printf "wrangler:finish\\n" >> "$MARKER"\n'
                f"echo '{version}'\n", encoding="utf-8",
            )
            uv.chmod(0o755)
            npx.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(temp) + os.pathsep + env.get("PATH", "")
            env["MARKER"] = str(marker)
            env["GITHUB_ENV"] = str(envfile)
            env.pop("B62_WORKER_NPX_PREWARMED", None)
            proc = subprocess.run(
                ["bash", str(PREWARM)], capture_output=True, text=True,
                env=env, cwd=temp, timeout=12, check=False,
            )
            return proc, marker.read_text(encoding="utf-8").splitlines(), (
                envfile.read_text(encoding="utf-8") if envfile.exists() else ""
            )

    def test_two_independent_preflights_overlap_and_gate_all_probes(self):
        proc, marks, env = self._offline_overlap()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(set(marks[:2]), {"vendor:start", "wrangler:start"})
        self.assertEqual(set(marks[2:]), {"vendor:finish", "wrangler:finish"})
        self.assertIn("B62_WORKER_VENDOR_SYNC=PASS", proc.stdout)
        self.assertIn("B62_WORKER_NPX_PREWARM=PASS", proc.stdout)
        self.assertIn("B62_WORKER_OVERLAP=PASS", proc.stdout)
        self.assertEqual(env, "B62_WORKER_NPX_PREWARMED=1\n")

    def test_failed_vendor_does_not_export_skip_marker(self):
        proc, marks, env = self._offline_overlap(vendor_exit=17)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(len(marks), 4)
        self.assertEqual(env, "")
        self.assertIn("B62_WORKER_OVERLAP=FAIL", proc.stderr)
        self.assertIn("B62_WORKER_VENDOR_SYNC=FAIL", proc.stderr)

    def test_wrong_wrangler_version_fails_before_any_probe(self):
        proc, marks, env = self._offline_overlap(version="4.149.0")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(len(marks), 4)
        self.assertEqual(env, "")
        self.assertIn("B62_WORKER_NPX_PREWARM=FAIL", proc.stderr)
        self.assertIn("B62_WORKER_OVERLAP=FAIL", proc.stderr)


if __name__ == "__main__":
    unittest.main()
