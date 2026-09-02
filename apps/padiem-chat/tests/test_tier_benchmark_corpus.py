from __future__ import annotations

import json
from pathlib import Path


REQUIRED_CATEGORIES = {
    "korean_conversation",
    "reasoning",
    "instruction_following",
    "coding",
    "long_answer",
    "summarization",
}
FORBIDDEN_ROUTE_TERMS = {
    "laguna",
    "nemotron",
    "hy3",
    "minimax",
    "kilo",
    "openrouter",
    "provider",
}


def _corpus() -> dict:
    path = Path(__file__).resolve().parent / "fixtures" / "padiem_tier_benchmark_v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_tier_benchmark_v1_is_synthetic_provider_neutral_and_complete():
    corpus = _corpus()

    assert corpus["version"] == "padiem-tier-benchmark-v1"
    assert corpus["language"] == "ko-KR"
    assert corpus["data_policy"] == "synthetic_non_sensitive_only"
    assert corpus["provider_calls_authorized"] is False

    cases = corpus["cases"]
    assert len(cases) == 6
    assert {case["category"] for case in cases} == REQUIRED_CATEGORIES
    assert len({case["id"] for case in cases}) == len(cases)

    for case in cases:
        assert case["id"].startswith("KR-")
        assert isinstance(case["prompt"], str) and case["prompt"].strip()
        assert isinstance(case["rubric"], list) and case["rubric"]
        joined = (case["prompt"] + " " + " ".join(case["rubric"])).lower()
        assert not any(term in joined for term in FORBIDDEN_ROUTE_TERMS)


def test_reasoning_case_has_one_unique_solution():
    corpus = _corpus()
    case = next(item for item in corpus["cases"] if item["id"] == "KR-REASON-001")

    assert case["expected_answer"] == "B"

    # Statements in the fixture are:
    # 1) A에는 없다, 2) B에는 없다, 3) A에 있다.
    true_counts = {
        "A": sum((False, True, True)),
        "B": sum((True, False, False)),
        "C": sum((True, True, False)),
    }
    solutions = [box for box, count in true_counts.items() if count == 1]

    assert true_counts == {"A": 2, "B": 1, "C": 2}
    assert solutions == [case["expected_answer"]]


def test_tier_benchmark_v1_has_no_network_or_live_user_dependency():
    corpus = _corpus()
    joined = json.dumps(corpus, ensure_ascii=False).lower()

    for forbidden in (
        "http://",
        "https://",
        "api_key",
        "authorization",
        "실제 사용자",
        "주민등록번호",
        "전화번호",
        "이메일 주소",
    ):
        assert forbidden not in joined
