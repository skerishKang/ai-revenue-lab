"""Capability-aware eligibility over the Business 14 model catalog.

This module is intentionally a small routing adapter over the existing catalog
and canonical capability-evidence contract. It does not choose a model or
change ranking policy; it only answers whether a catalog entry is eligible for
an explicit capability requirement.

Rules:
- supported => eligible;
- unsupported => ineligible;
- unknown => ineligible (fail closed);
- no requirement => no capability filtering;
- legacy catalog tags are interpreted only through capability_evidence.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.pilot.capability_evidence import (
    CapabilityRequirementResult,
    ModelCapability,
    capability_profile_from_catalog_model,
    evaluate_capability_requirements,
)
from app.pilot.catalog import CatalogModel


@dataclass(frozen=True, slots=True)
class CapabilityRouteDecision:
    model_id: str
    eligible: bool
    requirements: CapabilityRequirementResult

    def to_public_dict(self) -> dict[str, object]:
        return {
            "model_id": self.model_id,
            "eligible": self.eligible,
            "requirements": self.requirements.to_public_dict(),
        }


def _normalize_requirements(
    required: Iterable[str | ModelCapability] | None,
) -> tuple[ModelCapability, ...]:
    if required is None:
        return ()
    normalized: list[ModelCapability] = []
    for value in required:
        if isinstance(value, ModelCapability):
            normalized.append(value)
            continue
        if not isinstance(value, str):
            raise ValueError("capability requirement must be a string or ModelCapability")
        try:
            normalized.append(ModelCapability(value))
        except ValueError as exc:
            raise ValueError("unsupported canonical capability requirement") from exc
    if len(set(normalized)) != len(normalized):
        raise ValueError("capability requirements must not contain duplicates")
    return tuple(normalized)


def evaluate_model_capabilities(
    model: CatalogModel,
    required: Iterable[str | ModelCapability] | None,
) -> CapabilityRouteDecision:
    """Evaluate one model against explicit capability requirements.

    An empty requirement set is a no-op and preserves existing route behavior.
    Any required capability whose state is unknown or unsupported makes the
    model ineligible. No score or fallback policy is changed here.
    """

    requirements = _normalize_requirements(required)
    profile = capability_profile_from_catalog_model(model)
    result = evaluate_capability_requirements(profile, requirements)
    return CapabilityRouteDecision(
        model_id=model.model_id,
        eligible=result.satisfied,
        requirements=result,
    )


def filter_capability_eligible_models(
    candidates: Iterable[CatalogModel],
    required: Iterable[str | ModelCapability] | None,
) -> list[CatalogModel]:
    """Return only models with fully satisfied canonical capabilities."""

    candidates = list(candidates)
    requirements = _normalize_requirements(required)
    if not requirements:
        return candidates
    eligible: list[CatalogModel] = []
    for model in candidates:
        decision = evaluate_model_capabilities(model, requirements)
        if decision.eligible:
            eligible.append(model)
    return eligible
