"""Offline unit coverage for the no-POST exact Kira QKR-008 single receipt assessor."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
MODULE = SCRIPTS / "b14_kira_qkr_single_receipt.py"
spec = importlib.util.spec_from_file_location("b14_kira_qkr_single_receipt", MODULE)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def valid_receipt():
    case = probe.expected_case()
    raw = {
        "source": {"kind": "text"},
        "recipient": {"company": case["expected"]["recipient_company"]},
        "quote": {"projectName": case["expected"]["project_name"],
                  "issueDate": case["expected"]["issue_date"]},
        "items": copy.deepcopy(case["expected"]["items"]),
        "tax": {"mode": "EXCLUSIVE"},
        "warnings": [],
    }
    return {
        "case_id": probe.CASE_ID, "model_id": probe.MODEL_ID, "http_status": 200,
        "response": {
            "choices": [{"message": {"role": "assistant",
                                     "content": json.dumps(raw, ensure_ascii=False)},
                         "finish_reason": "stop"}],
            "business14": {
                "selected_model": probe.MODEL_ID,
                "selected_upstream_model": probe.expected_model()["upstream_model"],
                "actual_response_model": probe.expected_model()["upstream_model"],
                "route_mode": "manual", "attempt_count": 1, "fallback_used": False,
            }
        }
    }


class OfflineReceiptTests(unittest.TestCase):
    def test_plan_never_calls_provider_and_reads_exact_registration(self):
        plan = probe.plan()
        self.assertEqual(plan["model_id"], "kira/qwen3.8-flash-free")
        self.assertEqual(plan["provider_post_count"], 0)
        self.assertFalse(plan["provider_call_authorized_by_this_tool"])
        self.assertFalse(plan["actual_kira_qkr_proven"])

    def test_synthetic_gold_facts_and_quote_core_arithmetic(self):
        verdict = probe.evaluate_imported(valid_receipt())
        self.assertEqual(verdict["verdict"], "SINGLE_CASE_FACTS_AND_MATH_MATCH")
        self.assertTrue(verdict["qkr_fact_match"])
        self.assertTrue(verdict["quote_core_expected_totals_match"])
        self.assertEqual(verdict["quote_core_supply"], 6_500_000)
        self.assertEqual(verdict["quote_core_vat"], 650_000)
        self.assertEqual(verdict["quote_core_grand"], 7_150_000)
        self.assertEqual(verdict["qkr_mismatched_field_count"], 0)
        self.assertEqual(verdict["qkr_mismatched_item_field_count"], 0)
        self.assertEqual(verdict["provenance"], "IMPORTED_RESPONSE_NOT_ATTESTED_LIVE")
        self.assertFalse(verdict["model_quality_ranking_eligible"])
        self.assertEqual(verdict["real_provider_post_by_this_tool"], 0)

    def test_wrong_field_content_graded_fail_without_leaking_strings(self):
        bad = valid_receipt()
        answer = json.loads(bad["response"]["choices"][0]["message"]["content"])
        answer["recipient"]["company"] = "private wrong customer"
        bad["response"]["choices"][0]["message"]["content"] = json.dumps(answer)
        result = probe.evaluate_imported(bad)
        self.assertEqual(result["verdict"], "SINGLE_CASE_FACTS_OR_MATH_MISMATCH")
        self.assertEqual(result["qkr_mismatched_field_count"], 1)
        self.assertNotIn("private", json.dumps(result).lower())

    def test_item_mismatch_and_unauthorized_tax_mode_fail(self):
        for mutation in ("qty", "tax"):
            with self.subTest(mutation=mutation):
                bad = valid_receipt()
                answer = json.loads(bad["response"]["choices"][0]["message"]["content"])
                if mutation == "qty":
                    answer["items"][2]["qty"] = 77
                else:
                    answer["tax"]["mode"] = "INCLUSIVE"
                bad["response"]["choices"][0]["message"]["content"] = json.dumps(answer)
                result = probe.evaluate_imported(bad)
                self.assertEqual(result["verdict"], "SINGLE_CASE_FACTS_OR_MATH_MISMATCH")

    def test_fail_closed_bad_status_identity_retry_fallback_and_completion(self):
        changes = (
            ("http_status", lambda e: e.update(http_status=429)),
            ("wrong_case", lambda e: e.update(case_id="QKR-001")),
            ("wrong_model", lambda e: e.update(model_id="google/gemini-3.1-flash-lite")),
            ("wrong_selected", lambda e: e["response"]["business14"].update(selected_model="other")),
            ("wrong_upstream", lambda e: e["response"]["business14"].update(actual_response_model="other")),
            ("wrong_selected_upstream", lambda e: e["response"]["business14"].update(selected_upstream_model="other")),
            ("retry", lambda e: e["response"]["business14"].update(attempt_count=2)),
            ("attempt_bool", lambda e: e["response"]["business14"].update(attempt_count=True)),
            ("fallback", lambda e: e["response"]["business14"].update(fallback_used=True)),
            ("fallback_int", lambda e: e["response"]["business14"].update(fallback_used=0)),
            ("auto", lambda e: e["response"]["business14"].update(route_mode="auto")),
            ("empty", lambda e: e["response"]["choices"][0]["message"].update(content="")),
            ("length", lambda e: e["response"]["choices"][0].update(finish_reason="length")),
            ("json_fence", lambda e: e["response"]["choices"][0]["message"].update(content="```json {} ```")),
        )
        for name, mutate in changes:
            with self.subTest(name=name):
                bad = valid_receipt()
                mutate(bad)
                with self.assertRaises(ValueError):
                    probe.evaluate_imported(bad)

    def test_imported_receipt_cli_and_oversize_guards(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Path(folder) / "private-b14-response.json"
            f.write_text(json.dumps(valid_receipt(), ensure_ascii=False), encoding="utf-8")
            result = probe.read_receipt(f)
            self.assertEqual(result["case_id"], "QKR-008")
            with redirect_stdout(io.StringIO()) as out:
                exit_code = probe.main(["--response-file", str(f)])
            self.assertEqual(exit_code, 0)
            public = json.loads(out.getvalue())
            self.assertEqual(public["verdict"], "SINGLE_CASE_FACTS_AND_MATH_MATCH")
            self.assertEqual(public["real_provider_post_by_this_tool"], 0)
            self.assertNotIn("items", public)
            f.write_bytes(b"x" * (probe.MAX_RECEIPT_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "receipt_missing_or_too_large"):
                probe.read_receipt(f)

    def test_cli_plan_stays_offline_without_arguments(self):
        with redirect_stdout(io.StringIO()) as out:
            exit_code = probe.main([])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(out.getvalue())["provider_post_count"], 0)


if __name__ == "__main__":
    unittest.main()
