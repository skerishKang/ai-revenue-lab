"""Bounded availability and latency evidence contracts for Business 14.

The model/router catalog has both configured metadata and runtime observations.
These are deliberately different evidence classes: a configured latency class is
not a measured latency, and a configured enabled flag is not runtime
availability.  This module keeps those meanings structurally separate before
later routing integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import math


class RoutingEvidenceError(ValueError):
    """Raised when route evidence would overstate what is actually known."""


class AvailabilityState(str, Enum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AvailabilityEvidenceSource(str, Enum):
    UNKNOWN = "unknown"
    UPSTREAM_REPORTED = "upstream_reported"
    MEASURED = "measured"


class LatencyEvidenceSource(str, Enum):
    UNKNOWN = "unknown"
    CONFIGURED_CLASS = "configured_class"
    MEASURED = "measured"


class ConfiguredLatencyClass(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    SLOW = "slow"


def _require_aware_timestamp(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RoutingEvidenceError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class AvailabilityEvidence:
    """Timestamped runtime/upstream availability evidence for one route.

    `UNKNOWN` deliberately carries no observation timestamp.  A catalog
    `enabled=True` flag is not represented here because configuration is not
    runtime availability evidence.
    """

    route_id: str
    state: AvailabilityState
    source: AvailabilityEvidenceSource
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.route_id.strip():
            raise RoutingEvidenceError("route_id is required")

        if self.source is AvailabilityEvidenceSource.UNKNOWN:
            if self.state is not AvailabilityState.UNKNOWN or self.observed_at is not None:
                raise RoutingEvidenceError(
                    "unknown availability evidence cannot assert state or observation time"
                )
            return

        if self.state is AvailabilityState.UNKNOWN:
            raise RoutingEvidenceError("known availability source must assert a non-unknown state")
        if self.observed_at is None:
            raise RoutingEvidenceError("known availability evidence requires observed_at")
        _require_aware_timestamp(self.observed_at, "observed_at")


@dataclass(frozen=True)
class LatencyEvidence:
    """Either configured latency class or measured milliseconds, never both."""

    route_id: str
    source: LatencyEvidenceSource
    configured_class: ConfiguredLatencyClass | None = None
    measured_ms: float | None = None
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.route_id.strip():
            raise RoutingEvidenceError("route_id is required")

        if self.source is LatencyEvidenceSource.UNKNOWN:
            if (
                self.configured_class is not None
                or self.measured_ms is not None
                or self.observed_at is not None
            ):
                raise RoutingEvidenceError("unknown latency evidence cannot carry values")
            return

        if self.source is LatencyEvidenceSource.CONFIGURED_CLASS:
            if self.configured_class is None:
                raise RoutingEvidenceError("configured latency evidence requires configured_class")
            if self.measured_ms is not None or self.observed_at is not None:
                raise RoutingEvidenceError(
                    "configured latency class must not masquerade as measured telemetry"
                )
            return

        if self.source is LatencyEvidenceSource.MEASURED:
            if self.measured_ms is None:
                raise RoutingEvidenceError("measured latency evidence requires measured_ms")
            if not math.isfinite(self.measured_ms) or self.measured_ms < 0:
                raise RoutingEvidenceError("measured_ms must be finite and non-negative")
            if self.configured_class is not None:
                raise RoutingEvidenceError("measured latency must not carry configured_class")
            if self.observed_at is None:
                raise RoutingEvidenceError("measured latency evidence requires observed_at")
            _require_aware_timestamp(self.observed_at, "observed_at")
            return

        raise RoutingEvidenceError(f"unsupported latency evidence source: {self.source}")
