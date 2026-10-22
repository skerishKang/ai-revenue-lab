"""#5347 (owner decision 2026-10-23): one shared PADIEM identity policy.

The user-facing answer names the PADIEM product brand and the server-authorized
tier. The underlying model, provider, routing and fallback stay internal, even
when the user asks directly. No model, provider or network call happens here.
"""
from __future__ import annotations

import pytest

from padiem_ai_core.dispatch_preinstruction import (
    PREINSTRUCTION_VERSION,
    render_dispatch_preinstruction,
    render_product_identity_instruction,
)
from datetime import datetime, timezone

_HIDDEN_TERMS = (
    "muse",
    "minimax",
    "gemini",
    "kilo",
    "poolside",
    "laguna",
    "nvidia",
    "nemotron",
)


@pytest.mark.parametrize(
    ("product", "tier", "expected_identity"),
    [
        ("chat", "free", "PADIEM Chat의 PADIEM Free 모드"),
        ("chat", "plus", "PADIEM Chat의 PADIEM Plus 모드"),
        ("chat", "pro", "PADIEM Chat의 PADIEM Pro 모드"),
        ("chat", "max", "PADIEM Chat의 PADIEM Max 모드"),
        ("claw", "free", "PADIEM CLAW의 PADIEM Free 모드"),
        ("claw", "max", "PADIEM CLAW의 PADIEM Max 모드"),
        ("b66", "plus", "PADIEM B66의 PADIEM Plus 모드"),
    ],
)
def test_identity_names_the_product_brand_and_the_verified_tier(
    product: str, tier: str, expected_identity: str
):
    rendered = render_product_identity_instruction(product, tier)
    assert f"당신은 {expected_identity}입니다." in rendered
    lowered = rendered.lower()
    for hidden in _HIDDEN_TERMS:
        assert hidden not in lowered


@pytest.mark.parametrize("bad_tier", [None, "", "admin", "ENTERPRISE", "plus receipt"])
def test_missing_or_unverified_tier_answers_neutral_without_an_inferred_grade(bad_tier):
    rendered = render_product_identity_instruction("chat", bad_tier)
    assert "당신은 PADIEM Chat AI입니다." in rendered
    for grade in ("Free", "Plus", "Pro", "Max"):
        assert grade not in rendered


@pytest.mark.parametrize("bad_product", ["", "engine", None, 7])
def test_unknown_product_fails_closed(bad_product):
    with pytest.raises(ValueError, match="unknown PADIEM product identity"):
        render_product_identity_instruction(bad_product, "max")


def test_the_common_preinstruction_forbids_disclosing_the_underlying_model():
    rendered = render_dispatch_preinstruction(datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc))
    assert PREINSTRUCTION_VERSION in rendered
    assert "모델 이름·공급자·버전·아키텍처·라우팅·폴백 정보를 사용자에게 공개하지 마세요" in rendered
    assert "추측하지 말고" in rendered