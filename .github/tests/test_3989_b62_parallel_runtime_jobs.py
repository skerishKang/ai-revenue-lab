"""#3989: prove B62 Python/Worker parallelism preserves fail-closed required checks."""

from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "b62-padiem-chat-ci.yml"


def job(name: str, source: str) -> str:
    start = re.search(rf"^  {re.escape(name)}:\n", source, re.M)
    if not start:
        raise AssertionError(f"missing job: {name}")
    end = re.search(r"^  [a-z][\w-]*:\n", source[start.end():], re.M)
    return source[start.start() : start.end() + end.start() if end else len(source)]


class ParallelB62JobsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.plan = job("registry-ci-plan", cls.source)
        cls.ui = job("b62-static-ui", cls.source)
        cls.host = job("b62-full-suite", cls.source)
        cls.worker = job("b62-worker-suite", cls.source)
        cls.aggregate = job("b62-test", cls.source)
        cls.registry = job("b62-registry-contract", cls.source)

    def test_stable_required_status_aggregates_both_independent_jobs(self):
        self.assertIn("name: b62-test", self.aggregate)
        self.assertIn("if: always()", self.aggregate)
        self.assertIn(
            "needs: [registry-ci-plan, b62-static-ui, b62-full-suite, b62-worker-suite, b14-multimodal-test, b62-registry-contract]",
            self.aggregate,
        )
        self.assertIn("WORKER_RESULT: ${{ needs.b62-worker-suite.result }}", self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$PLAN_RESULT" = success', self.aggregate)

    def test_both_parallel_jobs_depend_on_same_fail_closed_plan(self):
        condition = "if: ${{ needs.registry-ci-plan.outputs.lane != 'model_registration_only' && needs.registry-ci-plan.outputs.scope != 'static_only' }}"
        for block in [self.host, self.worker]:
            self.assertIn("needs: registry-ci-plan", block)
            self.assertIn(condition, block)
            self.assertIn("runs-on: ubuntu-latest", block)
            self.assertIn("timeout-minutes: 12", block)
        self.assertNotIn("needs: b62-full-suite", self.worker)
        self.assertNotIn("needs: b62-worker-suite", self.host)

    def test_host_keeps_full_python_tests_and_core_safety(self):
        runner = (WORKFLOW.parents[1] / "scripts" / "b62_host_pytest_overlap_4070.sh").read_text(encoding="utf-8")
        self.assertIn("run: bash ../../.github/scripts/b62_host_pytest_overlap_4070.sh", self.host)
        self.assertIn("B62_CI_IMPACT_SCOPE: ${{ needs.registry-ci-plan.outputs.scope }}", self.host)
        self.assertIn("uv run --locked python -m pytest -q", runner)
        self.assertIn("uv run --extra dev python -m pytest -q", runner)
        self.assertIn('chat_only|static_only|tests_only|b14_only) run_core=0', runner)
        self.assertIn('*) echo "B62_HOST_PYTEST_SCOPE_UNCERTAIN=', runner)
        self.assertIn("B62_HOST_PYTEST_OVERLAP=FAIL", runner)
        self.assertIn("B62_HOST_PYTEST_OVERLAP=PASS", runner)
        self.assertIn("Verify locked host dependency versions", self.host)
        self.assertIn("JavaScript syntax", self.host)
        self.assertNotIn("Real Worker/Pyodide probes", self.host)
        self.assertNotIn("pywrangler sync", self.host)

    def test_worker_recreates_dependency_environment_not_host_artifacts(self):
        for marker in (
            "uses: actions/checkout@v4",
            "uses: actions/setup-python@v5",
            "uses: actions/setup-node@v4",
            "version: \"0.12.5\"",
            "uv lock --check",
            "uv sync --locked --extra dev",
            "Verify locked host dependency versions",
            "run: bash ../../.github/scripts/b62_worker_prewarm_overlap.sh",
            "Verify vendored Worker dependency versions",
            "git diff --exit-code -- uv.lock pylock.toml",
            "Verify Worker probe concurrency and failure propagation contract",
            "Real Worker/Pyodide probes (all four, parallel, fail-closed)",
            "Prove Core vendored for Python Worker",
            "uv run --locked pywrangler deploy --dry-run",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.worker)
        helper = WORKFLOW.parent.parent / "scripts" / "b62_worker_prewarm_overlap.sh"
        source = helper.read_text(encoding="utf-8")
        # It is still the original locked vendor sync, executed via the
        # fail-closed overlap helper. The original tests must not accidentally
        # accept removing or weakening the dependency lock at a call-site.
        self.assertIn("uv run --locked pywrangler sync --force", source)
        self.assertIn("npx --yes wrangler@4.130.0 --version", source)
        self.assertIn("B62_WORKER_OVERLAP=FAIL", source)
        self.assertIn("B62_WORKER_OVERLAP=PASS", source)
        self.assertLess(
            self.worker.index("b62_worker_prewarm_overlap.sh"),
            self.worker.index("Verify vendored Worker dependency versions"),
        )

    def test_only_proven_static_and_test_module_scopes_skip_live_worker_boots(self):
        self.assertEqual(self.worker.count("scope != 'static_only'"), 2)
        self.assertEqual(self.worker.count("scope != 'tests_only'"), 1)
        self.assertEqual(self.worker.count("scope != 'b14_only'"), 1)
        self.assertIn(
            "if: ${{ needs.registry-ci-plan.outputs.scope != 'static_only' "
            "&& needs.registry-ci-plan.outputs.scope != 'tests_only' "
            "&& needs.registry-ci-plan.outputs.scope != 'b14_only' }}",
            self.worker,
        )
        self.assertIn("name: Real Worker/Pyodide probes (all four, parallel, fail-closed)",
                      self.worker)
        # Every Worker dependency version, pylock, vendor build and bundle
        # contract STILL runs on test-only edits. Only live 4x boot is omitted.
        for marker in (
            "b62_worker_prewarm_overlap.sh",
            "Verify vendored Worker dependency versions",
            "Prove sync did not mutate committed locks",
            "Verify Worker probe concurrency and failure propagation contract",
            "Prove Core vendored for Python Worker",
            "pywrangler deploy --dry-run",
        ):
            self.assertIn(marker, self.worker)
        # Required aggregator waits for this worker job even on tests_only.
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$FULL_RESULT" = success', self.aggregate)
        # B14 pilot source contracts remain selected; only static-only skips.
        self.assertNotIn("scope != 'tests_only'", job("b14-multimodal-test", self.source))

    def test_proven_static_ui_lane_skips_python_vendor_and_worker_jobs(self):
        self.assertIn("needs: registry-ci-plan", self.ui)
        self.assertIn("scope == 'static_only'", self.ui)
        self.assertIn("lane != 'model_registration_only'", self.ui)
        self.assertIn("Parse every shipped UI JavaScript file", self.ui)
        self.assertIn("node --check", self.ui)
        self.assertIn("b62_dom_sink_audit.py", self.ui)
        self.assertIn("b62_static_origin_audit.py", self.ui)
        self.assertIn("b62_browser_persistence_audit.py", self.ui)
        self.assertNotIn("uv sync", self.ui)
        self.assertNotIn("pywrangler", self.ui)
        self.assertNotIn("secrets.", self.ui)
        for block in (self.host,self.worker):
            self.assertIn("scope != 'static_only'",block)
        self.assertIn("UI_RESULT:",self.aggregate)
        self.assertIn('elif [ "$SCOPE" = static_only ]; then',self.aggregate)
        self.assertIn('test "$UI_RESULT" = success',self.aggregate)
        self.assertIn("B62_CI_MODE=STATIC_UI_ONLY",self.aggregate)
        for x in ("FULL_RESULT","WORKER_RESULT","MM_RESULT","QUICK_RESULT"):
            self.assertIn('test "$'+x+'" = skipped',self.aggregate)

    def test_b14_only_keeps_full_b62_chat_b14_and_worker_bundle_gates(self):
        # The b14_only shortcut is allowed only at the live Workerd step.
        # All other gates and the registry-only branch are unchanged.
        self.assertIn("needs.registry-ci-plan.outputs.lane != 'model_registration_only'",
                      self.host)
        self.assertIn("B62 Chat and eligible Core tests", self.host)
        self.assertIn("b62_worker_prewarm_overlap.sh", self.worker)
        self.assertIn("Verify vendored Worker dependency versions", self.worker)
        self.assertIn("pywrangler deploy --dry-run", self.worker)
        self.assertNotIn("b14_only", job("b14-multimodal-test", self.source))
        self.assertIn('test "$FULL_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$MM_RESULT" = success', self.aggregate)

    def test_registry_quick_path_still_has_aggregator_and_is_not_blocked(self):
        self.assertIn("if: ${{ needs.registry-ci-plan.outputs.lane == 'model_registration_only' }}", self.registry)
        self.assertIn('test "$QUICK_RESULT" = success', self.aggregate)
        self.assertIn('test "$FULL_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$MM_RESULT" = skipped', self.aggregate)

    def test_b14_multimodal_runner_only_skips_proven_static_only(self):
        pilot = job("b14-multimodal-test", self.source)
        # Registration-only already uses its own quick contract; no broad skip
        # is allowed for chat_only, mixed/Core, B14, unknown or manual cases.
        self.assertIn("needs: registry-ci-plan", pilot)
        self.assertIn(
            "needs.registry-ci-plan.outputs.lane != 'model_registration_only' "
            "&& needs.registry-ci-plan.outputs.scope != 'static_only'",
            pilot,
        )
        self.assertIn('SCOPE: ${{ needs.registry-ci-plan.outputs.scope }}', self.aggregate)
        self.assertIn('elif [ "$SCOPE" = static_only ]; then', self.aggregate)
        self.assertIn('test "$MM_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$MM_RESULT" = success', self.aggregate)
        self.assertIn('test "$FULL_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$QUICK_RESULT" = skipped', self.aggregate)

    def test_classifier_tests_and_both_impact_triggers_retained(self):
        self.assertIn("test_3989_b62_parallel_runtime_jobs.py -q", self.plan)
        self.assertEqual(self.source.count('      - ".github/tests/test_3989_b62_parallel_runtime_jobs.py"'), 2)
        self.assertIn("b62_ci_impact_scope_3989.py", self.plan)
        self.assertEqual(self.source.count('      - ".github/workflows/b62-padiem-chat-ci.yml"'), 2)


    def _exercise_host_overlap(self, scope="full", fail_target=""):
        script = WORKFLOW.parents[1] / "scripts" / "b62_host_pytest_overlap_4070.sh"
        with tempfile.TemporaryDirectory(prefix="b62-host-overlap-contract-") as dirname:
            tmp = Path(dirname)
            marker = tmp / "calls.log"
            fake_uv = tmp / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                'printf "start:%s:%s\\n" "$PWD" "$*" >> "$B62_TEST_MARKER"\n'
                'sleep 0.20\n'
                'printf "finish:%s:%s\\n" "$PWD" "$*" >> "$B62_TEST_MARKER"\n'
                'case "$PWD" in\n'
                '  */packages/padiem-ai-core) test "$B62_FAIL_TARGET" != core || exit 17 ;;\n'
                '  */apps/padiem-chat) test "$B62_FAIL_TARGET" != chat || exit 18 ;;\n'
                '  *) exit 41 ;;\n'
                'esac\n'
                'echo "FAKE_PYTEST_PASS:$PWD"\n',
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(tmp) + os.pathsep + env.get("PATH", "")
            env["B62_TEST_MARKER"] = str(marker)
            env["B62_CI_IMPACT_SCOPE"] = scope
            env["B62_FAIL_TARGET"] = fail_target
            env["TMPDIR"] = str(tmp)
            result = subprocess.run(
                ["bash", str(script)],
                capture_output=True, text=True,
                env=env, timeout=15, check=False,
            )
            return result, marker.read_text(encoding="utf-8").splitlines()

    def test_chat_and_core_full_scope_overlap_without_extra_runner(self):
        proc, lines = self._exercise_host_overlap("full")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[0].startswith("start:"))
        self.assertTrue(lines[1].startswith("start:"))
        self.assertTrue(all(line.startswith("finish:") for line in lines[2:]))
        self.assertTrue(any("/packages/padiem-ai-core" in l for l in lines))
        self.assertTrue(any("/apps/padiem-chat" in l for l in lines))
        self.assertIn("B62_CHAT_PYTEST=PASS", proc.stdout)
        self.assertIn("B62_CORE_PYTEST=PASS", proc.stdout)
        self.assertIn("B62_HOST_PYTEST_OVERLAP=PASS", proc.stdout)

    def test_scope_preserves_original_core_skip_without_skipping_chat(self):
        for scope in ("chat_only", "static_only", "tests_only", "b14_only"):
            with self.subTest(scope=scope):
                proc, lines = self._exercise_host_overlap(scope)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(len(lines), 2)
                self.assertTrue(all("/apps/padiem-chat" in line for line in lines))
                self.assertIn("B62_CHAT_PYTEST=PASS", proc.stdout)
                self.assertIn("B62_CORE_PYTEST=SKIPPED_PROVEN_UNCHANGED", proc.stdout)

    def test_unknown_scope_fails_closed_to_both_suites(self):
        proc, lines = self._exercise_host_overlap("unknown")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(lines), 4)
        self.assertIn("B62_HOST_PYTEST_SCOPE_UNCERTAIN=", proc.stderr)
        self.assertIn("B62_CORE_PYTEST=PASS", proc.stdout)

    def test_either_suite_failure_propagates_after_other_finishes(self):
        for target in ("chat", "core"):
            with self.subTest(target=target):
                proc, lines = self._exercise_host_overlap("full", target)
                self.assertNotEqual(proc.returncode, 0)
                self.assertEqual(len(lines), 4)
                self.assertIn("B62_HOST_PYTEST_OVERLAP=FAIL", proc.stderr)
                self.assertIn(f"B62_{target.upper()}_PYTEST=FAIL", proc.stderr)
                opposite = "CORE" if target == "chat" else "CHAT"
                self.assertIn(f"B62_{opposite}_PYTEST=PASS", proc.stderr)


if __name__ == "__main__":
    unittest.main()
