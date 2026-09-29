"""Space Bunny vision source readiness using the B66 fixture corpus (#3209).

Source-only regression: the existing synthetic/non-sensitive B66 PNG fixtures
must pass through the existing bounded B14 image contract unchanged. No new
fixture is created and no live model call is made.

Covers §20 fixture reuse (f02/f11/f13) and §14 payload preservation at the
Core normalizer boundary for the canonical Space Bunny route.
"""

from __future__ import annotations

import base64
from pathlib import Path

from padiem_ai_core.b14_multimodal import B14MultimodalChatRequest
from padiem_ai_core.model_primary import (
    VISION_FALLBACK_DECISION,
    VISION_PRIMARY_MODEL_ID,
    VISION_PRIMARY_UPSTREAM_MODEL,
)

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "b66_e2e_corpus"

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


def test_vision_primary_is_space_bunny_alpha() -> None:
    assert VISION_PRIMARY_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert VISION_PRIMARY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"
    assert VISION_FALLBACK_DECISION == "UNDECIDED"


def test_b66_corpus_fixtures_pass_the_existing_image_contract() -> None:
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
            model=VISION_PRIMARY_MODEL_ID,
        )
        payload = request.to_payload()
        assert payload["model"] == VISION_PRIMARY_MODEL_ID
        content = payload["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "합계 금액을 읽어줘"}
        assert content[1]["image_url"]["url"] == url
        # The normalizer validates magic bytes: a PNG fixture must survive.
        assert raw.startswith(b"\x89PNG\r\n\x1a\n")
