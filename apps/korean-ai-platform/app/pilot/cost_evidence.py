"""Bounded cost-evidence semantics for Business 14 routing metadata.

This module deliberately separates a configured catalog price snapshot from
upstream-reported usage and measured monetary cost.  It performs no billing
mutation and does not choose a Provider/model route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class CostEvidenceError(ValueError):
    pass


class CostEvidenceStatus(str, Enum):
    CONFIGURED = "configured"
    UNKNOWN = "unknown"


def _validate_optional_rate(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CostEvidenceError(f"{name} must be a non-negative finite number or None")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise CostEvidenceError(f"{name} must be a non-negative finite number or None")
    return normalized


@dataclass(frozen=True, slots=True)
class ConfiguredCostEvidence:
    """Configured per-1M token price evidence from a catalog snapshot.

    A combined ranking rate exists only when *both* input and output rates are
    known.  Partial/absent pricing therefore remains UNKNOWN rather than being
    coerced to zero/free.
    """

    input_price_usd_per_1m: float | None
    output_price_usd_per_1m: float | None
    snapshot_state: str = "configured_snapshot"
    currency: str = "usd"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "input_price_usd_per_1m",
            _validate_optional_rate("input_price_usd_per_1m", self.input_price_usd_per_1m),
        )
        object.__setattr__(
            self,
            "output_price_usd_per_1m",
            _validate_optional_rate("output_price_usd_per_1m", self.output_price_usd_per_1m),
        )
        if self.currency != "usd":
            raise CostEvidenceError("configured catalog cost evidence currently requires usd")
        if not isinstance(self.snapshot_state, str) or not self.snapshot_state.strip():
            raise CostEvidenceError("snapshot_state must be a non-empty string")

    @property
    def status(self) -> CostEvidenceStatus:
        return (
            CostEvidenceStatus.CONFIGURED
            if self.input_price_usd_per_1m is not None
            and self.output_price_usd_per_1m is not None
            else CostEvidenceStatus.UNKNOWN
        )

    @property
    def is_known_zero(self) -> bool:
        return (
            self.status is CostEvidenceStatus.CONFIGURED
            and self.input_price_usd_per_1m == 0.0
            and self.output_price_usd_per_1m == 0.0
        )

    def combined_rate_usd_per_1m(self) -> float | None:
        """Return a configured ranking proxy, never a measured/invoiced cost."""
        if self.status is CostEvidenceStatus.UNKNOWN:
            return None
        assert self.input_price_usd_per_1m is not None
        assert self.output_price_usd_per_1m is not None
        return self.input_price_usd_per_1m + self.output_price_usd_per_1m

    def ranking_key(self) -> tuple[int, float]:
        """Known configured prices sort before unknown prices.

        The leading discriminator is what prevents UNKNOWN from becoming FREE:
        `(0, 0.0)` is explicit known-zero; `(1, 0.0)` is unknown.
        """
        combined = self.combined_rate_usd_per_1m()
        if combined is None:
            return (1, 0.0)
        return (0, combined)

    def to_public_dict(self) -> dict[str, str | float | None | bool]:
        return {
            "evidence_status": self.status.value,
            "input_price_usd_per_1m": self.input_price_usd_per_1m,
            "output_price_usd_per_1m": self.output_price_usd_per_1m,
            "combined_rate_usd_per_1m": self.combined_rate_usd_per_1m(),
            "known_zero_price": self.is_known_zero,
            "currency": self.currency,
            "snapshot_state": self.snapshot_state,
        }
