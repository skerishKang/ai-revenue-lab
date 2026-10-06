"""Kilo lane execution contract after the #3579 policy v2 successor change.

The Space Bunny upstream lane ended; the owner selected
``inclusionai/ling-3.1-flash`` as the Plus text successor (2026-10-06).
Space Bunny keeps only retirement metadata and is no longer registered in
the catalog. Everything here runs against the real registry, the real
provider spec, and the real router resolvers — no string-presence checks —
so the evidence is the actual registry result, not a keyword match.

The global ``b14/auto`` chain stays unchanged: Kilo lanes remain
explicit-only (never appended to ``CATALOG_MODELS``), and no
``video``/``audio``/generic-multimodal capability is declared anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import CATALOG_MODELS, get_catalog_by_id
from app.pilot.kilo_provider import (
    KILO_CREDENTIAL_BINDING,
    KILO_FREE_ROUTES,
    KILO_HY3_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    KILO_LAGUNA_UPSTREAM_MODEL,
    KILO_LING_MODEL_ID,
    KILO_LING_SOURCE_CHECKED_AT,
    KILO_LING_UPSTREAM_MODEL,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_NEMOTRON_UPSTREAM_MODEL,
    KILO_PROVIDER_ID,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_UPSTREAM_MODEL,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route

B66_BROWSER_DIR = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
)

# Business 66 browser code must never learn which model or provider runs the
# extraction. These are the exact strings this change introduces.
FORBIDDEN_BROWSER_TOKENS = (
    "stealth/space-bunny-alpha",
    "kilo/stealth-space-bunny-alpha",
    "space-bunny",
    "inclusionai/ling-3.1-flash",
    "kilo/inclusionai-ling-3.1-flash",
    "ling-3.1",
    "KILO_PROVIDER_ID",
    "platform_provider_id",
    "PADIEM_KILO_API_KEY",
)


def _browser_sources() -> list[Path]:
    return sorted(
        path
        for path in B66_BROWSER_DIR.iterdir()
        if path.is_file() and path.suffix in {".js", ".html", ".css"}
    )


def test_ling_successor_route_is_registered_on_the_existing_kilo_provider() -> None:
    model = get_catalog_by_id(KILO_LING_MODEL_ID)
    assert model is not None, "ling successor lane is not registered in the catalog"
    assert model.platform_provider_id == KILO_PROVIDER_ID
    assert model.upstream_model == KILO_LING_UPSTREAM_MODEL
    assert model.upstream_model == "inclusionai/ling-3.1-flash"
    assert model.provider == "Kilo Gateway / InclusionAI"
    assert model.enabled is True
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert model.source_checked_at == KILO_LING_SOURCE_CHECKED_AT
    # Context-window authority is the public Kilo gateway listing for the
    # successor lane (262,144 tokens), not an invented value.
    assert model.context_window == 262_144

    # The ended Space Bunny upstream lane keeps retirement metadata only.
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None


def test_kilo_lanes_share_the_optional_owner_managed_binding(monkeypatch) -> None:
    spec = ps.get_platform_provider(KILO_PROVIDER_ID)
    assert spec is not None

    # The fixed Provider spec itself stays keyless; policy v2 scopes the
    # shared owner-managed binding per request at the adapter boundary.
    assert spec.credential_source == ps.CredentialSource.NONE
    assert spec.credential_binding_name == ""
    assert "Authorization" not in plat._request_headers(spec)

    # Existing owner-managed key authenticates the successor lane when present.
    monkeypatch.setenv(
        KILO_CREDENTIAL_BINDING,
        "kilo_live_abcdefghijklmnopqrstuvwxyz1234",
    )
    authenticated = plat._request_headers(spec, model_id=KILO_LING_MODEL_ID)
    assert authenticated["Authorization"] == "Bearer kilo_live_abcdefghijklmnopqrstuvwxyz1234"

    # Missing binding falls back to the anonymous request shape.
    monkeypatch.delenv(KILO_CREDENTIAL_BINDING, raising=False)
    anonymous = plat._request_headers(spec, model_id=KILO_LING_MODEL_ID)
    assert anonymous == {"Content-Type": "application/json"}


def test_ling_declares_text_capabilities_only() -> None:
    model = get_catalog_by_id(KILO_LING_MODEL_ID)
    assert model is not None
    assert {"chat", "free"}.issubset(model.capabilities)
    # Ling 3.1 Flash is a text lane: no vision/video/multimodal capability is
    # declared, and the retired Space Bunny lane is no longer registered.
    unsupported = {"vision", "video", "multimodal", "audio", "image"}
    assert model.capabilities & unsupported == frozenset()


def test_ling_manual_resolution_is_explicit_and_fallback_free() -> None:
    decision = resolve_manual_route(KILO_LING_MODEL_ID)
    assert decision.route_mode == "manual"
    assert decision.selected_model == KILO_LING_MODEL_ID
    assert decision.selected_upstream_model == "inclusionai/ling-3.1-flash"
    assert decision.platform_provider_id == KILO_PROVIDER_ID
    assert decision.selected_route_id == f"platform:{KILO_LING_MODEL_ID}"
    assert decision.fallback_allowed is False
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 1
    assert decision.credential_available is True
    assert decision.credential_status == "key_available"


def test_existing_kilo_routes_are_preserved_unchanged() -> None:
    nemotron = get_catalog_by_id(KILO_NEMOTRON_MODEL_ID)
    laguna = get_catalog_by_id(KILO_LAGUNA_MODEL_ID)
    assert nemotron is not None and laguna is not None
    assert nemotron.upstream_model == KILO_NEMOTRON_UPSTREAM_MODEL
    assert laguna.upstream_model == KILO_LAGUNA_UPSTREAM_MODEL
    # nemotron is seeded from ``CATALOG_MODELS`` (the provider loop skips an
    # already-present id), laguna comes from the loop itself. Neither set is
    # widened by the new lane — this pins their current exact values.
    assert nemotron.capabilities == frozenset({"chat", "coding", "free"})
    assert laguna.capabilities == frozenset({"chat", "free"})
    assert nemotron.context_window == 1_000_000
    assert laguna.context_window == 262_144

    # Retired lanes stay unregistered (#2097, #3579): the successor lane must
    # not revive them.
    assert get_catalog_by_id(KILO_HY3_MODEL_ID) is None
    assert get_catalog_by_id(KILO_MINIMAX_M3_MODEL_ID) is None
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None

    registered = {route.model_id for route in KILO_FREE_ROUTES}
    assert registered == {
        KILO_NEMOTRON_MODEL_ID,
        KILO_LAGUNA_MODEL_ID,
        KILO_LING_MODEL_ID,
    }


def test_global_b14_auto_chain_is_unchanged_by_this_lane() -> None:
    # The lanes must stay out of the auto lane's model list entirely.
    assert KILO_SPACE_BUNNY_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}
    assert KILO_LING_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}

    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["free"],
        optimize_for="balanced",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == KILO_NEMOTRON_MODEL_ID
    assert decision.eligible_fallback == []

    fallback_ids = {item["model_id"] for item in decision.eligible_fallback}
    assert KILO_SPACE_BUNNY_MODEL_ID not in fallback_ids
    assert KILO_LING_MODEL_ID not in fallback_ids
    assert KILO_LAGUNA_MODEL_ID not in fallback_ids


@pytest.mark.asyncio
async def test_ling_call_shape_is_accepted_by_the_platform_stream_adapter(
    monkeypatch,
) -> None:
    """The provider-generic streaming adapter accepts this route's call shape.

    Mock provider mode keeps the check network-free while still exercising the
    real ``stream_platform_chat_completions`` entry point with the registered
    provider id, upstream model, and the shared Kilo credential boundary.
    """
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    model = get_catalog_by_id(KILO_LING_MODEL_ID)
    assert model is not None

    events = []
    async for event in plat.stream_platform_chat_completions(
        model_id=model.model_id,
        upstream_model=model.upstream_model,
        provider=model.provider,
        platform_provider_id=model.platform_provider_id,
        messages=[{"role": "user", "content": "견적서 항목을 추출해 주세요"}],
    ):
        events.append(event)

    assert events, "stream adapter produced no events for the lane"
    assert any(getattr(event, "done", False) for event in events)


def test_business_66_browser_sources_carry_no_model_or_provider_identity() -> None:
    sources = _browser_sources()
    assert sources, f"no Business 66 browser sources found under {B66_BROWSER_DIR}"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_BROWSER_TOKENS:
            assert token not in text, f"{token!r} leaked into {path.name}"
