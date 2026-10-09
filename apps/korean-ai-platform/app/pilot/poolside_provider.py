"""Poolside Provider onboarding for Business 14.

This module uses the existing generic platform-owned Provider plane. It adds
only non-secret Poolside metadata and the exact Laguna S 2.1 model entry.
No Provider call is made during registration.

Poolside is intentionally registered as an explicit-only model for the initial
rollout: it is addressable by exact model ID but is not inserted into the
legacy OpenRouter summary/auto-routing list. That keeps B14's historical
OpenRouter catalog contract intact while preventing Poolside from being chosen
by ``b14/auto`` before the owner explicitly approves that behavior.
"""

from __future__ import annotations

from app.pilot.catalog import (
    CATALOG_BY_ID,
    CatalogModel,
    ensure_free_tag_requires_known_zero_price,
)
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

POOLSIDE_PROVIDER_ID = "poolside"
POOLSIDE_MODEL_ID = "poolside/laguna-s-2.1"
POOLSIDE_UPSTREAM_MODEL = "poolside/laguna-s-2.1"
POOLSIDE_BASE_ORIGIN = "https://inference.poolside.ai/v1"
POOLSIDE_CREDENTIAL_BINDING = "PADIEM_POOLSIDE_API_KEY"


def register_poolside_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
