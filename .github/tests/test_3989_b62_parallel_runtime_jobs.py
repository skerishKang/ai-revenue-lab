"""#3989: prove B62 Python/Worker parallelism preserves fail-closed required checks."""

from pathlib import Path
import re
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
        cls.host = job("b62-full-suite", cls.source)
        cls.worker = job("b62-worker-suite", cls.source)
        cls.aggregate = job("b62-test", cls.source)
        cls.registry = job("b62-registry-contract", cls.source)

    def test_stable_required_status_aggregates_both_independent_jobs(self):
        self.assertIn("name: b62-test", self.aggregate)
        self.assertIn("if: always()", self.aggregate)
        self.assertIn(
            "needs: [registry-ci-plan, b62-full-suite, b62-worker-suite, b14-multimodal-test, b62-registry-contract]",
            self.aggregate,
        )
        self.assertIn("WORKER_RESULT: ${{ needs.b62-worker-suite.result }}", self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$PLAN_RESULT" = success', self.aggregate)

    def test_both_parallel_jobs_depend_on_same_fail_closed_plan(self):
        condition = "if: ${{ needs.registry-ci-plan.outputs.lane != 'model_registration_only' }}"
        for block in [self.host, self.worker]:
            self.assertIn("needs: registry-ci-plan", block)
            self.assertIn(condition, block)
            self.assertIn("runs-on: ubuntu-latest", block)
            self.assertIn("timeout-minutes: 12", block)
        self.assertNotIn("needs: b62-full-suite", self.worker)
        self.assertNotIn("needs: b62-worker-suite", self.host)

    def test_host_keeps_full_python_tests_and_core_safety(self):
        self.assertIn("uv run --locked python -m pytest -q", self.host)
        self.assertIn("Core tests with Tool Runtime dev dependency", self.host)
        self.assertIn("scope != 'chat_only' && needs.registry-ci-plan.outputs.scope != 'static_only'", self.host)
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

    def test_static_only_skips_only_live_worker_probes(self):
        self.assertEqual(self.worker.count("scope != 'static_only'"), 1)
        self.assertRegex(
            self.worker,
            r"Real Worker/Pyodide probes \(all four, parallel, fail-closed\)\n"
            r"\s*#.*\n\s*if: \$\{\{ needs.registry-ci-plan.outputs.scope != 'static_only' \}\}",
        )
        self.assertIn("pywrangler deploy --dry-run", self.worker)

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
        self.assertIn('if [ "$SCOPE" = static_only ]; then', self.aggregate)
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


if __name__ == "__main__":
    unittest.main()
