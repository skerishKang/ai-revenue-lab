"""Poolside Provider onboarding for Business 14.

This module uses the existing generic platform-owned Provider plane. It adds
only non-secret Poolside metadata for the owner-approved P5 LOW/MEDIUM models.
No Provider call is made during registration.

Both Poolside models are intentionally explicit-only: they are addressable by
exact model ID but are not inserted into the legacy OpenRouter summary/auto list.
B62 owns the LOW/MEDIUM product-profile choice and never delegates it to
``b14/auto``.
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
POOLSIDE_XS_MODEL_ID = "poolside/laguna-xs-2.1"
POOLSIDE_MODEL_ID = "poolside/laguna-s-2.1"  # compatibility name = MEDIUM
POOLSIDE_XS_UPSTREAM_MODEL = POOLSIDE_XS_MODEL_ID
POOLSIDE_UPSTREAM_MODEL = POOLSIDE_MODEL_ID
POOLSIDE_BASE_ORIGIN = "https://inference.poolside.ai/v1"
POOLSIDE_CREDENTIAL_BINDING = "POOLSIDE_API_KEY"


def _register_poolside_model(
    *,
    model_id: str,
    display_name: str,
    context_window: int,
    sort_order: int,
) -> None:
    if model_id in CATALOG_BY_ID:
        return
    model = CatalogModel(
        model_id=model_id,
        upstream_model=model_id,
        display_name=display_name,
        provider="Poolside",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=context_window,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding", "long_context"}),
        region="외부",
        sort_order=sort_order,
        credential_source="platform_secret",
        platform_provider_id=POOLSIDE_PROVIDER_ID,
        source="poolside_official_models_page",
        source_checked_at="2026-08-29",
        snapshot_state="configured_snapshot",
    )
    # Free endpoints are currently available, but P5 deliberately does not turn
    # a time-varying commercial condition into a permanent catalog ``free`` tag.
    ensure_free_tag_requires_known_zero_price(model)
    CATALOG_BY_ID[model.model_id] = model


def register_poolside_provider() -> None:
    """Idempotently register Poolside plus LOW XS and MEDIUM S 2.1."""
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

    _register_poolside_model(
        model_id=POOLSIDE_XS_MODEL_ID,
        display_name="Poolside: Laguna XS 2.1",
        context_window=256_000,
        sort_order=79,
    )
    _register_poolside_model(
        model_id=POOLSIDE_MODEL_ID,
        display_name="Poolside: Laguna S 2.1",
        context_window=1_000_000,
        sort_order=80,
    )


register_poolside_provider()
