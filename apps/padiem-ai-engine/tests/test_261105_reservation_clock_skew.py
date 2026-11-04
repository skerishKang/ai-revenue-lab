"""261105: 승인 워커 시계가 1초 앞서도 예약을 미래로 읽지 않는다.

05:2x 실측: 승인 워커의 Date 헤더가 p01보다 약 1초 앞섰고,
`parse_usage_reservation`이 `reserved_at > now`를 오차 허용 없이 거절해
모든 파일 레인 턴이 503 → `entitlement_unavailable`로 끝났다. 워커 시각은
권위 시각이고 호스트 시각은 관측일 뿐이므로, 작은 앞섬은 받아들이고
분명한 미래 값은 그대로 거절한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution_admission import ExecutionAdmissionError
from app.tenant_auth import (
    RESERVATION_CLOCK_SKEW,
    UsageReservation,
    parse_usage_reservation,
)

NOW = datetime(2026, 11, 5, 5, 30, tzinfo=timezone.utc)


def _reservation() -> UsageReservation:
    return UsageReservation(
        idempotency_key="res-1",
        billing_semantic_id="orchestration.run",
        product_id="b62",
        subject={"subject_type": "user", "subject_id": "sub_" + "a" * 32},
        request_fingerprint="f" * 64,
        trace_id="tr_abc",
        estimated_units=1,
        occurred_at=NOW,
    )


def _decision(reserved_at: datetime) -> dict:
    return {
        "reservation_ref": "res_" + "b" * 32,
        "admitted": True,
        "expires_at": (reserved_at + timedelta(minutes=5)).isoformat(),
        "reserved_at": reserved_at.isoformat(),
    }


def test_a_worker_clock_ahead_by_one_second_is_tolerated():
    decision = parse_usage_reservation(
        _decision(NOW + timedelta(seconds=1)), reservation=_reservation(), now=NOW)
    assert decision["admitted"] is True


def test_a_skew_beyond_the_tolerance_is_still_refused():
    with pytest.raises(ExecutionAdmissionError) as raised:
        parse_usage_reservation(
            _decision(NOW + RESERVATION_CLOCK_SKEW + timedelta(seconds=5)),
            reservation=_reservation(), now=NOW)
    assert raised.value.code == "entitlement_unavailable"


def test_an_expiry_before_its_reservation_is_still_refused():
    decision = _decision(NOW)
    decision["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    with pytest.raises(ExecutionAdmissionError):
        parse_usage_reservation(decision, reservation=_reservation(), now=NOW)
