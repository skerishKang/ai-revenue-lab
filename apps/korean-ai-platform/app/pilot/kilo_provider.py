"""Kilo Gateway Provider 03 onboarding for Business 14 (#956).

This module keeps a bounded set of explicit current free routes rather than
``kilo-auto/free``. Kilo's official Gateway documentation checked on
2026-09-02 lists the exact upstream IDs below as free and preserves their existing
anonymous/keyless execution contract. Space Bunny may additionally reuse the
owner-managed ``PADIEM_KILO_API_KEY`` runtime binding when it is present; the
binding maps to the existing account Secrets Store item and is optional.

Free availability is volatile. These registrations are dated snapshots, remain
explicit/manual-only, and are never inserted into ``b14/auto``. The fixed Kilo
Gateway origin, Space Bunny credential binding name, and upstream model IDs are
server-owned metadata; callers cannot replace any of them.

Re-check on 2026-09-08 against the public Gateway model list (#2094):
``minimax/minimax-m3:free`` and ``tencent/hy3:free`` are no longer offered.
Both lanes are retired (see RETIRED_KILO_FREE_MODEL_IDS) and are NOT
registered in the catalog: explicit manual/auto resolution fails closed with
``unsupported_model``. The IDs and upstream models below are retained purely
as retirement metadata for contract tests and operator documentation.

Owner decision (#3143) pinned ``stealth/space-bunny-alpha`` as the Business 66
quotation text primary. That upstream lane was REMOVED from the public Kilo
Gateway model list (re-checked 2026-10-06), and the keyless-lane preference is
RETIRED by owner policy v2 (2026-10-06): model lanes authenticate through
Secrets Store bindings (``PADIEM_KILO_API_KEY``).

Owner successor selection (2026-10-06, follow-up to #3568/#3569) pins
``inclusionai/ling-3.1-flash`` as the Business 66 quotation text primary:
verified live on the Kilo gateway (public model list present, pricing 0,
context 262,144, max completion 32,768, keyless probe HTTP 200 / cost 0).
It is registered here as an explicit free lane under the same ``kilo``
Provider spec, now executing with the Secrets Store binding per policy v2.
Like the lanes above it is never appended to ``CATALOG_MODELS``
or to ``b14/auto``; the global auto chain and its fallback set are unchanged.
The retired Space Bunny vision-primary declaration is not carried over:
Ling 3.1 Flash is text-only, so image work remains fail closed (Policy A).
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
# Policy v2 (2026-10-06): all Kilo lanes authenticate through the owner-managed
# Secrets Store binding when it resolves; the anonymous request shape remains
# the fallback when the binding is absent.
KILO_CREDENTIAL_BINDING = "PADIEM_KILO_API_KEY"

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

# Owner successor selection (2026-10-06): Ling 3.1 Flash on the same gateway.
# Upstream id carries no ``:free`` suffix -> same repo-facing transformation:
# ``inclusionai/ling-3.1-flash`` -> ``kilo/inclusionai-ling-3.1-flash``.
KILO_LING_MODEL_ID = "kilo/inclusionai-ling-3.1-flash"
KILO_LING_UPSTREAM_MODEL = "inclusionai/ling-3.1-flash"
KILO_LING_SOURCE_CHECKED_AT = "2026-10-06"
# Date of the owner/CENTRAL evidence that re-confirmed this lane callable on
# the Kilo free route (#3143 refresh). Space Bunny may use the existing
# owner-managed PADIEM_KILO_API_KEY runtime binding (#3209), but the binding is
# not required for route eligibility; this remains a dated availability snapshot.
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
    _KiloFreeRoute(
        model_id=KILO_LING_MODEL_ID,
        upstream_model=KILO_LING_UPSTREAM_MODEL,
        display_name="Kilo: InclusionAI Ling 3.1 Flash (free)",
        provider="Kilo Gateway / InclusionAI",
        context_window=262_144,
        sort_order=92,
        capabilities=frozenset({"chat", "free"}),
        source_checked_at=KILO_LING_SOURCE_CHECKED_AT,
    ),
)


def register_kilo_provider() -> None:
    """Idempotently register the explicit Kilo free routes.

    The shared Kilo Provider spec remains keyless so all free lanes preserve
    their existing contract. Space Bunny has one optional model-scoped
    ``KILO_SPACE_BUNNY_CREDENTIAL_BINDING`` in the platform adapter: when the
    binding resolves, B14 sends Bearer auth; when it does not, B14 sends the same
    anonymous request shape as the existing free lanes.
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


register_kilo_provider()
