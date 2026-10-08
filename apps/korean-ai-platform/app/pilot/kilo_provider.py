"""Kilo Gateway Provider 03 onboarding for Business 14 (#956).

This module keeps a bounded set of explicit current free routes rather than
``kilo-auto/free``. Kilo's official Gateway documentation checked on
2026-09-02 lists the exact upstream IDs below as free and preserves their
existing anonymous/keyless execution contract.

Free availability is volatile. These registrations are dated snapshots, remain
explicit/manual-only, and are never inserted into ``b14/auto``. The fixed Kilo
Gateway origin and upstream model IDs are server-owned metadata; callers
cannot replace any of them.

Re-check on 2026-09-08 against the public Gateway model list (#2094):
``minimax/minimax-m3:free`` and ``tencent/hy3:free`` are no longer offered.
Both lanes are retired (see RETIRED_KILO_FREE_MODEL_IDS) and are NOT
registered in the catalog: explicit manual/auto resolution fails closed with
``unsupported_model``. The IDs and upstream models below are retained purely
as retirement metadata for contract tests and operator documentation.

Owner final decision (LOCAL4, 2026-10-07): the Space Bunny lane
(``kilo/stealth-space-bunny-alpha``) is fully retired as well. It executes
nowhere: no product execution, no manual execution, no auto route, and no
fallback. The historical constants (model id, upstream id, credential
binding name, dated evidence snapshot) remain as retirement metadata only.
The lane is absent from ``KILO_FREE_ROUTES`` and from the catalog, and its
id lives in ``RETIRED_KILO_FREE_MODEL_IDS`` so explicit resolution fails
closed. The retired lane supports no runtime auth special-case.
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
KILO_SPACE_BUNNY_CREDENTIAL_BINDING = "PADIEM_KILO_API_KEY"

KILO_NEMOTRON_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_NEMOTRON_UPSTREAM_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
KILO_LAGUNA_MODEL_ID = "kilo/poolside-laguna-s-2.1-free"
KILO_LAGUNA_UPSTREAM_MODEL = "poolside/laguna-s-2.1:free"

# Historical Business 66 quotation lane identity (#3143). The upstream id
# carries no ``:free`` suffix, so the repo-facing id applies the same
# transformation used for the lanes above (``/`` -> ``-``, ``:`` -> ``-``) and
# therefore keeps no ``-free`` marker: ``stealth/space-bunny-alpha`` ->
# ``kilo/stealth-space-bunny-alpha``.
KILO_SPACE_BUNNY_MODEL_ID = "kilo/stealth-space-bunny-alpha"
KILO_SPACE_BUNNY_UPSTREAM_MODEL = "stealth/space-bunny-alpha"
# Dated availability snapshot from the owner/CENTRAL evidence that once
# re-confirmed this lane callable on the Kilo free route (#3143 refresh).
# Retained purely as historical evidence metadata: the lane is retired and
# never executes (#3568 plus the owner final retirement decision).
KILO_SPACE_BUNNY_SOURCE_CHECKED_AT = "2026-09-28"

# Retired lane identifiers kept as retirement metadata only. They are never
# registered in the catalog; #2097 removed the minimax/hy3 pair from
# KILO_FREE_ROUTES and from the fixed_chain_v1 fallback.
KILO_HY3_MODEL_ID = "kilo/tencent-hy3-free"
KILO_HY3_UPSTREAM_MODEL = "tencent/hy3:free"
KILO_MINIMAX_M3_MODEL_ID = "kilo/minimax-minimax-m3-free"
KILO_MINIMAX_M3_UPSTREAM_MODEL = "minimax/minimax-m3:free"

# Free lanes observed as removed from the public Kilo Gateway model list on
# 2026-09-08 (#2094), plus the Space Bunny lane retired everywhere by the
# owner final decision (2026-10-07). Retired lanes are unregistered and must
# never appear in any executable route lane (chain, catalog, or product tier).
RETIRED_KILO_FREE_MODEL_IDS = frozenset(
    {
        KILO_MINIMAX_M3_MODEL_ID,
        KILO_HY3_MODEL_ID,
        KILO_SPACE_BUNNY_MODEL_ID,
    }
)

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
    # Defaults keep the original free lanes byte-for-byte identical: they were
    # registered with ``chat``/``free`` only and a 2026-09-02 snapshot date.
    capabilities: frozenset[str] = frozenset({"chat", "free"})
    source_checked_at: str = "2026-09-02"


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
)
# Historical note: the Space Bunny lane (kilo/stealth-space-bunny-alpha,
# sort_order 92, capabilities {chat, coding, free, image}, context_window 0)
# was removed from KILO_FREE_ROUTES by the owner final retirement decision
# (2026-10-07). Its identity survives only in the constants and retired set
# above.


def register_kilo_provider() -> None:
    """Idempotently register the explicit Kilo free routes.

    The shared Kilo Provider spec stays keyless so all registered free lanes
    preserve their existing anonymous contract. No retired lane (including
    Space Bunny) is registered here, and no lane carries a model-scoped auth
    special-case in the platform adapter.
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
            capabilities=route.capabilities,
            region="외부",
            sort_order=route.sort_order,
            credential_source="platform_secret",
            platform_provider_id=KILO_PROVIDER_ID,
            source="kilo_official_gateway_models",
            source_checked_at=route.source_checked_at,
            snapshot_state="configured_snapshot",
        )
        ensure_free_tag_requires_known_zero_price(model)

        # Explicit-only. Do not append to CATALOG_MODELS / b14-auto. The owner
        # explicitly rejected provider-side auto/free routing for this lane.
        CATALOG_BY_ID[model.model_id] = model



# No import-time registration: canonical b14_models.json owns runtime models.
