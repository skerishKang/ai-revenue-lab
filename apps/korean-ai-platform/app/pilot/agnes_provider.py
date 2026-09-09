"""Agnes AI Provider onboarding for Business 14 (#2133).

Owner decision (#2126 5584200820) re-approved Agnes as an explicit Plus-pool
candidate after the #1933 S2-b retirement of the first Agnes integration.
ACT-0 authority for this route is the repository intake record
``docs/providers/AGNES_AI_V1.md`` (research snapshot 2026-08-27): OpenAI-
compatible fixed origin ``https://apihub.agnes-ai.com/v1``, Bearer auth,
advertised streaming, model ``agnes-2.5-flash``. The owner-approved credential
binding name is ``PADIEM_AGNES_API_KEY`` (names only; the value is never read,
printed, or committed here).

Registration is explicit/manual-pin only: the model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Pricing: the intake records a Credits-denominated free/default
tier, not USD rates — no price or free claim is fabricated here.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

AGNES_PROVIDER_ID = "agnes-ai"
AGNES_BASE_ORIGIN = "https://apihub.agnes-ai.com/v1"
AGNES_ALLOWED_HOST = "apihub.agnes-ai.com"
AGNES_CREDENTIAL_BINDING = "PADIEM_AGNES_API_KEY"

AGNES_MODEL_ID = "agnes-ai/agnes-2.5-flash"
AGNES_UPSTREAM_MODEL = "agnes-2.5-flash"
# Authority date of the intake record facts this registration reuses (#2133 ACT-0).
AGNES_SOURCE_CHECKED_AT = "2026-08-27"


def register_agnes_provider() -> None:
    """Idempotently register Agnes AI and the manual-pin agnes-2.5-flash route."""

    if get_platform_provider(AGNES_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=AGNES_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=AGNES_CREDENTIAL_BINDING,
                base_origin=AGNES_BASE_ORIGIN,
                allowed_hosts=(AGNES_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if AGNES_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=AGNES_MODEL_ID,
        upstream_model=AGNES_UPSTREAM_MODEL,
        display_name="Agnes: 2.5 Flash",
        provider="Agnes AI",
        provider_type="platform",
        # Credits-denominated provider pricing is not a USD rate: never fabricate.
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=0,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding"}),
        region="외부",
        sort_order=78,
        credential_source="platform_secret",
        platform_provider_id=AGNES_PROVIDER_ID,
        source="agnes_official_public_docs (#917 intake record)",
        source_checked_at=AGNES_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )

    # Manual-pin capable: exact-ID lookup table only. Do not append to
    # CATALOG_MODELS (the legacy public/b14-auto routing surface).
    CATALOG_BY_ID[model.model_id] = model


register_agnes_provider()
