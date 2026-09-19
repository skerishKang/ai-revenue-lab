"""Infron Provider onboarding for Business 14.

This is an explicit/manual-pin candidate only. Registration stores non-secret
metadata and performs no upstream or credential-value reads. The generic
platform adapter owns the fixed-origin, platform-secret, mock, and fail-closed
execution behavior.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

INFRON_PROVIDER_ID = "infron"
INFRON_BASE_ORIGIN = "https://llm.onerouter.pro/v1"
INFRON_ALLOWED_HOST = "llm.onerouter.pro"
INFRON_CREDENTIAL_BINDING = "PADIEM_INFRON_API_KEY"
INFRON_MODEL_ID = "infron/motif/motif-3"
INFRON_UPSTREAM_MODEL = "motif/motif-3"
INFRON_SOURCE_CHECKED_AT = "2026-09-18"


def register_infron_provider() -> None:
    """Register Infron and its exact manual-pin model route idempotently."""

    if get_platform_provider(INFRON_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=INFRON_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=INFRON_CREDENTIAL_BINDING,
                base_origin=INFRON_BASE_ORIGIN,
                allowed_hosts=(INFRON_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if INFRON_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=INFRON_MODEL_ID,
        upstream_model=INFRON_UPSTREAM_MODEL,
        display_name="Infron: Motif 3",
        provider="Infron",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=90,
        credential_source="platform_secret",
        platform_provider_id=INFRON_PROVIDER_ID,
        source="infron_official_origin_and_model",
        source_checked_at=INFRON_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )
    # Exact-ID lookup only; never add candidate routes to the public catalog or
    # b14/auto surface.
    CATALOG_BY_ID[model.model_id] = model


register_infron_provider()
