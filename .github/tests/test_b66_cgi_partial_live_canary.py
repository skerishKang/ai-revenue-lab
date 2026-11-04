from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "b66_cgi_partial_live_canary.py"
SPEC = importlib.util.spec_from_file_location("b66_cgi_partial_live_canary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class CanaryContractTests(unittest.TestCase):
    def test_one_shot_and_no_retry_contract(self):
        self.assertEqual(module.MAX_INTERPRET_POSTS, 1)
        self.assertEqual(module.USER_AGENT, "padiem-b66-cgi-partial-canary/1.0 (+github-actions)")
        self.assertEqual(module.RETRY, 0)
        self.assertEqual(module.FALLBACK, 0)

    def test_approximate_case_requires_explicit_allowlisted_selector(self):
        self.assertEqual(module.selected_case("partial"), "partial")
        self.assertEqual(module.selected_case("approx_qty"), "approx_qty")
        for invalid in (None, "", "auto", "all", "approx", 1):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.selected_case(invalid)
        script = SCRIPT.read_text(encoding="utf8")
        self.assertIn('os.getenv(CASE_ENV)', script)
        self.assertIn('"message": PARTIAL_TEXT if case == "partial" else APPROX_QUANTITY_TEXT', script)
        wf = (SCRIPT.parents[1] / "workflows" / "b66-cgi-partial-live-canary.yml").read_text(encoding="utf8")
        self.assertIn("quote_case:", wf)
        self.assertIn("B66_CGI_CANARY_CASE: " + chr(36) + "{{ inputs.quote_case }}", wf)
        self.assertIn("- approx_qty", wf)

    def test_exact_vs_approximate_quantity_authority_is_fail_closed(self):
        origin = module.MODEL_COMPLETION_ORIGIN
        constant = {
            "SAFE_RECIPIENT_MATCH": "TRUE",
            "SAFE_ITEM_MATCH": "TRUE",
            "UNIT_PRICE_NULL": "TRUE",
            "SAFE_QTY_MATCH": "TRUE",
            "APPROX_QTY_NULL": "FALSE",
        }
        exact = {"missing": ["unitPrice"]}
        rough = {"missing": ["qty", "unitPrice"]}
        self.assertTrue(module._canary_contract_satisfied(
            "partial", response_status=200, origin=origin,
            candidate=exact, summary=constant,
        ))
        rough_state = {**constant, "SAFE_QTY_MATCH": "FALSE", "APPROX_QTY_NULL": "TRUE"}
        self.assertTrue(module._canary_contract_satisfied(
            "approx_qty", response_status=200, origin=origin,
            candidate=rough, summary=rough_state,
        ))
        for changed in (
            {"missing": ["unitPrice"]},       # rough qty silently committed
            {"missing": []},                  # wrongly finalized
            {"missing": ["qty"]},             # model invented price
        ):
            self.assertFalse(module._canary_contract_satisfied(
                "approx_qty", response_status=200, origin=origin,
                candidate=changed, summary=rough_state,
            ))
        self.assertFalse(module._canary_contract_satisfied(
            "approx_qty", response_status=200, origin=origin,
            candidate=rough, summary={**rough_state, "APPROX_QTY_NULL": "FALSE"},
        ))
        self.assertFalse(module._canary_contract_satisfied(
            "approx_qty", response_status=200, origin=module.FALLBACK_ORIGIN,
            candidate=rough, summary=rough_state,
        ))
        self.assertFalse(module._canary_contract_satisfied(
            "approx_qty", response_status=502, origin=origin,
            candidate=rough, summary=rough_state,
        ))
        self.assertFalse(module._canary_contract_satisfied(
            "unknown", response_status=200, origin=origin,
            candidate=rough, summary=rough_state,
        ))

    def test_operator_grade_key_selection_is_required(self):
        offered = [{"tier": "free", "name": "g"}, {"tier": "plus", "name": "g"}]
        self.assertEqual(module.selected_tier(None, offered), module.DEFAULT_SELECTED_TIER)
        self.assertEqual(module.selected_tier("free", offered), "free")
        for bad_value in ("unknown", "freex", 1, True):
            with self.subTest(bad=bad_value), self.assertRaises(ValueError):
                module.selected_tier(bad_value, offered)
        with self.assertRaises(ValueError):
            module.selected_tier("max", offered)          # not offered by the deployment
        with self.assertRaises(ValueError):
            module.selected_tier("free", None)            # no offered list at all
        with self.assertRaises(ValueError):
            module.selected_tier("free", offered + [offered[0]])  # ambiguous rows

    def test_grade_options_contract_refuses_a_response_that_names_a_model(self):
        clean = {"ok": True, "tiers": [{"tier": "free", "name": "g"}], "default_tier": "free"}
        self.assertTrue(module.grade_options_contract(clean))
        self.assertFalse(module.grade_options_contract(
            {"ok": True, "tiers": [{"tier": "free", "name": "g", "model_id": "x/y"}],
             "default_tier": None}))
        self.assertFalse(module.grade_options_contract(
            {"ok": True, "tiers": [], "default_tier": None, "models": []}))
        self.assertFalse(module.grade_options_contract(
            {"ok": True, "tiers": [{"tier": "unknown-grade"}], "default_tier": None}))
        self.assertFalse(module.grade_options_contract({"ok": False, "tiers": []}))
        script = SCRIPT.read_text(encoding="utf8")
        # The old contract read a model catalog from the customer response.
        self.assertNotIn("selected_model_id(", script)
        self.assertNotIn('"model_id": chosen_model_id', script)

    def test_canary_submits_the_chosen_grade_and_verifies_the_contract(self):
        source = SCRIPT.read_text(encoding="utf8")
        self.assertIn('"tier": chosen_tier', source)
        self.assertIn('"/api/padiem/b66/quote/models"', source)
        self.assertIn('SELECTED_TIER_ENV = "B66_CGI_CANARY_SELECTED_TIER"', source)
        self.assertIn('summary["GRADE_OPTIONS_CONTRACT"] = "PASS"', source)
        wf = (SCRIPT.parents[1] / "workflows" / "b66-cgi-partial-live-canary.yml").read_text(encoding="utf8")
        self.assertIn("selected_tier:", wf)
        self.assertIn('default: "plus"', wf)
        self.assertIn("B66_CGI_CANARY_SELECTED_TIER: " + chr(36) + "{{ inputs.selected_tier }}", wf)


    def test_every_computed_marker_is_actually_emitted(self):
        """A check whose result is never printed is not evidence.

        The live run against the deployed grade contract computed the grade
        options result and the interpreter failure stage, then printed neither,
        because _print_summary still listed the retired model-catalog keys. This
        drives run_live end to end with zero network and fails if any marker the
        flow sets disappears from the emitted summary.
        """
        import io
        import json
        from contextlib import redirect_stdout
        from email.message import Message
        from unittest.mock import patch

        grade_rows = {"ok": True, "tiers": [{"tier": "free", "name": "grade"}],
                      "default_tier": "free"}
        refused_headers = Message()
        refused_headers["X-B66-Interpret-Failure-Stage"] = "interpreter_exception"
        refused_headers["X-B66-Interpret-Exception-Family"] = "type_error"
        replies = {
            "/api/padiem/auth/password/login": (200, Message(), b'{"ok": true}'),
            "/api/padiem/auth/status": (200, Message(), b'{"authenticated": true}'),
            "/api/padiem/b66/saved-skills?limit=20": (
                200, Message(),
                json.dumps({"ok": True, "skills": [
                    {"saved_skill_id": "b66skill_" + "0" * 32}]}).encode("utf8")),
            "/api/padiem/b66/quote/models": (
                200, Message(), json.dumps(grade_rows).encode("utf8")),
            "/api/padiem/b66/quote/interpret": (
                502, refused_headers,
                b'{"ok": false, "error": {"code": "quote_interpretation_failed"}}'),
        }
        seen = []

        def fake_json_request(opener, path, method="GET", payload=None):
            seen.append((method, path, payload))
            status, headers, body = replies[path]
            return module.SafeHttpResult(status=status, headers=headers, body=body)

        buffer = io.StringIO()
        with patch.object(module, "_json_request", side_effect=fake_json_request), \
                patch.dict("os.environ", {module.CASE_ENV: "partial",
                                          module.SELECTED_TIER_ENV: "free"}):
            with redirect_stdout(buffer):
                code = module.run_live("synthetic-canary-user", "synthetic-password")
        emitted = buffer.getvalue()
        self.assertEqual(code, 7)
        self.assertIn("B66_CGI_PARTIAL_CANARY=FAIL", emitted)
        for marker in ("GRADE_OPTIONS_HTTP=200", "GRADE_OPTIONS_CONTRACT=PASS",
                       "SELECTED_TIER=free", "INTERPRET_HTTP=502",
                       "INTERPRET_FAILURE_STAGE=interpreter_exception",
                       "INTERPRET_EXCEPTION_FAMILY=type_error",
                       "PUBLIC_ERROR=quote_interpretation_failed",
                       "INTERPRET_POSTS=1"):
            self.assertIn(marker, emitted)
        for retired in ("MODEL_OPTIONS_HTTP", "MODEL_SELECTION_RESULT", "SELECTED_MODEL_ID"):
            self.assertNotIn(retired, emitted)
        # The refused request carried the grade key and no model identity.
        self.assertEqual(seen[-1][:2], ("POST", "/api/padiem/b66/quote/interpret"))
        self.assertEqual(seen[-1][2]["tier"], "free")
        self.assertNotIn("model_id", seen[-1][2])

    def test_interpret_stage_and_family_headers_are_closed_allowlists(self):
        route = (SCRIPT.parents[2] / "apps" / "padiem-chat" / "app" /
                 "b66_quote_routes.py").read_text(encoding="utf8")
        # Every value the deployed route can send must be in the allowlist, or a
        # real stage would be reported as unknown exactly when it matters.
        for stage in ("interpreter_exception", "projection_missing_safe_dict",
                      "model_selection", "runtime_unavailable",
                      "provider_execution", "provider_response"):
            self.assertIn(f'"{stage}"', route)
            self.assertEqual(module.sanitize_interpret_stage(stage), stage)
        for family in ("chat_runtime_non_upstream", "type_error", "value_error",
                       "runtime_error", "unexpected_exception"):
            self.assertIn(f'"{family}"', route)
            self.assertEqual(module.sanitize_exception_family(family), family)
        self.assertEqual(module.sanitize_interpret_stage("raw-secret"), "ABSENT_OR_UNKNOWN")
        self.assertEqual(module.sanitize_exception_family(None), "ABSENT_OR_UNKNOWN")

    def test_public_error_code_reads_the_deployed_nested_error_shape(self):
        route = (SCRIPT.parents[2] / "apps" / "padiem-chat" / "app" /
                 "b66_quote_routes.py").read_text(encoding="utf8")
        # The probe's parser must follow the shape the deployment actually sends,
        # otherwise every real error reports as unknown and the canary is blind.
        self.assertIn('{"ok": False, "error": {"code": code, "message": message}}', route)
        self.assertEqual(
            module.public_error_code(
                {"ok": False, "error": {"code": "quote_interpretation_failed"}}),
            "quote_interpretation_failed",
        )
        self.assertEqual(
            module.public_error_code({"error_code": "quote_input_unrecognized"}),
            "quote_input_unrecognized",
        )
        self.assertIsNone(module.public_error_code({"ok": True}))
        self.assertEqual(
            module.sanitize_public_error(
                module.public_error_code({"ok": False, "error": {"code": "raw-secret"}})),
            "ABSENT_OR_UNKNOWN",
        )

    def test_cookie_authenticated_post_includes_exact_same_origin(self):
        # This is an isolated request-construction test: zero network calls.
        from unittest.mock import patch

        requests = []

        def capture(opener, request):
            requests.append(request)
            return module.SafeHttpResult(200, {}, b"{}")

        with patch.object(module, "_request", side_effect=capture):
            module._json_request(object(), "/api/padiem/b66/quote/models")
            module._json_request(
                object(), "/api/padiem/b66/quote/interpret",
                method="POST", payload={"tier": "plus"},
            )
        self.assertEqual(len(requests), 2)
        self.assertIsNone(requests[0].get_header("Origin"))
        self.assertEqual(requests[1].get_header("Origin"), module.BASE_URL)
        source = SCRIPT.read_text(encoding="utf8")
        self.assertIn('summary["LIVE_PROVIDER_CALLS_EXECUTED"] = "UNVERIFIED"', source)

    def test_upstream_class_is_closed_allowlist(self):
        self.assertEqual(
            module.sanitize_upstream_class("upstream_non_text_content"),
            "upstream_non_text_content",
        )
        self.assertEqual(
            module.sanitize_upstream_class("provider raw detail"),
            "ABSENT_OR_UNKNOWN",
        )

    def test_public_error_is_closed_allowlist(self):
        self.assertEqual(
            module.sanitize_public_error("quote_interpretation_failed"),
            "quote_interpretation_failed",
        )
        self.assertEqual(
            module.sanitize_public_error("provider raw detail"),
            "ABSENT_OR_UNKNOWN",
        )

    def test_missing_fields_are_bounded(self):
        self.assertEqual(
            module.sanitize_missing(["unitPrice"]),
            ("unitPrice",),
        )
        self.assertEqual(
            module.sanitize_missing(["private.raw.field"]),
            ("UNKNOWN_FIELD",),
        )

    def test_missing_fields_follow_current_server_contract(self):
        source = (SCRIPT.parents[2] / "apps" / "padiem-chat" / "app" /
                  "b66_quote_conversation.py").read_text(encoding="utf8")
        self.assertIn('for field in ("name", "qty", "unitPrice"):', source)
        self.assertIn('missing.append(field)', source)
        self.assertEqual(module.ALLOWED_MISSING_FIELDS,
                         frozenset({"recipient", "items", "name", "qty", "unitPrice"}))
        # Older indexed diagnostic labels are not returned by this server.
        self.assertEqual(module.sanitize_missing(["items[0].unitPrice"]),
                         ("UNKNOWN_FIELD",))

    def test_success_canary_requires_trusted_model_completion_provenance(self):
        source = SCRIPT.read_text(encoding="utf8")
        route = (SCRIPT.parents[2] / "apps" / "padiem-chat" / "app" /
                 "b66_quote_routes.py").read_text(encoding="utf8")
        self.assertIn('origin != MODEL_COMPLETION_ORIGIN', source)
        self.assertIn('origin=summary["X_B66_RESULT_ORIGIN"]', source)
        self.assertIn('"X-B66-Result-Origin"', route)
        self.assertIn('MODEL_COMPLETION_ORIGIN = "registered_model_completion"', source)
        self.assertIn('FALLBACK_ORIGIN = "deterministic_fallback"', source)
        self.assertIn('"X_B66_RESULT_ORIGIN"', source)
        self.assertNotIn('"answer": interpreted.body', source)

    def test_free_text_diagnostic_is_redacted(self):
        self.assertEqual(
            module._bounded_diagnostic("items[0].unitPrice"),
            "items[0].unitPrice",
        )
        self.assertEqual(
            module._bounded_diagnostic("raw customer detail"),
            "PRESENT_REDACTED",
        )


if __name__ == "__main__":
    unittest.main()
