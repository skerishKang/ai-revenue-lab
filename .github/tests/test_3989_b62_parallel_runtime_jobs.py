"""#3989: prove B62 Python/Worker parallelism preserves fail-closed required checks."""

from pathlib import Path
import os
import re
import subprocess
import tempfile
import textwrap
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
            "needs: [registry-ci-plan, b62-static-ui, b62-ui-mixed-tests, b62-core-parser-focused, b62-b14-attempt-focused, b62-full-suite, b62-worker-suite, b14-multimodal-test, b62-registry-contract]",
            self.aggregate,
        )
        self.assertIn("WORKER_RESULT: ${{ needs.b62-worker-suite.result }}", self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$PLAN_RESULT" = success', self.aggregate)

    def test_parallel_jobs_preserve_pr_plan_with_main_host_override(self):
        condition = "if: ${{ needs.registry-ci-plan.outputs.lane != 'model_registration_only' && needs.registry-ci-plan.outputs.scope != 'static_only' && needs.registry-ci-plan.outputs.scope != 'b14_tests_only' && needs.registry-ci-plan.outputs.scope != 'ui_mixed' && needs.registry-ci-plan.outputs.scope != 'core_focused_only' && needs.registry-ci-plan.outputs.scope != 'b14_attempt_only' }}"
        for block in [self.host, self.worker]:
            self.assertIn("needs: registry-ci-plan", block)
            self.assertIn("runs-on: ubuntu-latest", block)
            self.assertIn("timeout-minutes: 12", block)
        self.assertIn(condition, self.worker)
        original = condition.removeprefix("if: ${{ ").removesuffix(" }}")
        self.assertIn(original, self.host)
        self.assertIn("!cancelled()", self.host)
        self.assertIn("github.event_name == 'push' && github.ref == 'refs/heads/main'", self.host)
        self.assertIn("needs.registry-ci-plan.result == 'success'", self.host)
        self.assertNotIn("needs: b62-full-suite", self.worker)
        self.assertNotIn("needs: b62-worker-suite", self.host)

    def test_b14_unit_tests_only_skip_unchanged_b62_jobs_but_keep_required_status(self):
        # Source/lock changes cannot enter b14_tests_only; only exact B14 unit
        # test modules. B14 pilot still runs and the independent B14 workflow
        # covers all tests, while required b62-test reports success/failure.
        self.assertIn("scope != 'b14_tests_only'", self.host)
        self.assertIn("scope != 'b14_tests_only'", self.worker)
        pilot = job("b14-multimodal-test", self.source)
        self.assertNotIn("b14_tests_only", pilot)
        self.assertIn('elif [ "$SCOPE" = b14_tests_only ]; then', self.aggregate)
        self.assertIn("B62_CI_MODE=B14_TESTS_ONLY", self.aggregate)
        self.assertIn('test "$MM_RESULT" = success', self.aggregate)
        for name in ("UI_RESULT", "MIXED_RESULT", "FULL_RESULT", "WORKER_RESULT", "QUICK_RESULT"):
            expected = '"$EXPECTED_FOCUSED_FULL"' if name == "FULL_RESULT" else "skipped"
            self.assertIn('test "$' + name + '" = ' + expected, self.aggregate)

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
            "version: \"0.13.5\"",
            "uv lock --check",
            "uv sync --locked --extra dev",
            "Verify locked host dependency versions",
            "run: bash ../../.github/scripts/b62_worker_prewarm_overlap.sh",
            "Verify vendored Worker dependency versions",
            "git diff --exit-code -- uv.lock pylock.toml",
            "Verify Worker probe concurrency and failure propagation contract",
            "Real Worker/Pyodide probes (four assertions, one Workerd, fail-closed)",
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
        self.assertIn("name: Real Worker/Pyodide probes (four assertions, one Workerd, fail-closed)",
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
            expected = '"$EXPECTED_FOCUSED_FULL"' if x == "FULL_RESULT" else "skipped"
            self.assertIn('test "$'+x+'" = '+expected,self.aggregate)

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
        # B14 test/source scopes keep the B14 contract gate; B14 source-only
        # changes stay fail-closed.
        self.assertEqual(self.aggregate.count('test "$MM_RESULT" = success'), 2)
        self.assertIn('if [ "$SCOPE" = b14_only ]; then', self.aggregate)
        self.assertIn('case "$MM_RESULT" in', self.aggregate)
        self.assertIn('success|failure)', self.aggregate)

    def test_registry_quick_path_still_has_aggregator_and_is_not_blocked(self):
        self.assertIn("if: ${{ needs.registry-ci-plan.outputs.lane == 'model_registration_only' }}", self.registry)
        self.assertIn('test "$QUICK_RESULT" = success', self.aggregate)
        self.assertIn('test "$FULL_RESULT" = "$EXPECTED_FOCUSED_FULL"', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$MM_RESULT" = skipped', self.aggregate)

    def test_b14_multimodal_runner_preserves_pilot_tests_with_pinned_uv(self):
        pilot = job("b14-multimodal-test", self.source)
        self.assertIn('python-version: "3.12"', pilot)
        self.assertIn("astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9", pilot)
        self.assertIn('version: "0.13.5"', pilot)
        self.assertIn("uv pip install --system -e . 'pytest>=8.3,<9' 'pytest-asyncio>=0.24,<1'", pilot)
        self.assertIn("python -m compileall -q app/pilot app/factory.py", pilot)
        self.assertIn("python -m pytest -q tests/test_multimodal.py tests/test_pilot.py", pilot)
        self.assertNotIn("python -m pip install", pilot)

    def test_b14_multimodal_runner_only_skips_proven_static_and_ui_mixed(self):
        pilot = job("b14-multimodal-test", self.source)
        # Registration-only already uses its own quick contract; no broad skip
        # is allowed for chat_only, mixed/Core, B14, unknown or manual cases.
        self.assertIn("needs: registry-ci-plan", pilot)
        self.assertIn(
            "needs.registry-ci-plan.outputs.lane != 'model_registration_only' "
            "&& needs.registry-ci-plan.outputs.scope != 'static_only' "
            "&& needs.registry-ci-plan.outputs.scope != 'ui_mixed'",
            pilot,
        )
        self.assertIn('SCOPE: ${{ needs.registry-ci-plan.outputs.scope }}', self.aggregate)
        self.assertIn('elif [ "$SCOPE" = static_only ]; then', self.aggregate)
        self.assertIn('test "$MM_RESULT" = skipped', self.aggregate)
        self.assertIn('test "$MM_RESULT" = success', self.aggregate)
        self.assertIn('test "$FULL_RESULT" = success', self.aggregate)
        self.assertIn('test "$WORKER_RESULT" = success', self.aggregate)
        self.assertIn('test "$QUICK_RESULT" = skipped', self.aggregate)

    def test_product_lane_keeps_b14_contract_independent_from_product_e2e(self):
        # #5002: a B14 outage must not chain-fail the product regression lane.
        # The B14 job remains in `needs` so a missing/skipped run still fails
        # closed, while its own failure is reported separately and owned by
        # #4318 instead of being repeated per product.
        self.assertIn(
            "needs: [registry-ci-plan, b62-static-ui, b62-ui-mixed-tests, b62-core-parser-focused, b62-b14-attempt-focused, b62-full-suite, "
            "b62-worker-suite, b14-multimodal-test, b62-registry-contract]",
            self.aggregate,
        )
        self.assertIn('case "$MM_RESULT" in', self.aggregate)
        self.assertIn('success|failure)', self.aggregate)
        self.assertIn('B14 contract lane did not execute', self.aggregate)
        self.assertIn('B14_CONTRACT_RESULT=$MM_RESULT', self.aggregate)
        self.assertIn('Record independent result boundaries (#5002)', self.aggregate)
        self.assertIn('if [ "$FULL_RESULT" = success ]; then', self.aggregate)
        self.assertIn('PRODUCT_E2E_BYOK=INTEGRATION_MOCK', self.aggregate)
        self.assertIn('PRODUCT_E2E_BYOK=NOT_RUN (product regression did not pass', self.aggregate)
        self.assertIn('PRODUCT_E2E_BYOK_LIVE=NOT_RUN', self.aggregate)
        self.assertIn('B14_E2E=NOT_RUN', self.aggregate)
        self.assertIn('FIRST_B14_FAILURE_EVIDENCE=record the first failure once in #4318',
                      self.aggregate)
        # A B14 source change remains gated by its own contract; product
        # scopes accept an executed-but-failed B14 lane, while skipped or
        # cancelled execution is a fan-in configuration error.
        full_branch = self.aggregate.split(
            'echo \'B62_CI_MODE=UI_MIXED_TARGETED\'')[1]
        full_branch = full_branch.split('echo \'B62_CI_MODE=FULL\'')[0]
        self.assertIn('if [ "$SCOPE" = b14_only ]; then', full_branch)
        self.assertIn('test "$MM_RESULT" = success', full_branch)
        self.assertIn('case "$MM_RESULT" in', full_branch)
        self.assertIn('success|failure)', full_branch)
        b14_tests_only_branch = self.aggregate.split(
            'elif [ "$SCOPE" = b14_tests_only ]')[1]
        b14_tests_only_branch = b14_tests_only_branch.split(
            'elif [ "$SCOPE" = static_only ]')[0]
        self.assertIn('test "$MM_RESULT" = success', b14_tests_only_branch)

    def test_classifier_tests_and_pr_paths_retained_with_unfiltered_main(self):
        self.assertIn("test_3989_b62_parallel_runtime_jobs.py -q", self.plan)
        self.assertEqual(self.source.count('      - ".github/tests/test_3989_b62_parallel_runtime_jobs.py"'), 1)
        self.assertIn("b62_ci_impact_scope_3989.py", self.plan)
        self.assertEqual(self.source.count('      - ".github/workflows/b62-padiem-chat-ci.yml"'), 1)



    def test_main_full_suite_ignores_classifier_but_pr_and_manual_keep_it(self):
        expression = re.search(r"^    if: \$\{\{ (.+) \}\}$", self.host, re.M).group(1)
        reduced = ("static_only", "ui_mixed", "core_focused_only",
                   "b14_tests_only", "b14_attempt_only")
        for event, ref in (("push", "refs/heads/main"),
                           ("push", "refs/heads/feature"),
                           ("pull_request", "refs/pull/1/merge"),
                           ("workflow_dispatch", "refs/heads/main")):
            for scope in (*reduced, "full", "chat_only", "tests_only", "b14_only", ""):
                for lane in ("model_registration_only", "full", ""):
                    for result in ("success", "failure", "skipped"):
                        for cancelled in (False, True):
                            with self.subTest(event=event, ref=ref, scope=scope,
                                              lane=lane, result=result, cancelled=cancelled):
                                replacements = {
                                    "github.event_name": repr(event),
                                    "github.ref": repr(ref),
                                    "needs.registry-ci-plan.outputs.scope": repr(scope),
                                    "needs.registry-ci-plan.outputs.lane": repr(lane),
                                    "needs.registry-ci-plan.result": repr(result),
                                    "!cancelled()": repr(not cancelled),
                                }
                                evaluated = expression
                                for key, value in replacements.items():
                                    evaluated = evaluated.replace(key, value)
                                evaluated = evaluated.replace("&&", "and").replace("||", "or")
                                expected = not cancelled and (
                                    (event == "push" and ref == "refs/heads/main")
                                    or (result == "success" and lane != "model_registration_only"
                                        and scope not in reduced)
                                )
                                self.assertEqual(eval(evaluated, {"__builtins__": {}}), expected)

    def test_main_push_has_no_path_filter_and_e2e_keeps_the_pr_contract(self):
        push = self.source.split("  push:\n", 1)[1].split("  pull_request:", 1)[0]
        self.assertEqual(push.strip(), "branches: [main]")
        e2e = (WORKFLOW.parent / "web-desktop-nonmodel-e2e.yml").read_text(encoding="utf-8")
        push = e2e.split("  push:\n", 1)[1].split("  pull_request:", 1)[0]
        self.assertEqual(push.strip(), "branches: [main]")
        pr = e2e.split("  pull_request:\n", 1)[1].split("  workflow_dispatch:", 1)[0]
        self.assertEqual(pr.strip(), 'paths:\n      - "tests/e2e/**"\n'
                                    '      - ".github/workflows/web-desktop-nonmodel-e2e.yml"')
        block = job("e2e", e2e)
        self.assertIsNone(re.search(r"^    if:", block, re.M))
        self.assertIn("os: [ubuntu-latest, windows-latest]", block)
        self.assertIn("uv run --locked python -m pytest ../../tests/e2e -q", block)

    @unittest.skipUnless(os.name == "posix", "the probe runner contracts exercise POSIX process groups (setsid)")
    def test_main_aggregate_requires_full_success_without_changing_pr_lane_results(self):
        script = self.aggregate.split("        run: |\n", 1)[1].split("\n      - name:", 1)[0]
        script = textwrap.dedent(script)
        self.assertIn("MAIN_PUSH: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",
                      self.aggregate)
        cases = (
            ("model_registration_only", "full", ("QUICK_RESULT",)),
            ("full", "b14_tests_only", ("MM_RESULT",)),
            ("full", "b14_attempt_only", ("ATTEMPT_RESULT",)),
            ("full", "core_focused_only", ("PARSER_RESULT",)),
            ("full", "static_only", ("UI_RESULT",)),
            ("full", "ui_mixed", ("UI_RESULT", "MIXED_RESULT")),
            ("full", "full", ("WORKER_RESULT", "MM_RESULT")),
            ("full", "b14_only", ("WORKER_RESULT", "MM_RESULT")),
        )
        result_keys = ("UI_RESULT", "MIXED_RESULT", "PARSER_RESULT", "ATTEMPT_RESULT",
                       "WORKER_RESULT", "MM_RESULT", "QUICK_RESULT")
        for main_push in (False, True):
            for lane, scope, selected in cases:
                env = dict(os.environ, LANE=lane, SCOPE=scope, PLAN_RESULT="success",
                           MAIN_PUSH=str(main_push).lower(),
                           **{key: "success" if key in selected else "skipped" for key in result_keys})
                expected_full = "success" if main_push or (lane == "full" and scope in ("full", "b14_only")) else "skipped"
                for result in ("success", "failure", "skipped", "cancelled"):
                    with self.subTest(main_push=main_push, lane=lane, scope=scope, result=result):
                        proc = subprocess.run(["bash", "-c", script], env=dict(env, FULL_RESULT=result),
                                              capture_output=True, text=True, timeout=10)
                        self.assertEqual(proc.returncode == 0, result == expected_full, proc.stderr)
                # The main exception cannot waive an unrelated required lane failure.
                required_results = ("PLAN_RESULT", *selected)
                if scope == "full" and lane == "full":
                    # #5002: the independent B14 failure is not a product gate.
                    required_results = tuple(key for key in required_results if key != "MM_RESULT")
                for required in required_results:
                    proc = subprocess.run(
                        ["bash", "-c", script],
                        env=dict(env, FULL_RESULT=expected_full, **{required: "failure"}),
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertNotEqual(proc.returncode, 0, required)

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
            env["B62_TEST_MARKER"] = str(marker)
            env["B62_CI_IMPACT_SCOPE"] = scope
            env["B62_FAIL_TARGET"] = fail_target
            env["TMPDIR"] = str(tmp)
            env["FAKE_UV_DIR"] = str(tmp)
            # The bash one-liner invokes the script through $OVERLAP_SCRIPT;
            # without this the job ran `bash ""` and no call was ever recorded
            # (the Windows runner never saw it — the contract is POSIX-scoped).
            env["OVERLAP_SCRIPT"] = str(script)
            # The fake uv must win command lookup inside MSYS bash: resolve the
            # dir natively in bash, grant the exec bit with bash's own chmod,
            # then prepend it to PATH. A Python chmod and a drive-letter PATH
            # entry do neither on Windows.
            result = subprocess.run(
                ["bash", "-c",
                 'FAKE_BIN="$(cd "$FAKE_UV_DIR" && pwd)" || exit 9\n'
                 'chmod +x "$FAKE_BIN/uv" 2>/dev/null || true\n'
                 'export PATH="$FAKE_BIN:$PATH"\n'
                 'bash "$OVERLAP_SCRIPT"'],
                capture_output=True, text=True,
                env=env, timeout=15, check=False,
            )
            return result, marker.read_text(encoding="utf-8").splitlines()

    @unittest.skipUnless(os.name == "posix", "the probe runner contracts exercise POSIX process groups (setsid)")
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

    @unittest.skipUnless(os.name == "posix", "the probe runner contracts exercise POSIX process groups (setsid)")
    def test_scope_preserves_original_core_skip_without_skipping_chat(self):
        for scope in ("chat_only", "static_only", "tests_only", "b14_only"):
            with self.subTest(scope=scope):
                proc, lines = self._exercise_host_overlap(scope)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(len(lines), 2)
                self.assertTrue(all("/apps/padiem-chat" in line for line in lines))
                self.assertIn("B62_CHAT_PYTEST=PASS", proc.stdout)
                self.assertIn("B62_CORE_PYTEST=SKIPPED_PROVEN_UNCHANGED", proc.stdout)

    @unittest.skipUnless(os.name == "posix", "the probe runner contracts exercise POSIX process groups (setsid)")
    def test_unknown_scope_fails_closed_to_both_suites(self):
        proc, lines = self._exercise_host_overlap("unknown")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(lines), 4)
        self.assertIn("B62_HOST_PYTEST_SCOPE_UNCERTAIN=", proc.stderr)
        self.assertIn("B62_CORE_PYTEST=PASS", proc.stdout)

    @unittest.skipUnless(os.name == "posix", "the probe runner contracts exercise POSIX process groups (setsid)")
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
