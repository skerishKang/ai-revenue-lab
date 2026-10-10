"""#2676 / #3554: offline, fail-closed *one-case* Kira B14 quotation receipt assessment.

This program NEVER performs HTTP requests, reads API keys, or invokes providers.
It validates an externally captured HTTP-status + raw B14 response envelope,
then invokes the existing B66 extraction grader and QuoteCore calculation.
Imported response data is NOT independently attested as a live provider call.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from b66_quote_model_benchmark import (  # noqa: E402
    ROOT, grade_case, load_corpus, load_current_models,
)

MODEL_ID = "kira/qwen3.8-flash-free"
CASE_ID = "QKR-008"
MAX_RECEIPT_BYTES = 500_000
B66_QUOTE_DIR = ROOT / "reference" / "business-66-padiem-quote-v1"
_NODE = r"""
const fs = require("node:fs");
const Extract = require(process.argv[1]);
const Core = require(process.argv[2]);
const raw = JSON.parse(fs.readFileSync(0, "utf8"));
const result = Extract.buildDraftCandidate(Core.createProductionDraft(), raw);
if (!result.ok) { process.stdout.write(JSON.stringify({ok:false,error:"invalid_b66_candidate"})); process.exit(0); }
const totals = Core.computeDraftTotals(result.value.draft);
if (!totals) { process.stdout.write(JSON.stringify({ok:false,error:"invalid_quote_core_draft"})); process.exit(0); }
process.stdout.write(JSON.stringify({ok:true,items:result.value.draft.items.length,
  subtotal:totals.subtotal,supply:totals.supply,vat:totals.vat,grand:totals.grand,
  taxMode:totals.mode}));
"""


def expected_model() -> dict[str, Any]:
    """Always re-read the canonical registry; never synthesize another provider."""
    model = load_current_models().get(MODEL_ID)
    if not model or not model.get("enabled", True):
        raise ValueError("kira_model_not_in_canonical_registry")
    if model["provider_id"] != "kira" or model["upstream_model"] != "qwen3.8-flash-free":
        raise ValueError("kira_provider_identity_drift")
    return model


def expected_case() -> dict[str, Any]:
    case = next((row for row in load_corpus()["cases"] if row["id"] == CASE_ID), None)
    if not case or len(case["expected"]["items"]) != 12:
        raise ValueError("qkr008_fixture_invalid")
    return case


def plan() -> dict[str, Any]:
    row = expected_model()
    expected_case()
    return {
        "mode": "OFFLINE_PLAN_ONLY", "model_id": MODEL_ID,
        "provider_id": row["provider_id"], "upstream_model": row["upstream_model"],
        "case_id": CASE_ID, "expected_item_count": 12,
        "http_method_invoked": None,
        "provider_post_count": 0, "secrets_access_count": 0,
        "provider_call_authorized_by_this_tool": False,
        "response_receipt_required": True,
        "actual_kira_qkr_proven": False,
    }


def _quote_core(raw: dict[str, Any]) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["node", "-e", _NODE,
             str(B66_QUOTE_DIR / "quote-extraction.js"),
             str(B66_QUOTE_DIR / "quote-core.js")],
            input=json.dumps(raw, ensure_ascii=False),
            capture_output=True, text=True, timeout=12, check=False,
            encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("quote_core_unavailable") from exc
    if process.returncode or len(process.stdout) > 10_000:
        raise ValueError("quote_core_process_failed")
    try:
        output = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("quote_core_invalid_response") from exc
    if not isinstance(output, dict) or output.get("ok") is not True:
        raise ValueError("quote_core_rejected_extraction")
    return output


def evaluate_imported(receipt: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on *any* ambiguous provenance/route/finish; print no content."""
    row = expected_model()
    case = expected_case()
    if not isinstance(receipt, dict):
        raise ValueError("receipt_not_object")
    if receipt.get("case_id") != CASE_ID or receipt.get("model_id") != MODEL_ID:
        raise ValueError("receipt_case_or_model_mismatch")
    if type(receipt.get("http_status")) is not int or receipt["http_status"] != 200:
        raise ValueError("http_not_200")
    response = receipt.get("response")
    if not isinstance(response, dict):
        raise ValueError("b14_response_not_object")
    b14 = response.get("business14")
    if not isinstance(b14, dict):
        raise ValueError("b14_route_metadata_missing")
    expected = {
        "selected_model": MODEL_ID,
        "selected_upstream_model": row["upstream_model"],
        "actual_response_model": row["upstream_model"],
        "route_mode": "manual",
        "attempt_count": 1,
        "fallback_used": False,
    }
    for key, value in expected.items():
        actual = b14.get(key)
        if type(value) is bool or type(value) is int:
            if type(actual) is not type(value) or actual != value:
                raise ValueError("b14_route_" + key + "_mismatch")
        elif actual != value:
            raise ValueError("b14_route_" + key + "_mismatch")
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("b14_choices_invalid")
    choice = choices[0]
    if choice.get("finish_reason") != "stop":
        raise ValueError("b14_unfinished_or_truncated")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("b14_message_missing")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("b14_empty_answer")
    if len(content.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("b14_content_too_large")
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("b14_answer_not_strict_json") from exc
    if not isinstance(raw, dict):
        raise ValueError("b14_answer_not_json_object")

    # Score against the SAME fixed benchmark corpus & B66 normalizer; no new
    # grader, no prompt echo, no user data or raw model response in output.
    try:
        grade = grade_case(case, raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("b66_extraction_invalid") from exc
    try:
        money = _quote_core(raw)
    except ValueError:
        raise
    correct_totals = (
        money.get("items") == 12 and money.get("supply") == 6_500_000
        and money.get("vat") == 650_000 and money.get("grand") == 7_150_000
        and money.get("taxMode") == "EXCLUSIVE"
    )
    fact_correct = grade["status"] == "PASS"
    return {
        "provenance": "IMPORTED_RESPONSE_NOT_ATTESTED_LIVE",
        "model_id": MODEL_ID,
        "provider_id": row["provider_id"],
        "upstream_model": row["upstream_model"],
        "case_id": CASE_ID,
        "http_status_reported_by_receipt": 200,
        "selected_model_and_upstream_match": True,
        "attempt_count_reported": 1,
        "fallback_used_reported": False,
        "answer_nonempty_and_finished": True,
        "qkr_fact_match": fact_correct,
        "qkr_item_count_match": grade["item_count_correct"],
        "qkr_mismatched_field_count": sum(not ok for ok in grade["field_checks"].values()),
        "qkr_mismatched_item_field_count": sum(
            not ok for rowcheck in grade["item_checks"] for ok in rowcheck.values()
        ),
        "quote_core_item_count": money["items"],
        "quote_core_supply": money["supply"],
        "quote_core_vat": money["vat"],
        "quote_core_grand": money["grand"],
        "quote_core_expected_totals_match": correct_totals,
        "verdict": "SINGLE_CASE_FACTS_AND_MATH_MATCH" if fact_correct and correct_totals
                   else "SINGLE_CASE_FACTS_OR_MATH_MISMATCH",
        "model_quality_ranking_eligible": False,
        "real_provider_post_by_this_tool": 0,
        "real_native_sol_pdf_generated": False,
    }


def read_receipt(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("receipt_missing_or_too_large")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("receipt_invalid_json") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="No-network, one-case Kira QKR receipt assessor")
    parser.add_argument("--response-file", type=Path,
                        help="private existing B14 response receipt JSON; this script never sends a POST")
    args = parser.parse_args(argv)
    try:
        result = evaluate_imported(read_receipt(args.response_file)) if args.response_file else plan()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result.get("verdict", "OFFLINE_PLAN_ONLY") in (
            "SINGLE_CASE_FACTS_AND_MATH_MATCH", "OFFLINE_PLAN_ONLY"
        ) else 3
    except (ValueError, OSError) as exc:
        # Never echo untrusted raw exception strings or private path/contents.
        safe_errors = {
            "kira_model_not_in_canonical_registry", "kira_provider_identity_drift",
            "qkr008_fixture_invalid", "receipt_not_object", "receipt_case_or_model_mismatch",
            "http_not_200", "b14_response_not_object", "b14_route_metadata_missing",
            "b14_choices_invalid", "b14_unfinished_or_truncated", "b14_message_missing",
            "b14_empty_answer", "b14_content_too_large", "b14_answer_not_strict_json",
            "b14_answer_not_json_object", "b66_extraction_invalid",
            "quote_core_unavailable", "quote_core_process_failed",
            "quote_core_invalid_response", "quote_core_rejected_extraction",
            "receipt_missing_or_too_large", "receipt_invalid_json",
        }
        message = str(exc)
        category = message if message in safe_errors or (
            message.startswith("b14_route_") and message.endswith("_mismatch")
            and len(message) < 80
        ) else type(exc).__name__
        print(json.dumps({"status": "BLOCKED", "category": category,
                          "real_provider_post_by_this_tool": 0}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
