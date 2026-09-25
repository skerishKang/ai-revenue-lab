"""One-shot B14 comparative benchmark gate source.

The default path is inert. A live run requires an explicit selector and the
``--authorized-live-run`` marker. The source gate itself never reads secrets,
dispatches a workflow, activates routes, or mutates Production.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from b14_candidate_live_smoke import B14_BASE_URL, CHAT_PATH  # noqa: E402
from b14_model_evaluation import (  # noqa: E402
    EVALUATION_CANDIDATE_IDS,
    FIXTURE_PATH,
    evaluate_candidate,
    load_fixture,
)

ALL_FIVE = "all-five"
AUTO_SELECTOR = "b14/auto"
SELECTORS = (ALL_FIVE, *EVALUATION_CANDIDATE_IDS)
MAX_CASES = 6
MAX_ALL_FIVE_POSTS = len(EVALUATION_CANDIDATE_IDS) * MAX_CASES
RETRY = 0
FALLBACK = 0
CONFIRMATION = "RUN_B14_COMPARATIVE_BENCHMARK_ONCE"
Transport = Callable[[str, str, dict[str, Any] | None], tuple[int, bytes]]


def select_candidates(selector: str) -> tuple[str, ...]:
    if selector == ALL_FIVE:
        return EVALUATION_CANDIDATE_IDS
    if selector not in EVALUATION_CANDIDATE_IDS:
        raise ValueError("candidate_selector_not_allowlisted")
    return (selector,)


def urllib_transport(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, bytes]:
    """One bounded request; no retry loop and no secret/header input."""

    if method != "POST" or path != CHAT_PATH:
        raise ValueError("live_transport_route_not_allowed")
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        f"{B14_BASE_URL}{CHAT_PATH}",
        data=payload,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            return response.status, response.read(1_048_577)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1_048_577)


def run_comparative_benchmark(
    selector: str,
    transport: Transport,
    *,
    fixture: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run exactly six posts per selected manual-pin model, with no retry."""

    candidates = select_candidates(selector)
    corpus = fixture or load_fixture(FIXTURE_PATH)
    if len(corpus.get("cases", [])) != MAX_CASES:
        raise ValueError("fixture_case_count_invalid")
    reports = []
    for candidate_id in candidates:
        reports.append(evaluate_candidate(candidate_id, transport, fixture=corpus))
    post_count = len(candidates) * MAX_CASES
    if post_count > MAX_ALL_FIVE_POSTS:
        raise ValueError("benchmark_post_cap_exceeded")
    return {
        "selector": selector,
        "candidate_count": len(candidates),
        "case_count_per_candidate": MAX_CASES,
        "benchmark_post_count": post_count,
        "max_all_five_posts": MAX_ALL_FIVE_POSTS,
        "retry": RETRY,
        "fallback": FALLBACK,
        "fixture_version": corpus["version"],
        "reports": reports,
    }


def _safe_case_evidence(case: dict[str, Any]) -> dict[str, Any]:
    """Project one case without echoing provider-controlled diagnostic strings."""

    return {
        "fixture_version": case["fixture_version"],
        "case_id": case["case_id"],
        "category": case["category"],
        "requested_model_id": case["requested_model_id"],
        "expected_upstream_model": case["expected_upstream_model"],
        "actual_model_match": case["actual_model"] == case["expected_upstream_model"],
        "http_status": case["http_status"],
        "response_hash": case["response_hash"],
        "fallback_used": case["fallback_used"] is True,
        "attempt_count_one": case["attempt_count"] == 1
        and not isinstance(case["attempt_count"], bool),
        "latency_ms": case["latency_ms"],
        "objective_checks": case["objective_checks"],
        "manual_review": case["manual_review"],
        "contract_errors": case["contract_errors"],
        "error_code": case["error_code"],
    }


def _safe_report_evidence(report: dict[str, Any]) -> dict[str, Any]:
    """Project bounded comparative evidence for one allowlisted candidate."""

    return {
        "candidate_id": report["candidate_id"],
        "tier": report["tier"],
        "provider_id": report["provider_id"],
        "model_id": report["model_id"],
        "upstream_model": report["upstream_model"],
        "fixture_version": report["fixture_version"],
        "case_count": report["case_count"],
        "objective_total": report["objective_total"],
        "objective_passed": report["objective_passed"],
        "manual_review_required": report["manual_review_required"],
        "status": report["status"],
        "cases": [_safe_case_evidence(case) for case in report["cases"]],
    }


def _safe_summary(result: dict[str, Any]) -> str:
    """Project bounded benchmark evidence; never serialize prompts/responses."""

    return json.dumps(
        {
            "evidence_schema": "padiem-b14-comparative-benchmark-v1",
            "execution": "LIVE_WORKFLOW_DISPATCH",
            "selector": result["selector"],
            "candidate_count": result["candidate_count"],
            "case_count_per_candidate": result["case_count_per_candidate"],
            "benchmark_post_count": result["benchmark_post_count"],
            "max_all_five_posts": result["max_all_five_posts"],
            "retry": result["retry"],
            "fallback": result["fallback"],
            "fixture_version": result["fixture_version"],
            "reports": [_safe_report_evidence(report) for report in result["reports"]],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in SELECTORS or "--authorized-live-run" not in args[1:]:
        print("B14_COMPARATIVE_BENCHMARK=BLOCKED")
        print("LIVE_PROVIDER_CALL=0")
        print("WORKFLOW_DISPATCH=0")
        print("SECRET_VALUE_READ=0")
        print("ROUTE_ACTIVATION=0")
        print("PRODUCTION_MUTATION=0")
        return 0
    result = run_comparative_benchmark(args[0], urllib_transport)
    print(_safe_summary(result))
    return 0 if all(report["status"] == "PASS" for report in result["reports"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
