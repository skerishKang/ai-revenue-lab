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
