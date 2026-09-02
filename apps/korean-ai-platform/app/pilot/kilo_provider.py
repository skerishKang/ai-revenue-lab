"""Kilo Gateway Provider 03 onboarding for Business 14 (#956).

This module keeps a bounded set of explicit current free routes rather than
``kilo-auto/free``. Kilo's official Gateway documentation checked on
2026-09-02 lists the exact upstream IDs below as free and allows anonymous
requests to free models, subject to the Gateway's current IP rate limit.

Free availability is volatile. These registrations are dated snapshots, remain
explicit/manual-only, and are never inserted into ``b14/auto``. No API key is
stored or required for these routes. The fixed Kilo Gateway origin and upstream
model IDs are server-owned metadata; callers cannot replace either value.
"""

from __future__ import annotations

from dataclasses import dataclass

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
KILO_BASE_ORIGIN = "https://api.kilo.ai/api/gateway"
KILO_ALLOWED_HOST = "api.kilo.ai"

KILO_NEMOTRON_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_NEMOTRON_UPSTREAM_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
KILO_LAGUNA_MODEL_ID = "kilo/poolside-laguna-s-2.1-free"
KILO_LAGUNA_UPSTREAM_MODEL = "poolside/laguna-s-2.1:free"
KILO_HY3_MODEL_ID = "kilo/tencent-hy3-free"
KILO_HY3_UPSTREAM_MODEL = "tencent/hy3:free"
KILO_MINIMAX_M3_MODEL_ID = "kilo/minimax-minimax-m3-free"
KILO_MINIMAX_M3_UPSTREAM_MODEL = "minimax/minimax-m3:free"

# Backwards-compatible names used by the first Provider 03 tests/consumers.
KILO_MODEL_ID = KILO_NEMOTRON_MODEL_ID
KILO_UPSTREAM_MODEL = KILO_NEMOTRON_UPSTREAM_MODEL


@dataclass(frozen=True, slots=True)
class _KiloFreeRoute:
    model_id: str
    upstream_model: str
    display_name: str
    provider: str
    context_window: int
    sort_order: int


KILO_FREE_ROUTES = (
    _KiloFreeRoute(
        model_id=KILO_NEMOTRON_MODEL_ID,
        upstream_model=KILO_NEMOTRON_UPSTREAM_MODEL,
        display_name="Kilo: NVIDIA Nemotron 3 Ultra (free)",
        provider="Kilo Gateway / NVIDIA",
        context_window=1_000_000,
        sort_order=90,
    ),
    _KiloFreeRoute(
        model_id=KILO_LAGUNA_MODEL_ID,
        upstream_model=KILO_LAGUNA_UPSTREAM_MODEL,
        display_name="Kilo: Poolside Laguna S 2.1 (free)",
        provider="Kilo Gateway / Poolside",
        context_window=262_144,
        sort_order=91,
    ),
    _KiloFreeRoute(
        model_id=KILO_HY3_MODEL_ID,
        upstream_model=KILO_HY3_UPSTREAM_MODEL,
        display_name="Kilo: Tencent Hy3 (free)",
        provider="Kilo Gateway / Tencent",
        context_window=262_144,
        sort_order=92,
    ),
    _KiloFreeRoute(
        model_id=KILO_MINIMAX_M3_MODEL_ID,
        upstream_model=KILO_MINIMAX_M3_UPSTREAM_MODEL,
        display_name="Kilo: MiniMax M3 (free)",
        provider="Kilo Gateway / MiniMax",
        context_window=1_048_576,
        sort_order=93,
    ),
)


def register_kilo_provider() -> None:
    """Idempotently register the explicit anonymous Kilo free routes.

    ``CatalogModel.credential_source`` remains ``platform_secret`` as the
    current Router Core's compatibility marker for the generic platform
    execution adapter. The authoritative Provider spec is ``NONE`` and the
    adapter therefore sends no Authorization header. A later Router contract
    cleanup can expose ``none`` directly without changing public model IDs.
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

    for route in KILO_FREE_ROUTES:
        if route.model_id in CATALOG_BY_ID:
            continue

        model = CatalogModel(
            model_id=route.model_id,
            upstream_model=route.upstream_model,
            display_name=route.display_name,
            provider=route.provider,
            provider_type="platform",
            input_price_usd_per_1m=0.0,
            output_price_usd_per_1m=0.0,
            currency="usd",
            context_window=route.context_window,
            korean_score=0,
            latency_ms=0,
            capabilities=frozenset({"chat", "free"}),
            region="외부",
            sort_order=route.sort_order,
            credential_source="platform_secret",
            platform_provider_id=KILO_PROVIDER_ID,
            source="kilo_official_gateway_models",
            source_checked_at="2026-09-02",
            snapshot_state="configured_snapshot",
        )
        ensure_free_tag_requires_known_zero_price(model)

        # Explicit-only. Do not append to CATALOG_MODELS / b14-auto. The owner
        # explicitly rejected provider-side auto/free routing for this lane.
        CATALOG_BY_ID[model.model_id] = model


register_kilo_provider()
