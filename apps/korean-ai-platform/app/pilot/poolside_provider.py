"""Poolside Provider onboarding for Business 14.

This module uses the existing generic platform-owned Provider plane.  It adds
only non-secret Poolside metadata and the exact Laguna S 2.1 catalog entry.
No Provider call is made during registration.
"""

from __future__ import annotations

from app.pilot.catalog import (
    CATALOG_BY_ID,
    CATALOG_MODELS,
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
POOLSIDE_CREDENTIAL_BINDING = "POOLSIDE_API_KEY"


def register_poolside_provider() -> None:
    """Idempotently register Poolside and Laguna S 2.1.

    Pricing remains unknown in the durable catalog even though Poolside's
    official models page currently advertises limited-time free access.  This
    deliberately avoids turning a time-limited promotion into a permanent
    ``free`` capability claim.
    """

    if get_platform_provider(POOLSIDE_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=POOLSIDE_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=POOLSIDE_CREDENTIAL_BINDING,
                base_origin=POOLSIDE_BASE_ORIGIN,
                allowed_hosts=("inference.poolside.ai",),
                enabled=True,
            )
        )

    if POOLSIDE_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=POOLSIDE_MODEL_ID,
        upstream_model=POOLSIDE_UPSTREAM_MODEL,
        display_name="Poolside: Laguna S 2.1",
        provider="Poolside",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=1_000_000,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding", "long_context"}),
        region="외부",
        sort_order=80,
        credential_source="platform_secret",
        platform_provider_id=POOLSIDE_PROVIDER_ID,
        source="poolside_official_models_page",
        source_checked_at="2026-08-28",
        snapshot_state="configured_snapshot",
    )
    ensure_free_tag_requires_known_zero_price(model)
    CATALOG_MODELS.append(model)
    CATALOG_BY_ID[model.model_id] = model


register_poolside_provider()
