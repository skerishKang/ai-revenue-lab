"""Kilo Gateway Provider 03 onboarding for Business 14 (#956).

The first bounded route is one explicit current free model rather than
``kilo-auto/free``.  Kilo's official Gateway documentation (checked
2026-09-02) lists NVIDIA Nemotron 3 Ultra as a zero-cost free model and allows
anonymous requests to free models, subject to the Gateway's current IP rate
limit.  Free availability is volatile, so this registration is a dated route
snapshot and is never inserted into ``b14/auto``.

No API key is stored or required for this route.  The fixed Kilo Gateway origin
and exact upstream model ID are server-owned metadata; callers cannot replace
either value.
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

KILO_PROVIDER_ID = "kilo"
KILO_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_UPSTREAM_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
KILO_BASE_ORIGIN = "https://api.kilo.ai/api/gateway"
KILO_ALLOWED_HOST = "api.kilo.ai"


def register_kilo_provider() -> None:
    """Idempotently register the explicit anonymous Kilo free route.

    ``CatalogModel.credential_source`` remains ``platform_secret`` as the
    current Router Core's compatibility marker for the generic platform
    execution adapter.  The authoritative Provider spec is ``NONE`` and the
    adapter therefore sends no Authorization header.  A later Router contract
    cleanup can expose ``none`` directly without changing this route's public
    model identity.
    """

    if get_platform_provider(KILO_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=KILO_PROVIDER_ID,
                credential_source=CredentialSource.NONE,
                credential_binding_name="",
                base_origin=KILO_BASE_ORIGIN,
                allowed_hosts=(KILO_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if KILO_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=KILO_MODEL_ID,
        upstream_model=KILO_UPSTREAM_MODEL,
        display_name="Kilo: NVIDIA Nemotron 3 Ultra (free)",
        provider="Kilo Gateway / NVIDIA",
        provider_type="platform",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1_000_000,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "free"}),
        region="외부",
        sort_order=90,
        credential_source="platform_secret",
        platform_provider_id=KILO_PROVIDER_ID,
        source="kilo_official_gateway_models",
        source_checked_at="2026-09-02",
        snapshot_state="configured_snapshot",
    )
    ensure_free_tag_requires_known_zero_price(model)

    # Explicit-only. Do not append to CATALOG_MODELS / b14-auto. The owner
    # explicitly rejected provider-side auto/free routing for this test lane.
    CATALOG_BY_ID[model.model_id] = model


register_kilo_provider()
