"""Offline contract tests for the one-shot comparative benchmark gate."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_model_evaluation_live.py"
spec = importlib.util.spec_from_file_location("b14_model_evaluation_live", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def _json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _transport(calls: list[dict]):
    def send(method: str, path: str, body: dict | None):
        calls.append({"method": method, "path": path, "body": body})
        model = body["model"]
        upstream = {
            "agnes-ai/agnes-3.0-flash": "agnes-3.0-flash",
            "infron/motif/motif-3": "motif/motif-3",
            "inception/mercury-2.5": "mercury-2.5",
            "atria/Atria-Dawn-Preview": "Atria-Dawn-Preview",
            "experiential/gpt-5.6-luna": "gpt-5.6-luna",
        }[model]
        return 200, _json({
            "model": upstream,
            "choices": [{"message": {"content": "검증 가능한 응답입니다."}}],
            "business14": {
                "actual_response_model": upstream,
                "fallback_used": False,
                "attempt_count": 1,
            },
        })
    return send


def test_all_five_is_proven_to_be_exactly_30_posts() -> None:
    calls: list[dict] = []
    result = module.run_comparative_benchmark("all-five", _transport(calls))
    assert result["candidate_count"] == 5
    assert result["case_count_per_candidate"] == 6
    assert result["benchmark_post_count"] == 30
    assert result["max_all_five_posts"] == 30
    assert result["retry"] == 0
    assert result["fallback"] == 0
    assert len(calls) == 30
    assert all(call["method"] == "POST" and call["path"] == module.CHAT_PATH for call in calls)
    assert all(report["status"] == "PASS" for report in result["reports"])


def test_single_candidate_is_exactly_six_posts() -> None:
    calls: list[dict] = []
    result = module.run_comparative_benchmark("mercury", _transport(calls))
    assert result["candidate_count"] == 1
    assert result["benchmark_post_count"] == 6
    assert len(calls) == 6
    assert result["reports"][0]["candidate_id"] == "mercury"


def test_unknown_and_auto_selectors_fail_closed() -> None:
    with pytest.raises(ValueError, match="candidate_selector_not_allowlisted"):
        module.select_candidates("b14/auto")
    with pytest.raises(ValueError, match="candidate_selector_not_allowlisted"):
        module.select_candidates("poolside")


def test_default_cli_is_inert_and_records_source_slice_invariants(capsys) -> None:
    assert module.main([]) == 0
    output = capsys.readouterr().out
    assert "B14_COMPARATIVE_BENCHMARK=BLOCKED" in output
    assert "LIVE_PROVIDER_CALL=0" in output
    assert "WORKFLOW_DISPATCH=0" in output
    assert "SECRET_VALUE_READ=0" in output
    assert "ROUTE_ACTIVATION=0" in output
    assert "PRODUCTION_MUTATION=0" in output


def test_safe_summary_preserves_bounded_comparative_evidence_only() -> None:
    calls: list[dict] = []
    result = module.run_comparative_benchmark("agnes", _transport(calls))
    first_case = result["reports"][0]["cases"][0]
    expected_hash = first_case["response_hash"]
    expected_latency = first_case["latency_ms"]

    # Upstream-controlled diagnostic-like values must never be echoed even when
    # a future provider violates the expected response contract.
    first_case["actual_model"] = "PRIVATE-UPSTREAM-DIAGNOSTIC"
    first_case["attempt_count"] = "PRIVATE-ATTEMPT"

    summary = module._safe_summary(result)
    decoded = json.loads(summary)

    assert decoded["evidence_schema"] == "padiem-b14-comparative-benchmark-v1"
    assert decoded["execution"] == "LIVE_WORKFLOW_DISPATCH"
    assert decoded["benchmark_post_count"] == 6
    assert decoded["reports"][0]["cases"][0]["response_hash"] == expected_hash
    assert decoded["reports"][0]["cases"][0]["latency_ms"] == expected_latency
    assert "objective_checks" in decoded["reports"][0]["cases"][0]
    assert "manual_review" in decoded["reports"][0]["cases"][0]
    assert decoded["reports"][0]["cases"][0]["actual_model_match"] is False
    assert decoded["reports"][0]["cases"][0]["attempt_count_one"] is False

    assert "messages" not in summary
    assert '"content"' not in summary
    assert "PRIVATE-UPSTREAM-DIAGNOSTIC" not in summary
    assert "PRIVATE-ATTEMPT" not in summary
