"""Contract tests for the offline B14 model-evaluation harness."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b14_model_evaluation.py"
spec = importlib.util.spec_from_file_location("b14_model_evaluation", SCRIPT)
assert spec and spec.loader
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)


def _json(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _transport(calls: list[tuple[str, str, dict | None]]):
    def send(method: str, path: str, body: dict | None):
        calls.append((method, path, body))
        case = body["messages"][0]["content"]
        if "상자" in case:
            content = "정답은 B입니다. 세 문장 중 B에만 참이 하나입니다."
        elif "정확히 세 줄" in case:
            content = "요약: 비 때문\n우산으로\n몸을 젖힘"
        elif "핵심만 두 문장" in case:
            content = "토요일 오전 10시부터 오후 1시까지 전기 점검이 예정되어 있습니다. 점검 중 엘리베이터가 중단될 수 있으니 금요일까지 휴대전화를 충전해 주세요."
        else:
            content = "응답입니다."
        model = body["model"].split("/")[-1]
        return 200, _json({
            "model": model,
            "choices": [{"message": {"content": content}}],
            "business14": {
                "actual_response_model": model,
                "fallback_used": False,
                "attempt_count": 1,
            },
        })
    return send


def test_fixture_is_shared_synthetic_six_case_corpus() -> None:
    fixture = harness.load_fixture()
    assert fixture["version"] == "padiem-tier-benchmark-v1"
    assert len(fixture["cases"]) == 6
    assert fixture["provider_calls_authorized"] is False


def test_only_five_manual_pin_candidates_are_in_scope() -> None:
    assert harness.EVALUATION_CANDIDATE_IDS == ("agnes", "motif", "mercury", "atria", "luna")
    assert all(cid in harness.CANDIDATE_REGISTRY for cid in harness.EVALUATION_CANDIDATE_IDS)
    assert "b14/auto" not in {harness.CANDIDATE_REGISTRY[cid].model_id for cid in harness.EVALUATION_CANDIDATE_IDS}


def test_default_cli_is_inert_and_reports_zero_live_calls(capsys) -> None:
    assert harness.main([]) == 0
    output = capsys.readouterr().out
    assert "B14_MODEL_EVALUATION=BLOCKED" in output
    assert "LIVE_PROVIDER_CALL=0" in output
    assert "PRODUCTION_MUTATION=0" in output


def test_evaluate_candidate_uses_same_fixture_and_records_bounded_evidence() -> None:
    calls: list[tuple[str, str, dict | None]] = []
    report = harness.evaluate_candidate("agnes", _transport(calls), clock=iter([0.0, 0.01] * 6).__next__)
    assert report["live_provider_call"] is False
    assert report["case_count"] == 6
    assert len(calls) == 6
    assert all(method == "POST" and path == harness.CHAT_PATH for method, path, _ in calls)
    assert all(body["model"] == "agnes-ai/agnes-3.0-flash" for _, _, body in calls)
    assert report["objective_total"] == report["objective_passed"] == 4
    assert report["manual_review_required"] is True
    assert report["status"] == "PASS"
    for case in report["cases"]:
        assert len(case["response_hash"]) == 64
        assert "prompt" not in case
        assert "content" not in case
        assert case["fallback_used"] is False
        assert case["attempt_count"] == 1


def test_unknown_candidate_fails_closed() -> None:
    with pytest.raises(ValueError, match="candidate_not_manual_pin"):
        harness.evaluate_candidate("poolside", _transport([]))
    with pytest.raises(ValueError, match="candidate_not_manual_pin"):
        harness.evaluate_candidate("b14/auto", _transport([]))


def test_duplicate_or_unknown_fixture_case_is_rejected(tmp_path: Path) -> None:
    fixture = harness.load_fixture()
    fixture["cases"][1]["id"] = fixture["cases"][0]["id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="fixture_case_duplicate_or_invalid"):
        harness.load_fixture(path)

    fixture = harness.load_fixture()
    fixture["cases"][0]["id"] = "UNKNOWN-001"
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="fixture_case_unknown_or_missing"):
        harness.load_fixture(path)


def test_model_mismatch_fallback_and_attempts_fail_closed() -> None:
    def bad_transport(method: str, path: str, body: dict | None):
        return 200, _json({
            "model": "wrong-model",
            "choices": [{"message": {"content": "응답입니다."}}],
            "business14": {"actual_response_model": "wrong-model", "fallback_used": True, "attempt_count": 2},
        })

    report = harness.evaluate_candidate("agnes", bad_transport)
    assert report["status"] == "FAIL_CLOSED"
    assert set(report["cases"][0]["contract_errors"]) == {
        "actual_model_missing_or_mismatch", "silent_fallback", "attempt_count_not_one"
    }


def test_malformed_or_oversized_result_fails_closed() -> None:
    def malformed(method: str, path: str, body: dict | None):
        return 200, b"not-json"

    report = harness.evaluate_candidate("atria", malformed)
    assert report["status"] == "FAIL_CLOSED"
    assert report["cases"][0]["contract_errors"] == ["malformed_or_oversized_result"]


def test_http_failure_is_recorded_without_exposing_response() -> None:
    def failed_transport(method: str, path: str, body: dict | None):
        return 503, _json({"error": {"code": "no_safe_route", "message": "private detail"}})

    report = harness.evaluate_candidate("motif", failed_transport)
    case = report["cases"][0]
    assert case["http_status"] == 503
    assert case["error_code"] == "no_safe_route"
    assert "private detail" not in json.dumps(report)


def test_fallback_and_attempt_count_are_preserved_as_evidence() -> None:
    def fallback_transport(method: str, path: str, body: dict | None):
        return 200, _json({
            "model": "wrong-model",
            "choices": [{"message": {"content": "x"}}],
            "business14": {"actual_response_model": "wrong-model", "fallback_used": True, "attempt_count": 2},
        })

    report = harness.evaluate_candidate("luna", fallback_transport)
    assert report["cases"][0]["actual_model"] == "wrong-model"
    assert report["cases"][0]["fallback_used"] is True
    assert report["cases"][0]["attempt_count"] == 2
