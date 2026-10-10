"""#3989 — regression contract for safe source-invariant test-only CI routing.

This test MODULE is intentionally the only file changed in the proof PR.
The real CI classifier must detect tests_only from exact PR/push file metadata.
B62 full pytest still runs this file, while the completely unchanged Workerd
boot matrix may be omitted only for this tightly bounded change category.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
CLASSIFIER = REPO_ROOT / ".github/scripts/b62_ci_impact_scope_3989.py"
WORKFLOW = REPO_ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
HOST_RUNNER = REPO_ROOT / ".github/scripts/b62_host_pytest_overlap_4070.sh"

spec = importlib.util.spec_from_file_location("b62_tests_only_ci_scope_contract", CLASSIFIER)
assert spec and spec.loader
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


def modified(path: str, status: str = "modified") -> dict:
    return {"filename": path, "status": status}


class TestsOnlyCIRoutingContract(unittest.TestCase):
    def test_exact_direct_python_test_is_source_invariant(self):
        self.assertEqual(
            classifier.impact_scope([modified("apps/padiem-chat/tests/test_password_auth.py")]),
            classifier.TESTS_ONLY,
        )
        self.assertEqual(classifier.impact_scope([
            modified("apps/padiem-chat/tests/test_password_auth.py"),
            modified("apps/padiem-chat/tests/test_3989_ci_tests_only_scope_contract.py", "added"),
        ]), classifier.TESTS_ONLY)

    def test_runtime_source_and_config_always_retain_four_real_probes(self):
        sensitive = (
            "apps/padiem-chat/app/auth_routes.py",
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/worker_runtime_timeout_probe.py",
            "apps/padiem-chat/wrangler.toml",
            "apps/padiem-chat/pylock.toml",
            "apps/padiem-chat/uv.lock",
            "apps/padiem-chat/python_modules/padiem_ai_core/__init__.py",
            ".github/scripts/b62_worker_probe_parallel.sh",
            ".github/workflows/b62-padiem-chat-ci.yml",
            "packages/padiem-ai-core/padiem_ai_core/b14_execution.py",
        )
        test = modified("apps/padiem-chat/tests/test_password_auth.py")
        for path in sensitive:
            with self.subTest(path=path):
                self.assertNotEqual(classifier.impact_scope([test, modified(path)]),
                                    classifier.TESTS_ONLY)

    def test_conftest_helper_nested_unknown_cannot_skip_real_workers(self):
        for path in (
            "apps/padiem-chat/tests/conftest.py",
            "apps/padiem-chat/tests/_fixtures.py",
            "apps/padiem-chat/tests/test_nested/test_deep.py",
            "apps/padiem-chat/tests/test_staging.js",
            "apps/padiem-chat/tests/test_foo.py/../../worker.py",
            "apps/padiem-chat/tests\\test_no.py",
        ):
            with self.subTest(path=path):
                self.assertNotEqual(classifier.impact_scope([modified(path)]),
                                    classifier.TESTS_ONLY)

    def test_renames_removals_duplicates_and_large_diffs_fail_closed(self):
        p = "apps/padiem-chat/tests/test_password_auth.py"
        for status in ("removed", "renamed", "copied", "unchanged"):
            self.assertEqual(classifier.impact_scope([modified(p, status)]),
                             classifier.FULL)
        self.assertEqual(classifier.impact_scope([modified(p), modified(p)]),
                         classifier.FULL)
        self.assertEqual(classifier.impact_scope([]), classifier.FULL)
        self.assertEqual(classifier.impact_scope([modified(
            f"apps/padiem-chat/tests/test_{i}.py") for i in range(101)]),
            classifier.FULL)

    def test_exact_pr_and_push_compare_are_both_required(self):
        sha_a, sha_b = "a" * 40, "b" * 40
        repo = "skerishKang/ai-revenue-lab"
        for event_name in ("pull_request", "push"):
            event = {"repository": {"full_name": repo}}
            if event_name == "pull_request":
                event["pull_request"] = {"base": {"sha": sha_a},
                                         "head": {"sha": sha_b}}
            else:
                event.update(before=sha_a, after=sha_b)
            response = io.BytesIO(json.dumps({
                "status": "ahead",
                "files": [modified("apps/padiem-chat/tests/test_password_auth.py")],
            }).encode("utf-8"))
            with patch.object(classifier.urllib.request, "urlopen",
                              return_value=response) as api:
                self.assertEqual(classifier.impact_scope(classifier.changed_files(
                    event, event_name, repo, "token")), classifier.TESTS_ONLY)
                self.assertIn(f"compare/{sha_a}...{sha_b}",
                              api.call_args.args[0].full_url)
        self.assertIsNone(classifier.changed_files({}, "workflow_dispatch", repo, "token"))
        self.assertIsNone(classifier.changed_files(event, "push", repo, ""))

    def test_live_runtime_remains_required_for_unknown_scope(self):
        flow = WORKFLOW.read_text(encoding="utf-8")
        worker = flow[flow.index("  b62-worker-suite:"):flow.index("  b14-multimodal-test:")]
        self.assertIn("name: Real Worker/Pyodide probes (four assertions, one Workerd, fail-closed)",
                      worker)
        self.assertIn(
            "needs.registry-ci-plan.outputs.scope != 'static_only' && "
            "needs.registry-ci-plan.outputs.scope != 'tests_only'",
            worker,
        )
        self.assertIn("run: bash ../../.github/scripts/b62_worker_probe_parallel.sh",
                      worker)
        self.assertIn("uv run --locked pywrangler deploy --dry-run", worker)

    def test_test_only_still_requires_chat_vendor_lock_bundle_b14_and_status(self):
        flow = WORKFLOW.read_text(encoding="utf-8")
        worker = flow[flow.index("  b62-worker-suite:"):flow.index("  b14-multimodal-test:")]
        for marker in (
            "Pywrangler dependency sync from committed pylock",
            "Verify locked host dependency versions",
            "Verify vendored Worker dependency versions",
            "Prove sync did not mutate committed locks",
            "Verify Worker probe concurrency and failure propagation contract",
            "Prove Core vendored for Python Worker",
            "Python Worker bundle dry-run",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, worker)
        host = HOST_RUNNER.read_text(encoding="utf-8")
        self.assertIn("chat_only|static_only|tests_only|b14_only) run_core=0", host)
        self.assertIn("uv run --locked python -m pytest -q", host)
        self.assertIn("B62_CHAT_PYTEST=PASS", host)
        self.assertIn("name: b62-test", flow)
        self.assertIn('test "$WORKER_RESULT" = success', flow)
        self.assertIn('test "$FULL_RESULT" = success', flow)
        self.assertIn('test "$MM_RESULT" = success', flow)

    def test_worker_sources_are_not_touched_by_this_test_module(self):
        for probe in ("timeout", "web_transport", "p01_binding", "r2_read"):
            source = (REPO_ROOT / ".github/scripts" /
                      f"b62_worker_probe_{probe}.sh").read_text(encoding="utf-8")
            self.assertIn("setsid npx --yes wrangler@4.130.0 dev", source)
            self.assertIn("trap cleanup EXIT", source)


if __name__ == "__main__":
    unittest.main()
