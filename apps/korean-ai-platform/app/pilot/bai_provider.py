"""B.AI Provider onboarding for Business 14 (#2133).

Owner decision (#2126 5584200820) approved B.AI as a Padiem Pro candidate
provider with the credential name ``PADIEM_B_AI_API_KEY`` (name only; the
value never enters this repository).

ACT-0 authority — official B.AI docs (docs.b.ai), checked 2026-09-08:

- Production Base URL: ``https://api.b.ai/v1``;
- OpenAI-compatible ``POST /v1/chat/completions`` plus Responses/Messages
  protocols; Bearer authentication; streaming over SSE;
- ``qwen3.8-flash`` appears as the hosted production model ID (official code
  span and body text: "qwen3.8-flash is the hosted production model").

GLM-5.3-Flash is the owner's second named candidate, but every official page
uses the display name "GLM-5.3-Flash" and never publishes the exact ``model``
API string for it (the lowercase "glm-5-3-flash" tokens are URL slugs; the
"Supported Model IDs" guide table lists only ``glm-5.1`` for the GLM line).
#2133 forbids deriving an upstream ID from a display name, so this slice
registers ONLY ``qwen3.8-flash``. The GLM-5.3-Flash route stays blocked with
``MODEL_ID_AUTHORITY=UNKNOWN`` until the provider documents the exact ID (or
an authorized ACT-1 read of ``GET /v1/models`` proves it). No route is
fabricated in the meantime.

Registration is explicit/manual-pin only: the model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Pricing is Credits-denominated — no USD or free claim is
fabricated.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

BAI_PROVIDER_ID = "b-ai"
BAI_BASE_ORIGIN = "https://api.b.ai/v1"
BAI_ALLOWED_HOST = "api.b.ai"
BAI_CREDENTIAL_BINDING = "PADIEM_B_AI_API_KEY"

BAI_QWEN_MODEL_ID = "b-ai/qwen3.8-flash"
BAI_QWEN_UPSTREAM_MODEL = "qwen3.8-flash"
# Official docs.b.ai contract checked for #2133 ACT-0.
BAI_SOURCE_CHECKED_AT = "2026-09-08"


def register_bai_provider() -> None:
    """Idempotently register B.AI and the manual-pin qwen3.8-flash route."""

    if get_platform_provider(BAI_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=BAI_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=BAI_CREDENTIAL_BINDING,
                base_origin=BAI_BASE_ORIGIN,
                allowed_hosts=(BAI_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if BAI_QWEN_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=BAI_QWEN_MODEL_ID,
        upstream_model=BAI_QWEN_UPSTREAM_MODEL,
        display_name="B.AI: Qwen3.8 Flash",
        provider="B.AI / Alibaba Qwen",
        provider_type="platform",
        # Credits-denominated pricing (with a time-limited 0-Credits promo) is
        # not a USD rate: never fabricate price or a permanent free claim.
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        # Official page: hosted production model with "a default 1M-token
        # context window".
        context_window=1_000_000,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding", "long_context"}),
        region="외부",
        sort_order=79,
        credential_source="platform_secret",
        platform_provider_id=BAI_PROVIDER_ID,
        source="bai_official_llmservice_docs",
        source_checked_at=BAI_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )

    # Manual-pin capable: exact-ID lookup table only. Do not append to
    # CATALOG_MODELS (the legacy public/b14-auto routing surface).
    CATALOG_BY_ID[model.model_id] = model


register_bai_provider()
