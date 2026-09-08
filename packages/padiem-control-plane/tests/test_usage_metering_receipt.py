"""Tests for the promoted CP usage-metering receipt contract (#1556).

Behavioural cases are ported from the reviewed B54-side suite
(``apps/korean-ai-code-agent/tests/test_cloud_usage_metering.py``) with the
binding semantics kept exact. Pure offline validation; network-free.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.usage_metering_receipt import (
    ESTIMATED_PROVIDER_COST_SUPPORTED,
    REAL_BILLING_API_CONFIGURED,
    USAGE_RECEIPT_CREDIT_DEBIT_AUTHORITY,
    USAGE_RECEIPT_PRICING_AUTHORITY,
    CloudM1UsageReceipt,
    TrustedResourceUsageObservation,
    build_usage_receipt,
)

NOW = datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)
PLAN_ID = "plan_1"
RUN_ID = "run_1"
WORKSPACE_ID = "ws_1"
PLAN_FINGERPRINT = "c" * 64


def observation(**changes) -> TrustedResourceUsageObservation:
    values = dict(
        observation_id="usage_obs_1",
        plan_id=PLAN_ID,
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        plan_fingerprint=PLAN_FINGERPRINT,
        wall_time_ms=120000,
        cpu_time_ms=45000,
        peak_memory_mib=512,
        disk_read_bytes=1000,
        disk_write_bytes=2000,
        network_egress_bytes=0,
        observed_at=NOW,
        authority_ref="trusted:sandbox-meter",
        evidence_ref="evidence:usage-1",
    )
    values.update(changes)
    return TrustedResourceUsageObservation(**values)


def plan_refs(**changes):
    values = dict(
        plan_id=PLAN_ID,
        run_id=RUN_ID,
        workspace_id=WORKSPACE_ID,
        plan_fingerprint=PLAN_FINGERPRINT,
    )
    values.update(changes)
    return values


def test_exact_plan_bound_observation_builds_measured_receipt() -> None:
    receipt = build_usage_receipt(observation=observation(), **plan_refs())
    safe = receipt.safe_dict()
    assert safe["wall_time_ms"] == 120000
    assert safe["network_egress_bytes"] == 0
    assert safe["measured"] is True
    assert safe["control_plane_handoff_only"] is True
    assert len(safe["receipt_fingerprint"]) == 64
    assert safe["receipt_fingerprint"] == receipt.fingerprint


def test_receipt_fingerprint_is_deterministic_canonical_sha256() -> None:
    receipt = build_usage_receipt(observation=observation(), **plan_refs())
    payload = {
        "plan_id": PLAN_ID,
        "run_id": RUN_ID,
        "workspace_id": WORKSPACE_ID,
        "plan_fingerprint": PLAN_FINGERPRINT,
        "wall_time_ms": 120000,
        "cpu_time_ms": 45000,
        "peak_memory_mib": 512,
        "disk_read_bytes": 1000,
        "disk_write_bytes": 2000,
        "network_egress_bytes": 0,
        "observed_at": NOW.isoformat(),
        "evidence_ref": "evidence:usage-1",
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert receipt.fingerprint == expected


def test_receipt_id_binds_observation_and_plan_fingerprint() -> None:
    receipt = build_usage_receipt(observation=observation(), **plan_refs())
    digest = hashlib.sha256(f"usage_obs_1:{PLAN_FINGERPRINT}".encode("utf-8")).hexdigest()[:24]
    assert receipt.receipt_id == f"usage:{digest}"


def test_negative_bool_and_network_egress_metrics_fail_closed() -> None:
    with pytest.raises(ControlPlaneContractError, match="non-negative"):
        observation(wall_time_ms=-1)
    with pytest.raises(ControlPlaneContractError, match="non-negative"):
        observation(cpu_time_ms=True)
    with pytest.raises(ControlPlaneContractError, match="zero network egress"):
        observation(network_egress_bytes=1)


def test_plan_run_workspace_and_fingerprint_mismatch_fail_closed() -> None:
    for changes in (
        {"plan_id": "plan_other"},
        {"run_id": "run_other"},
        {"workspace_id": "ws_other"},
        {"plan_fingerprint": "b" * 64},
    ):
        with pytest.raises(ControlPlaneContractError, match="does not bind exact"):
            build_usage_receipt(observation=observation(), **plan_refs(**changes))


def test_builder_rejects_non_observation_and_unbounded_refs() -> None:
    with pytest.raises(ControlPlaneContractError, match="TrustedResourceUsageObservation"):
        build_usage_receipt(observation="not-an-observation", **plan_refs())  # type: ignore[arg-type]
    with pytest.raises(ControlPlaneContractError, match="plan_fingerprint"):
        build_usage_receipt(observation=observation(), **plan_refs(plan_fingerprint="short"))
    with pytest.raises(ControlPlaneContractError, match="bounded safe reference"):
        build_usage_receipt(observation=observation(), **plan_refs(run_id=""))


def test_naive_observation_timestamp_is_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="timezone-aware"):
        observation(observed_at=datetime(2026, 9, 3, 10, 0))


def test_invalid_fingerprint_digest_is_rejected() -> None:
    with pytest.raises(ControlPlaneContractError, match="SHA-256"):
        observation(plan_fingerprint="z" * 64)


def test_measurement_carries_no_pricing_credit_or_provider_cost_authority() -> None:
    assert USAGE_RECEIPT_PRICING_AUTHORITY is False
    assert USAGE_RECEIPT_CREDIT_DEBIT_AUTHORITY is False
    assert ESTIMATED_PROVIDER_COST_SUPPORTED is False
    assert REAL_BILLING_API_CONFIGURED is False
    safe = build_usage_receipt(observation=observation(), **plan_refs()).safe_dict()
    assert safe["estimated_provider_cost"] is False
    assert safe["pricing_authority"] is False
    assert safe["credit_debit_authority"] is False


def test_receipt_direct_construction_enforces_zero_egress_and_bounded_fields() -> None:
    with pytest.raises(ControlPlaneContractError, match="network egress must be zero"):
        CloudM1UsageReceipt(
            receipt_id="usage:x",
            plan_id=PLAN_ID,
            run_id=RUN_ID,
            workspace_id=WORKSPACE_ID,
            plan_fingerprint=PLAN_FINGERPRINT,
            wall_time_ms=1,
            cpu_time_ms=1,
            peak_memory_mib=1,
            disk_read_bytes=1,
            disk_write_bytes=1,
            network_egress_bytes=5,
            observed_at=NOW,
            evidence_ref="evidence:usage-1",
        )


def test_safe_projections_carry_no_raw_payload_or_credential() -> None:
    obs_safe = observation().safe_dict()
    assert obs_safe["raw_provider_payload"] is False
    assert obs_safe["provider_credential"] is False
    assert obs_safe["estimated_provider_cost"] is False
    assert obs_safe["observed_at"].endswith("Z")
    receipt_safe = build_usage_receipt(observation=observation(), **plan_refs()).safe_dict()
    assert receipt_safe["contract_version"] == "claw-cloud-m1-usage-receipt.v1"
