"""#3989 B62 expensive-suite scope: fail closed on every uncertain change."""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_ci_impact_scope_3989.py"
SPEC = importlib.util.spec_from_file_location("b62_ci_impact_scope", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SHA_A = "a" * 40
SHA_B = "b" * 40
REPO = "skerishKang/ai-revenue-lab"


def file(path, status="modified"):
    return {"filename": path, "status": status}


def fake_event(event_type="pull_request"):
    event = {"repository": {"full_name": REPO}}
    if event_type == "pull_request":
        event["pull_request"] = {"base": {"sha": SHA_A}, "head": {"sha": SHA_B}}
    else:
        event.update(before=SHA_A, after=SHA_B)
    return event


class B62ScopeTests(unittest.TestCase):
    def test_static_js_and_css_skip_core_and_worker_probes(self):
        self.assertEqual(module.impact_scope([
            file("apps/padiem-chat/static/app.js"),
            file("apps/padiem-chat/static/style.css", "added"),
        ]), module.STATIC_ONLY)

    def test_exact_claw_touch_css_and_static_assertions_skip_runtime(self):
        css = file("apps/padiem-chat/static/claw-focus-layout.css")
        assertions = file("apps/padiem-chat/tests/test_4488_claw_automation_touch_accessibility.py")
        self.assertEqual(module.impact_scope([css, assertions]), module.STATIC_TOUCH_ONLY)
        self.assertEqual(module.impact_scope([assertions, css]), module.STATIC_TOUCH_ONLY)
        # No broad Python-test carveout: unrelated test modules stay slow-path.
        self.assertNotEqual(module.impact_scope([
            css, file("apps/padiem-chat/tests/test_password_auth.py")
        ]), module.STATIC_TOUCH_ONLY)
        self.assertEqual(module.impact_scope([
            css, file(assertions["filename"], "removed")
        ]), module.FULL)
        self.assertEqual(module.impact_scope([
            css, assertions, file("apps/padiem-chat/app/auth_routes.py")
        ]), module.CHAT_ONLY)
        workflow = (ROOT / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8")
        self.assertIn("scope == 'static_touch_only'", workflow)
        self.assertIn("scope != 'static_touch_only'", workflow)
        self.assertIn("python -m pytest -q apps/padiem-chat/tests/test_4488_claw_automation_touch_accessibility.py", workflow)

    def test_chat_python_worker_and_tests_do_not_rerun_unchanged_core(self):
        for path in (
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/app/web_tools.py",
            "apps/padiem-chat/app/b66_quote_routes.py",
        ):
            self.assertEqual(module.impact_scope([file(path)]), module.CHAT_ONLY)

    def test_strict_test_modules_only_have_no_live_worker_source_change(self):
        # The entire B62 pytest suite still runs, and pylock/bundle are checked.
        for path in (
            "apps/padiem-chat/tests/test_password_auth.py",
            "apps/padiem-chat/tests/test_worker_web_fetch_transport.py",
            "apps/padiem-chat/tests/test_b66_quote_pdf.py",
        ):
            self.assertEqual(module.impact_scope([file(path)]), module.TESTS_ONLY)
        self.assertEqual(module.impact_scope([
            file("apps/padiem-chat/tests/test_password_auth.py"),
            file("apps/padiem-chat/tests/test_b54_claw_run_history_ui.py", "added"),
        ]), module.TESTS_ONLY)

    def test_test_only_scope_fails_closed_for_any_unsupported_file(self):
        path = "apps/padiem-chat/tests/test_password_auth.py"
        dangerous = (
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/worker_runtime_timeout_probe.py",
            "apps/padiem-chat/app/auth_routes.py",
            "apps/padiem-chat/wrangler.toml",
            "apps/padiem-chat/pylock.toml",
            ".github/scripts/b62_worker_probe_timeout.sh",
            ".github/workflows/b62-padiem-chat-ci.yml",
            "packages/padiem-ai-core/padiem_ai_core/workflow.py",
            "apps/korean-ai-platform/app/pilot/b14_models.json",
            "apps/padiem-chat/tests/conftest.py",
            "apps/padiem-chat/tests/worker_runtime_probe_origin.py",
            "apps/padiem-chat/tests/test_nested/test_foo.py",
            "apps/padiem-chat/static/app.js",
        )
        for change in dangerous:
            with self.subTest(change=change):
                self.assertNotEqual(module.impact_scope([file(path), file(change)]),
                                    module.TESTS_ONLY)
        for invalid in (
            file(path, "removed"), file(path, "renamed"),
            file("apps/padiem-chat/tests/test_foo.js"),
            file("apps/padiem-chat/tests/test_../worker.py"),
        ):
            with self.subTest(invalid=invalid):
                self.assertNotEqual(module.impact_scope([invalid]), module.TESTS_ONLY)
        self.assertEqual(module.impact_scope(
            [file("apps/padiem-chat/tests/test_foo.py")] * 2
        ), module.FULL)
        self.assertEqual(module.impact_scope(
            [file(f"apps/padiem-chat/tests/test_case{i}.py") for i in range(101)]
        ), module.FULL)

    def test_api_exact_compare_proves_test_only_for_pr_and_push(self):
        for event_type in ("pull_request", "push"):
            event = fake_event(event_type)
            data = {"status": "ahead", "files": [
                file("apps/padiem-chat/tests/test_password_auth.py")
            ]}
            with patch.object(module.urllib.request, "urlopen",
                              return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertEqual(module.impact_scope(
                    module.changed_files(event, event_type, REPO, "token")),
                    module.TESTS_ONLY)

    def test_b14_isolated_pilot_app_and_test_modules_prove_worker_source_unchanged(self):
        # B62 Workerd probes import B62 sources/Core, not the independent B14
        # app. Keep B62 Chat integration and B14 suites, but skip 4 unchanged
        # Workerd process launches and unchanged Core pytest.
        samples = (
            "apps/korean-ai-platform/app/factory.py",
            "apps/korean-ai-platform/app/pilot/b14_execution.py",
            "apps/korean-ai-platform/app/pilot/b14_models.json",
            "apps/korean-ai-platform/app/pilot/nested/runner.py",
        )
        for path in samples:
            with self.subTest(path=path):
                self.assertEqual(module.impact_scope([file(path)]), module.B14_ONLY)
        self.assertEqual(module.impact_scope([
            file("apps/korean-ai-platform/app/pilot/runner.py"),
            file("apps/korean-ai-platform/tests/test_pilot.py"),
        ]), module.B14_ONLY)

    def test_b14_test_module_only_keeps_independent_b14_and_stable_b62_status(self):
        for path in (
            "apps/korean-ai-platform/tests/test_multimodal.py",
            "apps/korean-ai-platform/tests/test_pilot.py",
            "apps/korean-ai-platform/tests/test_b14_native_parameters.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(module.impact_scope([file(path)]), module.B14_TESTS_ONLY)
        self.assertEqual(module.impact_scope([
            file("apps/korean-ai-platform/tests/test_multimodal.py"),
            file("apps/korean-ai-platform/tests/test_pilot.py", "added"),
        ]), module.B14_TESTS_ONLY)

        # Mixed B14 source+tests must run B62's existing integration and bundle.
        self.assertEqual(module.impact_scope([
            file("apps/korean-ai-platform/tests/test_pilot.py"),
            file("apps/korean-ai-platform/app/pilot/b14_execution.py"),
        ]), module.B14_ONLY)
        for unsafe in (
            "apps/korean-ai-platform/tests/conftest.py",
            "apps/korean-ai-platform/tests/test_nested/test_provider.py",
            "apps/korean-ai-platform/pyproject.toml",
            "apps/korean-ai-platform/uv.lock",
            "apps/padiem-chat/app/claw_general_routes.py",
            ".github/workflows/b62-padiem-chat-ci.yml",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertEqual(module.impact_scope([
                    file("apps/korean-ai-platform/tests/test_multimodal.py"),
                    file(unsafe),
                ]), module.FULL)
        for bad in (
            [file("apps/korean-ai-platform/tests/test_pilot.py", "removed")],
            [file("apps/korean-ai-platform/tests/test_pilot.py", "renamed")],
            [file("apps/korean-ai-platform/tests/test_pilot.py")] * 2,
        ):
            self.assertEqual(module.impact_scope(bad), module.FULL)

    def test_b14_test_scope_uses_exact_pr_and_push_comparison(self):
        for event_type in ("pull_request", "push"):
            event = fake_event(event_type)
            data = {"status": "ahead", "files": [
                file("apps/korean-ai-platform/tests/test_pilot.py"),
            ]}
            with patch.object(module.urllib.request, "urlopen",
                              return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertEqual(module.impact_scope(
                    module.changed_files(event, event_type, REPO, "token")
                ), module.B14_TESTS_ONLY)

    def test_b14_test_scope_maintains_required_status_and_independent_full_b14(self):
        workflow = (ROOT / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8")
        independent = (ROOT / ".github/workflows/validate-b14-alpha.yml").read_text(encoding="utf-8")
        self.assertIn("name: b62-test", workflow)
        self.assertIn('elif [ "$SCOPE" = b14_tests_only ]; then', workflow)
        self.assertIn('test "$MM_RESULT" = success', workflow)
        self.assertIn("B62_CI_MODE=B14_TESTS_ONLY", workflow)
        self.assertEqual(workflow.count("outputs.scope != 'b14_tests_only'"), 2)
        self.assertIn("run: uv run pytest -q", independent)
        self.assertIn("apps/korean-ai-platform/**", independent)

    def test_b14_isolated_scope_fails_closed_for_mixed_deps_ci_and_unknown(self):
        b14 = file("apps/korean-ai-platform/app/pilot/b14_execution.py")
        hazards = (
            "apps/korean-ai-platform/pyproject.toml",
            "apps/korean-ai-platform/requirements.txt",
            "apps/korean-ai-platform/uv.lock",
            "apps/korean-ai-platform/app/middleware.js",
            "apps/korean-ai-platform/tests/conftest.py",
            "apps/korean-ai-platform/tests/test_nested/test_b14.py",
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/pylock.toml",
            "apps/padiem-chat/app/claw_routes.py",
            "apps/padiem-chat/tests/test_password_auth.py",
            "apps/padiem-chat/static/app.js",
            "packages/padiem-ai-core/padiem_ai_core/b14_transport.py",
            ".github/workflows/b62-padiem-chat-ci.yml",
            ".github/scripts/b62_ci_impact_scope_3989.py",
        )
        for path in hazards:
            with self.subTest(path=path):
                self.assertNotEqual(module.impact_scope([b14, file(path)]),
                                    module.B14_ONLY)
        for invalid in (
            [file(b14["filename"], "renamed")],
            [file(b14["filename"], "deleted")],
            [b14, b14],
            [file("apps/korean-ai-platform/app/pilot/../worker.py")],
            [file("apps/korean-ai-platform/app/pilot\\worker.py")],
        ):
            with self.subTest(paths=invalid):
                self.assertEqual(module.impact_scope(invalid), module.FULL)

    def test_exact_pr_and_push_compare_b14_only(self):
        for event_type in ("pull_request", "push"):
            event = fake_event(event_type)
            data = {"status": "ahead", "files": [
                file("apps/korean-ai-platform/app/pilot/b14_execution.py")
            ]}
            with patch.object(module.urllib.request, "urlopen",
                              return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertEqual(module.impact_scope(
                    module.changed_files(event, event_type, REPO, "token")
                ), module.B14_ONLY)

    def test_mixed_product_or_ci_files_always_full(self):
        for outside in (
            "packages/padiem-ai-core/padiem_ai_core/web_runtime.py",
            "apps/korean-ai-platform/app/pilot/b14_models.json",
            "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py",
            "reference/business-66-padiem-quote-v1/index.html",
            "apps/padiem-chat/wrangler.toml",
            "apps/padiem-chat/uv.lock",
            "apps/padiem-chat/pyproject.toml",
            "apps/padiem-chat/pylock.toml",
            "apps/padiem-chat/app/model_registry.json",
            "apps/padiem-chat/scripts/vendor_helper.py",
            ".github/workflows/b62-padiem-chat-ci.yml",
            ".github/scripts/b62_ci_impact_scope_3989.py",
            "docs/operations/CI_3989_ENGINE_LL_ROUTING.md",
        ):
            self.assertEqual(module.impact_scope([
                file("apps/padiem-chat/static/app.js"), file(outside),
            ]), module.FULL)

    def test_mixed_static_and_python_retains_worker_probes(self):
        self.assertEqual(module.impact_scope([
            file("apps/padiem-chat/static/app.js"),
            file("apps/padiem-chat/worker.py"),
        ]), module.CHAT_ONLY)

    def test_malformed_file_lists_full(self):
        cases = [None, [], {}, "file", [{}], [file("app/foo", "removed")],
                 [file("apps/padiem-chat/static/a.js", "renamed")],
                 [file("apps/padiem-chat/static/a.js")] * 2,
                 [file("apps/padiem-chat/static/../worker.py")],
                 [file("apps/padiem-chat/static\\app.js")],
                 [file("apps/padiem-chat/static/a.js")] * 101]
        for case in cases:
            with self.subTest(case=str(case)[:60]):
                self.assertEqual(module.impact_scope(case), module.FULL)

    def test_exact_compare_pr_and_push(self):
        for event_type in ("pull_request", "push"):
            event = fake_event(event_type)
            data = {"status": "ahead", "files": [file("apps/padiem-chat/static/app.js")]}
            with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as call:
                self.assertEqual(module.impact_scope(
                    module.changed_files(event, event_type, REPO, "token")
                ), module.STATIC_ONLY)
                self.assertIn(f"/compare/{SHA_A}...{SHA_B}", call.call_args.args[0].full_url)

    def test_diverged_pr_with_exact_files_preserves_small_ui_scope(self):
        # Real #4533: main advanced independently; GitHub compare returned
        # diverged even though the PR changed exactly one Claw CSS stylesheet.
        cases = (
            ([file("apps/padiem-chat/static/claw-focus-layout.css")], module.STATIC_ONLY),
            ([file("apps/korean-ai-platform/tests/test_pilot.py")], module.B14_TESTS_ONLY),
            ([file("apps/padiem-chat/app/auth_routes.py")], module.CHAT_ONLY),
        )
        for files, scope in cases:
            with self.subTest(scope=scope):
                event = fake_event()
                event["pull_request"]["changed_files"] = len(files)
                reply = {"status": "diverged", "ahead_by": 1, "behind_by": 3,
                         "files": files}
                with patch.object(module.urllib.request, "urlopen",
                                  return_value=io.BytesIO(json.dumps(reply).encode())):
                    self.assertEqual(module.impact_scope(
                        module.changed_files(event, "pull_request", REPO, "token")
                    ), scope)

    def test_diverged_pr_requires_exact_untruncated_source_evidence(self):
        css = file("apps/padiem-chat/static/claw-focus-layout.css")
        exact = {"status": "diverged", "ahead_by": 1, "behind_by": 3,
                 "files": [css]}
        cases = (
            ({}, exact),  # missing PR changed-file count is not proof
            ({"changed_files": 2}, exact),  # truncated compare
            ({"changed_files": 0}, exact),
            ({"changed_files": True}, exact),
            ({"changed_files": 1}, dict(exact, ahead_by=0)),
            ({"changed_files": 1}, dict(exact, ahead_by="1")),
            ({"changed_files": 1}, dict(exact, status="behind")),
        )
        for attributes, reply in cases:
            with self.subTest(attributes=attributes, status=reply["status"]):
                event = fake_event()
                event["pull_request"].update(attributes)
                with patch.object(module.urllib.request, "urlopen",
                                  return_value=io.BytesIO(json.dumps(reply).encode())):
                    self.assertIsNone(module.changed_files(
                        event, "pull_request", REPO, "token"))
        with patch.object(module.urllib.request, "urlopen",
                          return_value=io.BytesIO(json.dumps(exact).encode())):
            self.assertIsNone(module.changed_files(
                fake_event("push"), "push", REPO, "token"))

    def test_fail_closed_on_event_and_api_ambiguity(self):
        for event_type in ("workflow_dispatch", "schedule", "delete"):
            self.assertIsNone(module.changed_files(fake_event(), event_type, REPO, "token"))
        for data in (
            {"status": "behind", "files": [file("apps/padiem-chat/static/app.js")]},
            {"status": "ahead", "files": [file("apps/padiem-chat/static/app.js")] * 101},
            {"status": "ahead", "files": None},
        ):
            with patch.object(module.urllib.request, "urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertIsNone(module.changed_files(fake_event(), "pull_request", REPO, "token"))
        event = fake_event()
        event["pull_request"]["head"]["sha"] = "broken"
        self.assertIsNone(module.changed_files(event, "pull_request", REPO, "token"))
        self.assertIsNone(module.changed_files(fake_event(), "pull_request", REPO, ""))
        self.assertIsNone(module.changed_files(fake_event(), "pull_request", "someone/else", "token"))

    def test_workflow_maintains_full_chat_and_bundle_with_status(self):
        text = (ROOT / ".github/workflows/b62-padiem-chat-ci.yml").read_text(encoding="utf-8")
        self.assertIn("name: b62-test", text)
        self.assertIn("name: B62 full regression", text)
        runner = (ROOT / ".github/scripts/b62_host_pytest_overlap_4070.sh").read_text(encoding="utf-8")
        self.assertIn("run: bash ../../.github/scripts/b62_host_pytest_overlap_4070.sh", text)
        self.assertIn("uv run --locked python -m pytest -q", runner)
        self.assertIn("uv run --extra dev python -m pytest -q", runner)
        self.assertIn("B62_HOST_PYTEST_OVERLAP=FAIL", runner)
        self.assertIn("run: uv run --locked pywrangler deploy --dry-run", text)
        self.assertIn("name: Real Worker/Pyodide probes (four assertions, one Workerd, fail-closed)", text)
        self.assertIn("run: bash ../../.github/scripts/b62_worker_probe_parallel.sh", text)
        # Main owns pinned Wrangler prewarming within its parallel runner.
        runner = (ROOT / ".github/scripts/b62_worker_probe_parallel.sh").read_text(encoding="utf-8")
        self.assertIn("npx --yes wrangler@4.130.0 --version", runner)
        self.assertLess(runner.index("npx --yes wrangler@4.130.0 --version"),
                        runner.index("for index in 0 1 2 3; do"))
        self.assertIn("scope: ${{ steps.classify-b62.outputs.scope }}", text)
        self.assertIn("B62_CI_IMPACT_SCOPE=", SCRIPT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
