"""Model-independent vision payload readiness while primary selection is HOLD (#3568).

The synthetic/non-sensitive B66 PNG fixture corpus still proves the bounded
Core image payload contract. No executable provider/model route is implied by
this test; a local synthetic model identifier is used only to exercise the
normalizer.
"""

from __future__ import annotations

import base64
from pathlib import Path

from padiem_ai_core.b14_multimodal import B14MultimodalChatRequest
from padiem_ai_core.model_primary import (
    VISION_FALLBACK_DECISION,
    VISION_PRIMARY_DECISION,
    VISION_PRIMARY_MODEL_ID,
    VISION_PRIMARY_UPSTREAM_MODEL,
)

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "b66_e2e_corpus"
MODEL_UNDER_TEST = "test/vision-contract-only"

REUSED_FIXTURES = (
    "f02-scanned-quotation.png",
    "f11-simple-logo.png",
    "f13-degraded-scan.png",
)


def _data_url_for(fixture_name: str) -> tuple[str, bytes]:
    path = CORPUS_DIR / fixture_name
    assert path.is_file(), f"B66 fixture missing: {fixture_name}"
    raw = path.read_bytes()
    assert raw, f"B66 fixture is empty: {fixture_name}"
    assert len(raw) <= 4 * 1024 * 1024, f"B66 fixture exceeds 4 MiB: {fixture_name}"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{encoded}", raw


def test_vision_primary_is_pending_successor_selection() -> None:
    assert VISION_PRIMARY_DECISION == "PENDING_SUCCESSOR_SELECTION"
    assert VISION_PRIMARY_MODEL_ID is None
    assert VISION_PRIMARY_UPSTREAM_MODEL is None
    assert VISION_FALLBACK_DECISION == "UNDECIDED"


def test_b66_corpus_fixtures_pass_the_model_independent_image_contract() -> None:
    for fixture_name in REUSED_FIXTURES:
        url, raw = _data_url_for(fixture_name)
        request = B14MultimodalChatRequest(
            messages=(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "합계 금액을 읽어줘"},
                        {"type": "image_url", "image_url": {"url": url}},
                    ],
                },
            ),
            model=MODEL_UNDER_TEST,
        )
        payload = request.to_payload()
        assert payload["model"] == MODEL_UNDER_TEST
        content = payload["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "합계 금액을 읽어줘"}
        assert content[1]["image_url"]["url"] == url
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
