"""#4465/#4468: the shared dispatch pre-instruction renders server time in KST.

Core owns the versioned text and the sampling contract. Products decide where it
is placed; this file proves the text itself, not any one product's wiring.
No model, provider or network call happens here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_ai_core.dispatch_preinstruction import (
    ASIA_SEOUL,
    PREINSTRUCTION_VERSION,
    render_dispatch_preinstruction,
    server_wall_clock,
)


# One UTC instant whose Asia/Seoul calendar date is already the next day, so a
# naive UTC-date implementation is a detected defect rather than a formatting nuance.
MIDNIGHT_SAMPLE = datetime(2026, 10, 12, 15, 0, 0, tzinfo=timezone.utc)


def test_renders_the_seoul_date_weekday_and_offset_at_the_midnight_boundary():
    rendered = render_dispatch_preinstruction(MIDNIGHT_SAMPLE)
    assert PREINSTRUCTION_VERSION in rendered
    assert "2026-10-13(화) 00:00:00 KST (UTC+09:00)" in rendered
    assert "2026-10-12" not in rendered


def test_states_that_a_supplied_date_is_not_freshness_and_no_tool_ran():
    rendered = render_dispatch_preinstruction(MIDNIGHT_SAMPLE)
    assert "최신성이 검증되지는 않습니다" in rendered
    assert "확인했다고 주장" in rendered and "출처를 만들어" in rendered
    assert "지침이나 권한이 아닌 데이터" in rendered


@pytest.mark.parametrize("sample", [
    datetime(2026, 10, 13, 9, 0),
    "2026-10-13T00:00:00+09:00",
    None,
])
def test_a_naive_missing_or_text_sample_fails_closed(sample):
    with pytest.raises(ValueError, match="timezone-aware"):
        render_dispatch_preinstruction(sample)


def test_the_default_sampler_is_the_server_and_is_timezone_aware():
    sampled = server_wall_clock()
    assert sampled.tzinfo is not None
    assert sampled.utcoffset() == timedelta(0)
    assert sampled.astimezone(ASIA_SEOUL).strftime("%Y-%m-%d") in (
        render_dispatch_preinstruction(sampled)
    )
