"""Route execution contract for the Space Bunny text+vision primary lane (#3209).

Owner decision: ``stealth/space-bunny-alpha`` is both the canonical text
primary and the canonical vision primary (decision source #3143, revised
#3209). Everything here runs against the real registry, the real provider
spec, and the real router resolvers — no string-presence checks — so the
evidence is the actual registry result, not a keyword match.

Scope is the existing single-image product contract: the lane declares
``image`` alongside ``chat``/``coding``/``free`` and reuses the existing B14
multimodal path. No ``video``/``audio``/generic-multimodal capability is
declared and the global ``b14/auto`` chain stays unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import CATALOG_MODELS, get_catalog_by_id
from app.pilot.kilo_provider import (
    KILO_FREE_ROUTES,
    KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
    KILO_HY3_MODEL_ID,
    KILO_LAGUNA_MODEL_ID,
    KILO_LAGUNA_UPSTREAM_MODEL,
    KILO_MINIMAX_M3_MODEL_ID,
    KILO_NEMOTRON_MODEL_ID,
    KILO_NEMOTRON_UPSTREAM_MODEL,
    KILO_PROVIDER_ID,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_SOURCE_CHECKED_AT,
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
    "KILO_PROVIDER_ID",
    "platform_provider_id",
)


@pytest.fixture(autouse=True)
def _space_bunny_kilo_secret(monkeypatch):
    monkeypatch.setenv(
        KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
        "kilo_live_abcdefghijklmnopqrstuvwxyz1234",
    )


def _browser_sources() -> list[Path]:
    return sorted(
        path
        for path in B66_BROWSER_DIR.iterdir()
        if path.is_file() and path.suffix in {".js", ".html", ".css"}
    )


def test_space_bunny_route_is_registered_on_the_existing_kilo_provider() -> None:
    model = get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID)
    assert model is not None, "space bunny lane is not registered in the catalog"
    assert model.platform_provider_id == KILO_PROVIDER_ID
    assert model.upstream_model == KILO_SPACE_BUNNY_UPSTREAM_MODEL
    assert model.upstream_model == "stealth/space-bunny-alpha"
    assert model.provider == "Kilo Gateway / Stealth"
    assert model.enabled is True
    assert model.input_price_usd_per_1m == 0.0
    assert model.output_price_usd_per_1m == 0.0
    assert model.source_checked_at == KILO_SPACE_BUNNY_SOURCE_CHECKED_AT
    # Context-window authority stays exactly as current main (#3209): the lane
    # keeps the explicit 0 sentinel instead of inventing a value.
    assert model.context_window == 0


def test_space_bunny_reuses_model_scoped_kilo_secret() -> None:
    spec = ps.get_platform_provider(KILO_PROVIDER_ID)
    assert spec is not None

    # Shared historical Kilo provider remains keyless.
    assert spec.credential_source == ps.CredentialSource.NONE
    assert spec.credential_binding_name == ""
    assert ps.is_secret_present(spec) is True
    assert "Authorization" not in plat._request_headers(spec)

    # Space Bunny alone consumes the existing owner-managed credential.
    headers = plat._request_headers(spec, model_id=KILO_SPACE_BUNNY_MODEL_ID)
    assert headers["Authorization"] == "Bearer kilo_live_abcdefghijklmnopqrstuvwxyz1234"
    assert headers["Content-Type"] == "application/json"


def test_space_bunny_declares_text_and_image_capabilities_only() -> None:
    model = get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID)
    assert model is not None
    assert {"chat", "coding", "free", "image"}.issubset(model.capabilities)
    # Video product activation stays off (#3209): upstream metadata may list
    # video input, but no video/audio/wildcard capability is declared.
    unsupported = {"vision", "video", "multimodal", "audio"}
    assert model.capabilities & unsupported == frozenset()


def test_space_bunny_manual_resolution_is_explicit_and_fallback_free() -> None:
    decision = resolve_manual_route(KILO_SPACE_BUNNY_MODEL_ID)
    assert decision.route_mode == "manual"
    assert decision.selected_model == KILO_SPACE_BUNNY_MODEL_ID
    assert decision.selected_upstream_model == "stealth/space-bunny-alpha"
    assert decision.platform_provider_id == KILO_PROVIDER_ID
    assert decision.selected_route_id == f"platform:{KILO_SPACE_BUNNY_MODEL_ID}"
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

    # Retired lanes stay unregistered (#2097): the new lane must not revive them.
    assert get_catalog_by_id(KILO_HY3_MODEL_ID) is None
    assert get_catalog_by_id(KILO_MINIMAX_M3_MODEL_ID) is None

    registered = {route.model_id for route in KILO_FREE_ROUTES}
    assert registered == {
        KILO_NEMOTRON_MODEL_ID,
        KILO_LAGUNA_MODEL_ID,
        KILO_SPACE_BUNNY_MODEL_ID,
    }


def test_global_b14_auto_chain_is_unchanged_by_this_lane() -> None:
    # The lane must stay out of the auto lane's model list entirely.
    assert KILO_SPACE_BUNNY_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}

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
    assert KILO_LAGUNA_MODEL_ID not in fallback_ids


@pytest.mark.asyncio
async def test_space_bunny_call_shape_is_accepted_by_the_platform_stream_adapter(
    monkeypatch,
) -> None:
    """The provider-generic streaming adapter accepts this route's call shape.

    Mock provider mode keeps the check network-free while still exercising the
    real ``stream_platform_chat_completions`` entry point with the registered
    provider id, upstream model, and model-scoped Kilo credential.
    """
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    model = get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID)
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


def test_space_bunny_missing_model_scoped_secret_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv(KILO_SPACE_BUNNY_CREDENTIAL_BINDING, raising=False)
    with pytest.raises(Exception) as exc_info:
        resolve_manual_route(KILO_SPACE_BUNNY_MODEL_ID)
    assert "비밀키" in str(exc_info.value) or "secret" in str(exc_info.value).lower()
