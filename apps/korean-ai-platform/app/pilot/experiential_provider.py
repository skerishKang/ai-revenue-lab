"""Experiential Labs Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

EXPERIENTIAL_PROVIDER_ID = "experiential"
EXPERIENTIAL_BASE_ORIGIN = "https://api.experientiallabs.ai/v1"
EXPERIENTIAL_ALLOWED_HOST = "api.experientiallabs.ai"
EXPERIENTIAL_CREDENTIAL_BINDING = "PADIEM_EXLAB_API_KEY"
# Owner selection 2026-10-07: the Experiential Labs lane moves off the retired
# ``gpt-5.6-luna`` pin to the GLM model the owner named. The route id carries
# the model name so the catalog can never silently drift from the upstream it
# actually calls.
EXPERIENTIAL_MODEL_ID = "experiential/glm-5.3-flash-abliterated"
EXPERIENTIAL_UPSTREAM_MODEL = "glm-5.3-flash-abliterated"
EXPERIENTIAL_DISPLAY_NAME = "Experiential Labs: GLM 5.3 Flash (abliterated)"
EXPERIENTIAL_SOURCE_CHECKED_AT = "2026-10-07"


def register_experiential_provider() -> None:
    """Register Experiential Labs and its exact manual-pin route idempotently."""

    if get_platform_provider(EXPERIENTIAL_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=EXPERIENTIAL_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=EXPERIENTIAL_CREDENTIAL_BINDING,
                base_origin=EXPERIENTIAL_BASE_ORIGIN,
                allowed_hosts=(EXPERIENTIAL_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if EXPERIENTIAL_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=EXPERIENTIAL_MODEL_ID,
        upstream_model=EXPERIENTIAL_UPSTREAM_MODEL,
        display_name=EXPERIENTIAL_DISPLAY_NAME,
        provider="Experiential Labs",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=93,
        credential_source="platform_secret",
        platform_provider_id=EXPERIENTIAL_PROVIDER_ID,
        source="experiential_labs_official_origin_and_model",
        source_checked_at=EXPERIENTIAL_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )
    CATALOG_BY_ID[model.model_id] = model


register_experiential_provider()
