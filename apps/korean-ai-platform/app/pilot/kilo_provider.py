"""Kilo Gateway Provider 03 onboarding for Business 14 (#956).

This module keeps a bounded set of explicit current free routes rather than
``kilo-auto/free``. Kilo's official Gateway documentation checked on
2026-09-02 lists the exact upstream IDs below as free. Production execution uses the
owner-managed Kilo API credential already stored in Cloudflare Secrets Store;
the credential value is never committed, logged, returned, or exposed to
callers.

Free availability is volatile. These registrations are dated snapshots, remain
explicit/manual-only, and are never inserted into ``b14/auto``. The fixed Kilo
Gateway origin, credential binding name, and upstream model IDs are server-owned
metadata; callers cannot replace any of them.

Re-check on 2026-09-08 against the public Gateway model list (#2094):
``minimax/minimax-m3:free`` and ``tencent/hy3:free`` are no longer offered.
Both lanes are retired (see RETIRED_KILO_FREE_MODEL_IDS) and are NOT
registered in the catalog: explicit manual/auto resolution fails closed with
``unsupported_model``. The IDs and upstream models below are retained purely
as retirement metadata for contract tests and operator documentation.

Owner decision (#3143) pins ``stealth/space-bunny-alpha`` as the Business 66
quotation text primary. It is registered here as one additional explicit
free lane under the same ``kilo`` Provider spec. Owner correction #3209
reuses the existing Cloudflare Secrets Store credential through
``CredentialSource.PLATFORM_SECRET``; no new provider adapter or secret value is
introduced. Like the lanes above it is never appended to ``CATALOG_MODELS``
or to ``b14/auto``; the global auto chain and its fallback set are unchanged.
Owner decision (#3209) additionally names the same lane the canonical vision
primary for the existing single-image product contract (``chat``/``coding``/
``free`` plus ``image``): Product image requests reuse the existing B14
multimodal path. No ``video``/``audio``/generic-multimodal capability is
declared and no video product activation follows from upstream metadata.
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
KILO_CREDENTIAL_BINDING = "KILO_API_KEY"

KILO_NEMOTRON_MODEL_ID = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
KILO_NEMOTRON_UPSTREAM_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
KILO_LAGUNA_MODEL_ID = "kilo/poolside-laguna-s-2.1-free"
KILO_LAGUNA_UPSTREAM_MODEL = "poolside/laguna-s-2.1:free"

# Business 66 quotation text-primary lane (#3143). The upstream id carries no
# ``:free`` suffix, so the repo-facing id applies the same transformation used
# for the lanes above (``/`` -> ``-``, ``:`` -> ``-``) and therefore keeps no
# ``-free`` marker: ``stealth/space-bunny-alpha`` ->
# ``kilo/stealth-space-bunny-alpha``.
KILO_SPACE_BUNNY_MODEL_ID = "kilo/stealth-space-bunny-alpha"
KILO_SPACE_BUNNY_UPSTREAM_MODEL = "stealth/space-bunny-alpha"
# Date of the owner/CENTRAL evidence that re-confirmed this lane callable on
# the Kilo free route (#3143 refresh). Authentication now comes from the existing
# owner-managed KILO_API_KEY binding (#3209); this remains a dated availability
# snapshot, not a guarantee.
KILO_SPACE_BUNNY_SOURCE_CHECKED_AT = "2026-09-28"

# Retired lane identifiers kept as retirement metadata only. They are never
# registered in the catalog; #2097 removed them from KILO_FREE_ROUTES and from
# the fixed_chain_v1 fallback.
KILO_HY3_MODEL_ID = "kilo/tencent-hy3-free"
KILO_HY3_UPSTREAM_MODEL = "tencent/hy3:free"
KILO_MINIMAX_M3_MODEL_ID = "kilo/minimax-minimax-m3-free"
KILO_MINIMAX_M3_UPSTREAM_MODEL = "minimax/minimax-m3:free"

# Free lanes observed as removed from the public Kilo Gateway model list on
# 2026-09-08 (#2094). Retired lanes are unregistered and must never appear in
# any executable route lane (chain, catalog, or product tier).
RETIRED_KILO_FREE_MODEL_IDS = frozenset(
    {
        KILO_MINIMAX_M3_MODEL_ID,
        KILO_HY3_MODEL_ID,
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
    _KiloFreeRoute(
        model_id=KILO_SPACE_BUNNY_MODEL_ID,
        upstream_model=KILO_SPACE_BUNNY_UPSTREAM_MODEL,
        display_name="Kilo: Stealth Space Bunny Alpha (free)",
        provider="Kilo Gateway / Stealth",
        # No context-window figure exists in the owner/issue evidence for this
        # lane. 0 keeps it explicitly undeclared instead of inventing a value;
        # routing does not enforce context length on explicit manual routes.
        # Authority: unchanged from main (#3209 preserves the 0 sentinel and
        # does not resurrect stale #3202 metadata).
        context_window=0,
        sort_order=92,
        capabilities=frozenset({"chat", "coding", "free", "image"}),
        source_checked_at=KILO_SPACE_BUNNY_SOURCE_CHECKED_AT,
    ),
)


def register_kilo_provider() -> None:
    """Idempotently register the explicit authenticated Kilo free routes.

    ``CatalogModel.credential_source`` remains ``platform_secret`` and the
    authoritative Provider spec now matches it: B14 resolves only the existing
    ``KILO_API_KEY`` Worker binding and sends it as a Bearer credential. Missing
    credential material fails closed; callers can never supply or override it.
    """

    if get_platform_provider(KILO_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=KILO_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=KILO_CREDENTIAL_BINDING,
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


register_kilo_provider()
