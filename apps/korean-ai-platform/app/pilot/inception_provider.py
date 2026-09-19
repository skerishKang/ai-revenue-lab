"""Inception Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

INCEPTION_PROVIDER_ID = "inception"
INCEPTION_BASE_ORIGIN = "https://api.inceptionlabs.ai/v1"
INCEPTION_ALLOWED_HOST = "api.inceptionlabs.ai"
INCEPTION_CREDENTIAL_BINDING = "PADIEM_INCEPTION_MERCURY_API_KEY"
INCEPTION_MODEL_ID = "inception/mercury-2.5"
INCEPTION_UPSTREAM_MODEL = "mercury-2.5"
INCEPTION_SOURCE_CHECKED_AT = "2026-09-18"


def register_inception_provider() -> None:
    """Register Inception and its exact manual-pin model route idempotently."""

    if get_platform_provider(INCEPTION_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=INCEPTION_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=INCEPTION_CREDENTIAL_BINDING,
                base_origin=INCEPTION_BASE_ORIGIN,
                allowed_hosts=(INCEPTION_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if INCEPTION_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=INCEPTION_MODEL_ID,
        upstream_model=INCEPTION_UPSTREAM_MODEL,
        display_name="Inception: Mercury 2.5",
        provider="Inception",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=91,
        credential_source="platform_secret",
        platform_provider_id=INCEPTION_PROVIDER_ID,
        source="inception_official_origin_and_model",
        source_checked_at=INCEPTION_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )
    CATALOG_BY_ID[model.model_id] = model


register_inception_provider()
