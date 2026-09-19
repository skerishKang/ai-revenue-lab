"""Atria Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

ATRIA_PROVIDER_ID = "atria"
ATRIA_BASE_ORIGIN = "https://api.atria-asi.ai/v1"
ATRIA_ALLOWED_HOST = "api.atria-asi.ai"
ATRIA_CREDENTIAL_BINDING = "PADIEM_ATRIA_API_KEY"
ATRIA_MODEL_ID = "atria/Atria-Dawn-Preview"
ATRIA_UPSTREAM_MODEL = "Atria-Dawn-Preview"
ATRIA_SOURCE_CHECKED_AT = "2026-09-18"


def register_atria_provider() -> None:
    """Register Atria and its exact manual-pin model route idempotently."""

    if get_platform_provider(ATRIA_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=ATRIA_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=ATRIA_CREDENTIAL_BINDING,
                base_origin=ATRIA_BASE_ORIGIN,
                allowed_hosts=(ATRIA_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if ATRIA_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=ATRIA_MODEL_ID,
        upstream_model=ATRIA_UPSTREAM_MODEL,
        display_name="Atria: Dawn Preview",
        provider="Atria",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=92,
        credential_source="platform_secret",
        platform_provider_id=ATRIA_PROVIDER_ID,
        source="atria_official_origin_and_model",
        source_checked_at=ATRIA_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )
    CATALOG_BY_ID[model.model_id] = model


register_atria_provider()
