from __future__ import annotations

import math

import pytest

from app.pilot.cost_evidence import (
    ConfiguredCostEvidence,
    CostEvidenceError,
    CostEvidenceStatus,
)


def test_known_zero_price_is_explicit_free_evidence_not_unknown() -> None:
    evidence = ConfiguredCostEvidence(0.0, 0.0)

    assert evidence.status is CostEvidenceStatus.CONFIGURED
    assert evidence.is_known_zero is True
    assert evidence.combined_rate_usd_per_1m() == 0.0
    assert evidence.ranking_key() == (0, 0.0)


def test_unknown_or_partial_price_remains_unknown_and_sorts_after_known() -> None:
    known_zero = ConfiguredCostEvidence(0.0, 0.0)
    known_paid = ConfiguredCostEvidence(0.30, 2.50)
    partial = ConfiguredCostEvidence(0.30, None)
    unknown = ConfiguredCostEvidence(None, None)

    assert partial.status is CostEvidenceStatus.UNKNOWN
    assert partial.combined_rate_usd_per_1m() is None
    assert unknown.status is CostEvidenceStatus.UNKNOWN
    assert unknown.is_known_zero is False

    ordered = sorted(
        [unknown, known_paid, partial, known_zero],
        key=ConfiguredCostEvidence.ranking_key,
    )
    assert ordered[0] is known_zero
    assert ordered[1] is known_paid
    assert set(ordered[2:]) == {partial, unknown}


def test_combined_configured_rate_is_a_snapshot_ranking_proxy() -> None:
    evidence = ConfiguredCostEvidence(0.30, 2.50)

    assert evidence.combined_rate_usd_per_1m() == pytest.approx(2.80)
    assert evidence.to_public_dict() == {
        "evidence_status": "configured",
        "input_price_usd_per_1m": 0.30,
        "output_price_usd_per_1m": 2.50,
        "combined_rate_usd_per_1m": pytest.approx(2.80),
        "known_zero_price": False,
        "currency": "usd",
        "snapshot_state": "configured_snapshot",
    }


def test_invalid_configured_rates_fail_closed() -> None:
    for value in (-0.01, math.inf, -math.inf, math.nan, True, "0.1"):
        with pytest.raises(CostEvidenceError):
            ConfiguredCostEvidence(value, 0.0)  # type: ignore[arg-type]

    with pytest.raises(CostEvidenceError):
        ConfiguredCostEvidence(0.0, 0.0, currency="krw")


def test_public_shape_does_not_claim_measured_or_upstream_cost() -> None:
    public = ConfiguredCostEvidence(None, None).to_public_dict()
    serialized = repr(public).lower()

    assert public["evidence_status"] == "unknown"
    assert public["combined_rate_usd_per_1m"] is None
    assert "measured" not in serialized
    assert "upstream_reported" not in serialized
    assert "invoice" not in serialized
