"""Read-only exact-serving-model evidence for the canonical B14 registry (#3977).

Do not infer model variants, serving-specific output caps, hidden sampling
defaults, or API support from an unrelated manufacturer's model card.
The official-source annotations below are strictly guarded by the serving
provider, exact upstream model code, and first-party Google API origin.
No credentials, network access, routing, or model calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model_registry_file import read_registry
from .model_native_parameters import _SUPPORTED

EvidenceStatus = Literal["DOCUMENTED", "UNKNOWN"]
_GOOGLE_API_ORIGIN = "https://generativelanguage.googleapis.com/v1beta/openai"

# Exact model ID -> (official model documentation URL, manufacturer max output).
# Source: Google AI for Developers, rechecked 2026-10-10.
# The two Gemini cards explicitly specify 65,536 output tokens; this is the
# ORIGINAL model-card limit, never the tested serving API or request cap.
# Google documents both Gemma 4 model IDs on its official hosted-Gemma guide,
# but does not state serving max output there; therefore those values stay None.
_GOOGLE_FIRST_PARTY_SOURCES: dict[str, tuple[str, int | None]] = {
    "google/gemini-3.1-flash-lite": (
        "https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite",
        65536,
    ),
    "google/gemini-3.5-flash-lite": (
        "https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite",
        65536,
    ),
    "google/gemma-4-26b-a4b-it": (
        "https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api",
        None,
    ),
    "google/gemma-4-31b-it": (
        "https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api",
        None,
    ),
}


@dataclass(frozen=True)
class GoogleAIStudioFreeTierSnapshot:
    """Owner-reported observed Google API quota; NOT a model capability.

    This is not a live balance, automatic limiter, or permanent guarantee.
    """
    rpm: int
    input_tpm: int
    rpd: int
    observed_on: str = "2026-10-09"
    source: str = "owner_reported_google_ai_studio_rate_limit"
    scope: str = "per_model_per_project"


# User's verified 2026-10-09 Google AI Studio Free-tier dashboard snapshot.
# Exact project/model limit, not official permanent manufacturer capacity.
# Recheck dashboard https://aistudio.google.com/rate-limit and official
# rate-limit rules https://ai.google.dev/gemini-api/docs/rate-limits .
# Never use these numbers to clamp max_tokens, automatically change models,
# or classify rate-limited 429 as model-quality failure.
_GOOGLE_FREE_TIER_OBSERVED: dict[str, tuple[int, int, int]] = {
    "google/gemini-3.1-flash-lite": (15, 250000, 500),
    "google/gemini-3.5-flash-lite": (15, 250000, 500),
    "google/gemma-4-26b-a4b-it": (30, 16000, 14400),
    "google/gemma-4-31b-it": (30, 16000, 14400),
}


@dataclass(frozen=True)
class ServingModelEvidence:
    model_id: str
    serving_provider_id: str
    upstream_model: str
    serving_origin: str
    registry_source: str
    registry_checked_at: str
    manufacturer: str | None = None
    variant_kind: str | None = None
    official_source_url: str | None = None
    google_ai_studio_free_tier_observed: GoogleAIStudioFreeTierSnapshot | None = None
    manufacturer_model_max_output: int | None = None
    serving_model_max_output: int | None = None
    native_override_fields: tuple[str, ...] = ()
    native_override_status: EvidenceStatus = "UNKNOWN"

    @property
    def provenance_status(self) -> EvidenceStatus:
        return (
            "DOCUMENTED"
            if self.manufacturer and self.variant_kind and self.official_source_url
            else "UNKNOWN"
        )

    @property
    def manufacturer_output_limit_status(self) -> EvidenceStatus:
        return "DOCUMENTED" if self.manufacturer_model_max_output is not None else "UNKNOWN"

    @property
    def output_limit_status(self) -> EvidenceStatus:
        # Full output-budget authority requires independently evidenced model
        # AND serving caps. Never elevate a manufacturer card to a live limit.
        return (
            "DOCUMENTED"
            if self.manufacturer_model_max_output is not None
            and self.serving_model_max_output is not None
            else "UNKNOWN"
        )


def _official_google_fact(
    model_id: str, provider_id: str, upstream_model: str, origin: str
) -> tuple[str | None, str | None, str | None, int | None]:
    """Only first-party Google official exact codes may carry these facts."""
    if (
        provider_id != "google"
        or origin.rstrip("/") != _GOOGLE_API_ORIGIN
        or model_id != "google/" + upstream_model
    ):
        return None, None, None, None
    official = _GOOGLE_FIRST_PARTY_SOURCES.get(model_id)
    if official is None:
        return None, None, None, None
    source_url, manufacturer_max_output = official
    # This variant label proves only the official serving model code, NOT the
    # absence of finetuning or differences in third-party serving behavior.
    return "Google", "official_first_party_api_code", source_url, manufacturer_max_output


def registered_serving_evidence() -> tuple[ServingModelEvidence, ...]:
    """Report strictly source-backed model/provider identities and official facts.

    Exact native allow-lists are existing code authority, not vendor defaults.
    Unknown vendor options, model variants and serving caps remain UNKNOWN.
    """
    registry = read_registry()
    providers = registry["providers"]
    result: list[ServingModelEvidence] = []
    for model in registry["models"]:
        model_id = model["id"]
        provider_id = model["provider_id"]
        upstream = model["upstream_model"]
        if not model_id.startswith(provider_id + "/"):
            raise ValueError("B14 exact model/provider tuple mismatch")
        origin = providers[provider_id]["base_origin"]
        manufacturer, variant, source_url, maker_output = _official_google_fact(
            model_id, provider_id, upstream, origin
        )
        observed_limits = _GOOGLE_FREE_TIER_OBSERVED.get(model_id) if source_url else None
        quota_snapshot = (
            GoogleAIStudioFreeTierSnapshot(*observed_limits)
            if observed_limits is not None else None
        )
        native = _SUPPORTED.get(model_id)
        result.append(ServingModelEvidence(
            model_id=model_id,
            serving_provider_id=provider_id,
            upstream_model=upstream,
            serving_origin=origin,
            registry_source=model["source"],
            registry_checked_at=model["source_checked_at"],
            manufacturer=manufacturer,
            variant_kind=variant,
            official_source_url=source_url,
            google_ai_studio_free_tier_observed=quota_snapshot,
            manufacturer_model_max_output=maker_output,
            # Serving API max output and explicit per-request budgets are
            # separate from official manufacturer/model-card max output.
            serving_model_max_output=None,
            native_override_fields=tuple(sorted(native)) if native else (),
            native_override_status="DOCUMENTED" if native is not None else "UNKNOWN",
        ))
    unknown_ids = set(_SUPPORTED) - {item.model_id for item in result}
    if unknown_ids:
        raise ValueError("native override profile refers to an unregistered B14 exact model")
    return tuple(result)
