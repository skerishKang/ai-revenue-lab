"""OpenCode Zen / Muse Spark 1.2 Contributor Free onboarding for P5 (#1083).

The selected HIGH route is explicit-only and uses OpenCode Zen's documented
OpenAI Responses-compatible endpoint. Registration performs no network call and
contains no secret value.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel, ensure_free_tag_requires_known_zero_price
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

OPENCODE_ZEN_PROVIDER_ID = "opencode-zen"
MUSE_SPARK_HIGH_MODEL_ID = "opencode-zen/muse-spark-1.2-contributor-free"
MUSE_SPARK_UPSTREAM_MODEL = "muse-spark-1.2-contributor-free"
OPENCODE_ZEN_BASE_ORIGIN = "https://opencode.ai/zen/v1"
OPENCODE_ZEN_CREDENTIAL_BINDING = "OPENCODE_ZEN_API_KEY"


def register_opencode_zen_provider() -> None:
    if get_platform_provider(OPENCODE_ZEN_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=OPENCODE_ZEN_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=OPENCODE_ZEN_CREDENTIAL_BINDING,
                base_origin=OPENCODE_ZEN_BASE_ORIGIN,
                allowed_hosts=("opencode.ai",),
                enabled=True,
                api_style="responses",
            )
        )

    if MUSE_SPARK_HIGH_MODEL_ID in CATALOG_BY_ID:
        return
    model = CatalogModel(
        model_id=MUSE_SPARK_HIGH_MODEL_ID,
        upstream_model=MUSE_SPARK_UPSTREAM_MODEL,
        display_name="Muse Spark 1.2 Contributor Free",
        provider="OpenCode Zen / Meta",
        provider_type="platform",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1_000_000,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding", "long_context", "free"}),
        region="외부",
        sort_order=90,
        credential_source="platform_secret",
        platform_provider_id=OPENCODE_ZEN_PROVIDER_ID,
        source="opencode_zen_docs",
        source_checked_at="2026-08-29",
        snapshot_state="configured_snapshot",
    )
    ensure_free_tag_requires_known_zero_price(model)
    CATALOG_BY_ID[model.model_id] = model


register_opencode_zen_provider()
