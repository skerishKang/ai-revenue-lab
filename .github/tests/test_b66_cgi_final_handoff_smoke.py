from __future__ import annotations

import importlib.util
import ast
import io
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_final_handoff_smoke.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_final_handoff_smoke", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FinalHandoffSmokeContractTests(unittest.TestCase):
    def test_exact_three_interpret_budget(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 3)
        self.assertEqual(module.MAX_PDF_POSTS, 3)
        self.assertEqual(module.PDF_PATH, "/api/padiem/b66/quote/pdf")
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

    def test_exact_acceptance_inputs(self):
        self.assertEqual(
            module.COMPLETE_TEXT,
            "대한건설에 배관 100미터, 미터당 18000원, 부가세 별도",
        )
        self.assertEqual(
            module.PARTIAL_TEXT,
            "대한건설에 배관 100미터, 부가세 별도",
        )
        self.assertEqual(module.FOLLOWUP_TEXT, "미터당 18000원")

    def test_provider_host_detection_is_closed_to_real_provider_hosts(self):
        self.assertTrue(module._is_direct_provider("https://api.kilo.ai/v1/chat"))
        self.assertTrue(module._is_direct_provider("https://openrouter.ai/api/v1/chat"))
        self.assertFalse(
            module._is_direct_provider(
                "https://quick-quote-kr.pages.dev/api/padiem/b66/quote/interpret"
            )
        )

    def test_google_fonts_css_is_not_a_direct_model_provider(self):
        # Public GET-only browser observation: fonts.googleapis.com/css2.
        self.assertFalse(module._is_direct_provider(
            "https://fonts.googleapis.com/css2?family=Manrope:wght@400"
        ))
        self.assertFalse(module._is_direct_provider(
            "https://fonts.googleapis.com/css?family=Manrope"
        ))
        # This exemption must not expand to any other Google API route.
        self.assertTrue(module._is_direct_provider(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini:generateContent"
        ))
        self.assertTrue(module._is_direct_provider(
            "https://aiplatform.googleapis.com/v1/projects/p/locations/l"
        ))
        self.assertTrue(module._is_direct_provider(
            "https://fonts.googleapis.com/v1/models/gemini:generateContent"
        ))
        self.assertTrue(module._is_direct_provider(
            "https://www.googleapis.com/v1/models/gemini:generateContent"
        ))
        self.assertTrue(module._is_direct_provider(
            "https://api.openai.com/v1/chat/completions"
        ))
        self.assertTrue(module._is_direct_provider(
            "https://api.anthropic.com/v1/messages"
        ))

    def test_final_handoff_uses_real_certified_pdf_download_not_window_print(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("page.expect_download", source)
        self.assertIn("cgi_browser_pdf_not_active", source)
        self.assertIn("cgi_browser_pdf_used_server", source)
        self.assertIn("CERTIFIED_BROWSER_PDF_DOWNLOADS=3", source)
        self.assertIn('print("PDF_POSTS=0")', source)
        self.assertIn('body.startswith(b"%PDF-")', source)
        self.assertNotIn("window.print =", source)

    def test_target_is_standalone_b66_production(self):
        self.assertEqual(module.TARGET_URL, "https://quick-quote-kr.pages.dev/")
        self.assertEqual(
            module.INTERPRET_PATH,
            "/api/padiem/b66/quote/interpret",
        )


class B66InterpretFailureEvidenceTests(unittest.TestCase):
    """Only already-emitted errors from the one preauthorized request."""

    @staticmethod
    def _upstream_route_vocabulary():
        source = (
            Path(__file__).parents[2] / "apps" / "padiem-chat" / "app"
            / "b66_quote_routes.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "_UPSTREAM_CLASS_ALLOWLIST"
                for target in node.targets
            ):
                assert isinstance(node.value, ast.Call)
                assert isinstance(node.value.args[0], (ast.Set, ast.Tuple))
                return {v.value for v in node.value.args[0].elts}
        raise AssertionError("B66 canonical upstream class vocabulary absent")

    def test_502_failure_stage_and_family_vocab_mirrors_canonical_route(self):
        source = (
            Path(__file__).parents[2] / "apps" / "padiem-chat" / "app"
            / "b66_quote_routes.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        names = {
            "_B66_INTERPRET_FAILURE_STAGES": module.B66_INTERPRET_FAILURE_STAGES,
            "_B66_INTERPRET_EXCEPTION_FAMILIES": module.B66_INTERPRET_EXCEPTION_FAMILIES,
        }
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    self.assertIsInstance(node.value, ast.Call)
                    self.assertIsInstance(node.value.args[0], ast.Set)
                    self.assertEqual(
                        {item.value for item in node.value.args[0].elts},
                        names.pop(target.id)
                    )
        self.assertEqual(names, {}, "route and smoke vocabulary must stay synchronized")

    def test_502_new_provenance_markers_fail_only_and_no_privacy_leak(self):
        response_body = json.dumps({"error": {
            "code": "quote_interpretation_failed",
            "message": "PRIVATE_QUOTE_TOKEN_NEVER_PRINT",
        }})
        cases = (
            ({"x-b66-interpret-failure-stage": "interpreter_exception",
              "x-b66-interpret-exception-family": "type_error"},
             ("interpreter_exception", "type_error")),
            ({"x-b66-interpret-failure-stage": "projection_missing_safe_dict",
              "x-b66-interpret-exception-family": "type_error"},
             ("projection_missing_safe_dict", "UNCLASSIFIED")),
            ({"x-b66-interpret-failure-stage": "company-name-private",
              "x-b66-interpret-exception-family": "company-name-private"},
             ("UNCLASSIFIED", "UNCLASSIFIED")),
        )
        for raw_headers, expected in cases:
            class Response:
                headers = {
                    "content-type": "application/json",
                    **raw_headers,
                    "set-cookie": "PRIVATE_QUOTE_TOKEN_NEVER_PRINT",
                }
                def text(self):
                    return response_body
            output = io.StringIO()
            with redirect_stdout(output):
                module._print_bounded_b66_interpret_failure(Response())
            lines = output.getvalue().splitlines()
            self.assertEqual(lines[-2:], [
                "B66_INTERPRET_FAILURE_STAGE=" + expected[0],
                "B66_INTERPRET_EXCEPTION_FAMILY=" + expected[1],
            ])
            self.assertNotIn("PRIVATE_QUOTE_TOKEN_NEVER_PRINT", output.getvalue())
            self.assertNotIn("company-name-private", output.getvalue())

    def test_new_b66_503_model_and_runtime_errors_have_bounded_diagnostics(self):
        cases = (
            ("quote_model_unavailable", "model_selection"),
            ("quote_runtime_unavailable", "runtime_unavailable"),
            ("quote_interpretation_failed", "provider_execution"),
            ("quote_interpretation_failed", "provider_response"),
        )
        for code, stage in cases:
            body = json.dumps({"error": {
                "code": code,
                "message": "CUSTOMER_PRIVATE_QUOTE_MESSAGE",
            }})
            self.assertEqual(
                module._bounded_b66_interpret_failure(body, {
                    "x-b66-upstream-class": "upstream_error"
                    if stage == "provider_execution" else "private-route-value",
                })[0],
                code,
            )
            class SyntheticResponse:
                headers = {
                    "content-type": "application/json",
                    "x-b66-interpret-failure-stage": stage,
                    "x-b66-interpret-exception-family": "PRIVATE_FAMILY",
                    "set-cookie": "CUSTOMER_PRIVATE_QUOTE_MESSAGE",
                }
                def text(self):
                    return body
            output = io.StringIO()
            with redirect_stdout(output):
                module._print_bounded_b66_interpret_failure(SyntheticResponse())
            recorded = output.getvalue()
            self.assertIn("B66_INTERPRET_FAILURE_STAGE=" + stage, recorded)
            self.assertNotIn("CUSTOMER_PRIVATE_QUOTE_MESSAGE", recorded)
            self.assertNotIn("PRIVATE_FAMILY", recorded)

    def test_exact_allowlist_matches_real_b66_route(self):
        self.assertEqual(
            module.B66_UPSTREAM_CLASS_VOCABULARY,
            self._upstream_route_vocabulary()
        )
        self.assertEqual(module.B66_INTERPRET_ERROR_CODES, {
            "quote_interpretation_failed", "quote_runtime_unavailable",
            "quote_model_unavailable", "padiem_service_unavailable"
        })

    def test_known_interpreter_failure_classified_without_leaking_message(self):
        body = json.dumps({
            "error": {
                "code": "quote_interpretation_failed",
                "message": "PRIVATE QUOTE CUSTOMER VALUES HERE",
                "debug": {"token": "NO LEAK"}
            }
        })
        result = module._bounded_b66_interpret_failure(
            body, {
                "x-b66-upstream-class": "upstream_timeout",
                "set-cookie": "SECRET",
            }
        )
        self.assertEqual(result, (
            "quote_interpretation_failed", "B66_INTERPRETER_ROUTE", "upstream_timeout"
        ))
        self.assertNotIn("PRIVATE", str(result))
        self.assertNotIn("SECRET", str(result))

    def test_pages_proxy_is_distinct_from_b66_interpreter(self):
        body = json.dumps({"error": {"code": "padiem_service_unavailable"}})
        self.assertEqual(module._bounded_b66_interpret_failure(
            body, {"x-b66-upstream-class": "provider_server_error"}
        ), ("padiem_service_unavailable", "PAGES_UPSTREAM_PROXY", "UNCLASSIFIED"))

    def test_malformed_or_unlisted_payload_and_header_are_opaque(self):
        for body in (
            None, "{not json", json.dumps({"error": {"code": "PRIVATE"}}),
            json.dumps({"error": {"code": "quote_interpretation_failed"}}) + "X" * 8192,
            json.dumps({"error": {"message": "contains private input"}}),
        ):
            self.assertEqual(
                module._bounded_b66_interpret_failure(
                    body, {"x-b66-upstream-class": "PRIVATE or customer text"}
                ),
                ("UNCLASSIFIED", "UNCLASSIFIED", "UNCLASSIFIED"),
            )
        valid_body = '{"error":{"code":"quote_interpretation_failed"}}'
        self.assertEqual(module._bounded_b66_interpret_failure(
            valid_body, {"x-b66-upstream-class": "private.example.com"}
        ), ("quote_interpretation_failed", "B66_INTERPRETER_ROUTE", "UNCLASSIFIED"))

    def test_prints_only_enumerated_fields_and_never_raw_response(self):
        class SyntheticResponse:
            headers = {"content-type": "application/json",
                       "x-b66-upstream-class": "upstream_binding_unavailable",
                       "cookie": "NEVER_PRINT"}
            def text(self):
                return json.dumps({"error": {
                    "code": "quote_interpretation_failed",
                    "message": "NEVER_PRINT",
                    "customer": {"company": "NEVER_PRINT"}
                }})
        output = io.StringIO()
        with redirect_stdout(output):
            module._print_bounded_b66_interpret_failure(SyntheticResponse())
        lines = output.getvalue().splitlines()
        self.assertEqual(lines, [
            "B66_INTERPRET_ERROR_CODE=quote_interpretation_failed",
            "B66_INTERPRET_ERROR_LAYER=B66_INTERPRETER_ROUTE",
            "B66_INTERPRET_UPSTREAM_CLASS=upstream_binding_unavailable",
            "B66_INTERPRET_FAILURE_STAGE=UNCLASSIFIED",
            "B66_INTERPRET_EXCEPTION_FAMILY=UNCLASSIFIED",
        ])
        self.assertNotIn("NEVER_PRINT", output.getvalue())

    def test_diagnostics_are_fail_only_and_budget_unchanged(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for variable in ("response", "first", "second"):
            self.assertIn(
                f"if {variable}.status != 200:\n"
                f"        _print_bounded_b66_interpret_failure({variable})",
                source
            )
        self.assertEqual(module.MAX_INTERPRET_POSTS, 3)
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)


class ClawOneShotPreNetworkTests(unittest.TestCase):
    """#3523: failure controls must abort before requests leave Chromium."""

    class Request:
        def __init__(self, method: str, url: str, body=None) -> None:
            self.method = method
            self.url = url
            self.post_data_json = body

    class Route:
        def __init__(self) -> None:
            self.actions: list[str] = []

        def continue_(self) -> None:
            self.actions.append("network")

        def abort(self, reason: str) -> None:
            self.actions.append("abort:" + reason)

    def dispatch(self, guard, method, url, body=None):
        route = self.Route()
        guard.route_request(route, self.Request(method, url, body))
        return route.actions

    def test_first_approved_post_continues_exactly_once(self):
        g = module._ClawOutboundGuard()
        url = module.CLAW_TARGET_URL.rstrip("/") + module.CLAW_GENERAL_PATH
        actions = self.dispatch(g, "POST", url, {"model_id": module.CLAW_OWNER_SELECTED_MODEL_ID})
        self.assertEqual(actions, ["network"])
        self.assertEqual(g.claw_posts, 1)
        self.assertEqual(self.dispatch(
            g, "POST", module.CLAW_TARGET_URL.rstrip("/") + "/api/auth/password/login",
            {"username": "stub"},
        ), ["network"])
        self.assertEqual(g.claw_posts, 1)
        g.assert_clean()

    def test_second_post_aborted_before_network_and_detected(self):
        g = module._ClawOutboundGuard()
        url = module.CLAW_TARGET_URL.rstrip("/") + module.CLAW_GENERAL_PATH
        payload = {"model_id": module.CLAW_OWNER_SELECTED_MODEL_ID}
        self.assertEqual(self.dispatch(g, "POST", url, payload), ["network"])
        self.assertEqual(self.dispatch(g, "POST", url, payload), ["abort:blockedbyclient"])
        self.assertEqual(g.claw_posts, 1)
        self.assertEqual(g.blocked_duplicate_posts, 1)
        with self.assertRaisesRegex(module.SmokeFailure, "blocked_second_claw_post"):
            g.assert_clean()

    def test_wrong_or_missing_model_aborted_with_zero_posts(self):
        url = module.CLAW_TARGET_URL.rstrip("/") + module.CLAW_GENERAL_PATH
        for body in ({}, {"model_id": "unapproved/model"}, None, "text"):
            with self.subTest(body=body):
                g = module._ClawOutboundGuard()
                self.assertEqual(self.dispatch(g, "POST", url, body), ["abort:blockedbyclient"])
                self.assertEqual(g.claw_posts, 0)
                with self.assertRaisesRegex(module.SmokeFailure, "blocked_unapproved_model"):
                    g.assert_clean()

    def test_direct_provider_aborted_but_google_fonts_css_allowed(self):
        g = module._ClawOutboundGuard()
        self.assertEqual(self.dispatch(g, "GET", "https://fonts.googleapis.com/css2?family=Manrope"), ["network"])
        self.assertEqual(self.dispatch(g, "POST", "https://generativelanguage.googleapis.com/v1/models"), ["abort:blockedbyclient"])
        self.assertEqual(self.dispatch(g, "POST", "https://api.openai.com/v1/chat/completions"), ["abort:blockedbyclient"])
        self.assertEqual(g.blocked_direct_provider, 2)
        with self.assertRaisesRegex(module.SmokeFailure, "blocked_browser_direct_provider"):
            g.assert_clean()

    def test_off_origin_claw_post_blocked_and_not_counted(self):
        g = module._ClawOutboundGuard()
        self.assertEqual(self.dispatch(
            g, "POST", "https://evil.invalid/api/claw/general",
            {"model_id": module.CLAW_OWNER_SELECTED_MODEL_ID},
        ), ["abort:blockedbyclient"])
        self.assertEqual(g.claw_posts, 0)
        with self.assertRaisesRegex(module.SmokeFailure, "blocked_untrusted_claw_target"):
            g.assert_clean()

    def test_claw_runtime_installs_pre_network_route_guard(self):
        text = SCRIPT.read_text(encoding="utf-8")
        owner = text[text.index("def run_claw_owner_one_shot("):text.index("\ndef self_test(")]
        self.assertIn('context.route("**/*", guarded_route)', owner)
        self.assertIn('service_workers="block"', owner)
        self.assertIn("guard.route_request(route, route.request)", owner)
        self.assertIn("guard.assert_clean()", owner)
        self.assertNotIn('page.on("request", observe_request)', owner)
        self.assertNotIn("assistant-message:last-of-type .typing", owner)

    @unittest.skipUnless(shutil.which("node"), "Node required to evaluate terminal predicate")
    def test_terminal_lifecycle_js_negative_controls(self):
        # Execute the same JavaScript predicate the actual browser waits on.
        # DOM stubs distinguish nonempty text from the authoritative lifecycle.
        js = r"""
const predicate = eval('(' + process.argv[1] + ')');
function caseOf(status, content, error, count) {
  const article = {
    dataset: { lifecycle: status },
    querySelector(selector) {
      if (selector === '.assistant-content') return { innerText: content };
      if (selector === '.error-box') return error ? {} : null;
      return null;
    }
  };
  global.document = { querySelectorAll() {
    return Array(count).fill(article);
  }};
  return predicate(0);
}
const assert = require('node:assert/strict');
assert.equal(caseOf('completed', '정상 답변', false, 1), true);
assert.equal(caseOf('streaming', '정상 답변', false, 1), false);
assert.equal(caseOf('failed', '정상 답변', false, 1), false);
assert.equal(caseOf('cancelled', '정상 답변', false, 1), false);
assert.equal(caseOf('completed', '  ', false, 1), false);
assert.equal(caseOf('completed', '정상 답변', true, 1), false);
assert.equal(caseOf('completed', '정상 답변', false, 0), false);
assert.equal(caseOf('completed', '정상 답변', false, 2), false);
"""
        completed = subprocess.run(
            ["node", "-e", js, module.CLAW_ASSISTANT_COMPLETED_JS],
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class CanaryEvidenceSeamTests(unittest.TestCase):
    """#3655: the one-shot canary's bounded evidence contract."""

    def test_failure_detail_vocabulary_mirrors_kagent_port_exactly(self):
        # The smoke script cannot import product packages, so the vocabulary
        # is mirrored as a literal. This sync test fails if the port's closed
        # P01_FAILURE_DETAILS vocabulary and the mirror ever drift apart.
        adapter_source = (
            Path(__file__).parents[2]
            / "apps"
            / "korean-ai-code-agent"
            / "src"
            / "kagent"
            / "p01_adapter.py"
        ).read_text(encoding="utf-8")
        port_details = set(
            re.findall(
                r'^P01_FAILURE_DETAIL_[A-Z_]+ = "([a-z0-9_]+)"$',
                adapter_source,
                re.MULTILINE,
            )
        )
        self.assertTrue(port_details)
        self.assertEqual(port_details, set(module.CLAW_FAILURE_DETAIL_VOCABULARY))

    def test_evidence_header_allowlist_is_the_chat_route_vocabulary(self):
        self.assertEqual(
            set(module.CLAW_EVIDENCE_RESPONSE_HEADERS),
            {
                "x-padiem-claw-run-id",
                "x-padiem-orchestration-run-id",
                "x-padiem-selected-route-id",
                "x-padiem-provider-attempts",
                "x-padiem-fallback-used",
            },
        )
        route_source = (
            Path(__file__).parents[2]
            / "apps"
            / "padiem-chat"
            / "app"
            / "claw_general_routes.py"
        ).read_text(encoding="utf-8")
        for header in module.CLAW_EVIDENCE_RESPONSE_HEADERS:
            canonical = "-".join(word.capitalize() for word in header.split("-"))
            self.assertIn(canonical, route_source)
        self.assertIn(module.CLAW_EVIDENCE_MARKER, route_source)

    def test_bounded_evidence_headers_drop_unlisted_and_malformed(self):
        good = {
            "x-padiem-claw-run-id": "run_" + "b" * 24,
            "x-padiem-orchestration-run-id": "orch_test_001",
            "x-padiem-selected-route-id": "plus.agnes-3.0-flash.v1",
            "x-padiem-provider-attempts": "1",
            "x-padiem-fallback-used": "false",
        }
        self.assertEqual(module._bounded_evidence_headers(good), good)
        self.assertEqual(module._bounded_evidence_headers({"x-padiem-claw-run-id": "junk"}), {})
        self.assertEqual(module._bounded_evidence_headers(None), {})

    def test_bounded_error_class_never_carries_message_or_free_text(self):
        body = json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "engine_execution_failed",
                    "message": "Engine 실행에 실패했습니다.",
                    "detail": "engine_provider_server_error",
                },
            }
        )
        self.assertEqual(
            module._bounded_error_class(body),
            ("engine_execution_failed", "engine_provider_server_error"),
        )
        # Out-of-vocabulary detail degrades to None; the message never survives.
        leaky = json.dumps(
            {"error": {"code": "engine_execution_failed", "detail": "prompt tokens xyz"}}
        )
        self.assertEqual(module._bounded_error_class(leaky), ("engine_execution_failed", None))
        self.assertEqual(module._bounded_error_class("not json"), (None, None))

    def test_admission_result_mapping_is_fail_closed(self):
        self.assertEqual(module._canonical_admission_result("engine_admission_denied"), "DENIED")
        self.assertEqual(module._canonical_admission_result("engine_provider_timeout"), "UNPROVEN")
        self.assertEqual(module._canonical_admission_result(None), "UNPROVEN")

    def test_owner_selected_model_is_bound_to_the_exact_claw_post(self):
        self.assertEqual(module.CLAW_OWNER_SELECTED_MODEL_ID, "agnes-ai/agnes-3.0-flash")
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('page.locator("#clawModelIdInput")', source)
        self.assertIn("model_input.fill(CLAW_OWNER_SELECTED_MODEL_ID)", source)
        self.assertIn("response.request.post_data_json", source)
        self.assertIn('submitted.get("model_id") != CLAW_OWNER_SELECTED_MODEL_ID', source)
        self.assertIn("EXPLICIT_MODEL_ID_IN_CLAW_POST=PASS", source)

    def test_one_shot_bounds_are_unchanged(self):
        self.assertEqual(module.MAX_CLAW_GENERAL_POSTS, 1)
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)
        self.assertEqual(module.CLAW_EVIDENCE_MARKER, "one-shot")


if __name__ == "__main__":
    unittest.main()
