from datetime import datetime, timezone
import pytest
from app.pilot.routing_evidence import (
    AvailabilityEvidence,
    AvailabilityEvidenceSource,
    AvailabilityState,
    ConfiguredLatencyClass,
    LatencyEvidence,
    LatencyEvidenceSource,
    RoutingEvidenceError,
)
from _registry_values import model_ids

#: Two identities the effective registry installs, so the route under test is a
#: deployed route rather than a value written in this suite (#7241 3a).
_INSTALLED_IDS = sorted(model_ids())
ROUTE_ID = _INSTALLED_IDS[0]
OTHER_ROUTE_ID = _INSTALLED_IDS[1]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
def test_unknown_availability_cannot_claim_available() -> None:
    with pytest.raises(RoutingEvidenceError):
        AvailabilityEvidence(
            route_id=ROUTE_ID,
            state=AvailabilityState.AVAILABLE,
            source=AvailabilityEvidenceSource.UNKNOWN,
        )
def test_known_availability_requires_timestamp() -> None:
    with pytest.raises(RoutingEvidenceError):
        AvailabilityEvidence(
            route_id=ROUTE_ID,
            state=AvailabilityState.AVAILABLE,
            source=AvailabilityEvidenceSource.MEASURED,
        )
def test_measured_availability_accepts_aware_timestamp() -> None:
    evidence = AvailabilityEvidence(
        route_id=ROUTE_ID,
        state=AvailabilityState.AVAILABLE,
        source=AvailabilityEvidenceSource.MEASURED,
        observed_at=NOW,
    )
    assert evidence.state is AvailabilityState.AVAILABLE
def test_configured_latency_class_is_not_measured_latency() -> None:
    evidence = LatencyEvidence(
        route_id=OTHER_ROUTE_ID,
        source=LatencyEvidenceSource.CONFIGURED_CLASS,
        configured_class=ConfiguredLatencyClass.FAST,
    )
    assert evidence.measured_ms is None
    assert evidence.observed_at is None
def test_configured_latency_rejects_measured_fields() -> None:
    with pytest.raises(RoutingEvidenceError):
        LatencyEvidence(
            route_id=OTHER_ROUTE_ID,
            source=LatencyEvidenceSource.CONFIGURED_CLASS,
            configured_class=ConfiguredLatencyClass.FAST,
            measured_ms=500,
        )
def test_measured_latency_requires_timestamp_and_valid_value() -> None:
    with pytest.raises(RoutingEvidenceError):
        LatencyEvidence(
            route_id=OTHER_ROUTE_ID,
            source=LatencyEvidenceSource.MEASURED,
            measured_ms=500,
        )
    with pytest.raises(RoutingEvidenceError):
        LatencyEvidence(
            route_id=OTHER_ROUTE_ID,
            source=LatencyEvidenceSource.MEASURED,
            measured_ms=float("nan"),
            observed_at=NOW,
        )
def test_measured_latency_is_distinct_from_configured_class() -> None:
    evidence = LatencyEvidence(
        route_id=OTHER_ROUTE_ID,
        source=LatencyEvidenceSource.MEASURED,
        measured_ms=487.5,
        observed_at=NOW,
    )
    assert evidence.measured_ms == 487.5
    assert evidence.configured_class is None
def test_naive_timestamps_fail_closed() -> None:
    with pytest.raises(RoutingEvidenceError):
        AvailabilityEvidence(
            route_id="route-a",
            state=AvailabilityState.DEGRADED,
            source=AvailabilityEvidenceSource.UPSTREAM_REPORTED,
            observed_at=datetime(2026, 8, 30, 12, 0),
        )
