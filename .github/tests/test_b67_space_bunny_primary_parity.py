"""Successor-pending canonical-primary parity contract (#3568).

Static and network-free. Space Bunny survives only as historical identity
constants, not as a registered model. Since #6816 (2026-11-04, owner-merged)
the kilo host may exist as a fallback provider declaration in the B14 catalog
with zero catalog models riding it. Padiem has no canonical
text/vision primary pending owner decision.

The product-tier authority is asserted once:
``packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py``
is the LIVE route contract that Chat, Claw and Control Plane resolve
through. After the owner decisions #5009 (Plus/Pro/Max Muse primary) and
#5218 (Free Google priority, active-only product tier declaration) it holds
one EXECUTABLE route per tier and no legacy successor-pending hold route.

The unshipped legacy ``apps/korean-ai-platform/app/pilot/tier_registry_v1.py``
governance projection was deleted; no second tier registry may return.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PRIMARY = ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core" / "model_primary.py"
KILO_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "kilo_provider.py"
SENSENOVA_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "sensenova_provider.py"
AGNES_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "agnes_provider.py"
POOLSIDE_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "poolside_provider.py"
PRODUCT_TIERS = ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane" / "product_tier_routes.py"
TIER_REGISTRY = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "tier_registry_v1.py"
A9_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a9_production_smoke.py"
A12_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a12_stream_replay_production_smoke.py"
A12_DOC = ROOT / "docs" / "operations" / "A12_STREAM_REPLAY_GATE_DEPENDENCIES.md"
B14_JSON = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "b14_models.json"
ROUTING_POLICY = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "routing_policy.py"


def _string_constant(text: str, name: str) -> str | None:
    match = re.search(rf'^{name} = "([^"]+)"$', text, re.MULTILINE)
    return match.group(1) if match else None


def test_canonical_declaration_holds_text_and_vision_primary() -> None:
    text = MODEL_PRIMARY.read_text(encoding="utf-8")
    assert _string_constant(text, "TEXT_PRIMARY_DECISION") == "PENDING_SUCCESSOR_SELECTION"
    assert "TEXT_PRIMARY_PROVIDER_ID = None" in text
    assert "TEXT_PRIMARY_MODEL_ID = None" in text
    assert "TEXT_PRIMARY_UPSTREAM_MODEL = None" in text
    assert _string_constant(text, "VISION_PRIMARY_DECISION") == "PENDING_SUCCESSOR_SELECTION"
    assert "VISION_PRIMARY_PROVIDER_ID = None" in text
    assert "VISION_PRIMARY_MODEL_ID = None" in text
    assert "VISION_PRIMARY_UPSTREAM_MODEL = None" in text
    assert "TEXT_SECONDARY_MODEL_ID = None" in text
    assert "TEXT_FALLBACK_ENABLED = False" in text


def test_kilo_catalog_fully_retires_space_bunny_to_historical_metadata() -> None:
    kilo_text = KILO_PROVIDER.read_text(encoding="utf-8")
    canonical_text = MODEL_PRIMARY.read_text(encoding="utf-8")

    # Historical identity constants survive for audit purposes.
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_CREDENTIAL_BINDING") == "PADIEM_KILO_API_KEY"
    # Owner removed all Kilo live registrations, not just Space Bunny.
    assert "KILO_FREE_ROUTES: tuple[_KiloFreeRoute, ...] = ()" in kilo_text
    data=json.loads(B14_JSON.read_text(encoding="utf-8"))
    ids={m["id"] for m in data["models"]}
    assert len(ids)==len(data["models"])
    # #6816 (2026-11-04, owner-merged) re-declared the kilo host as a provider
    # declaration for the Free fallback (Kilo Crouton Alpha,
    # PADIEM_B14_CREDENTIAL_08). The retirement stays on the MODEL axis: the
    # catalog may declare the kilo provider host, but no catalog model may
    # ride it — the retired ids below stay unregistered.
    if "kilo" in data["providers"]:
        kilo_models = [m["id"] for m in data["models"] if m.get("provider") == "kilo"]
        assert kilo_models == [], kilo_models
    assert ids.isdisjoint({
        "kilo/stealth-space-bunny-alpha",
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free",
        "b-ai/qwen3.8-flash",
        "infron/motif/motif-3",
        "experiential/gpt-5.6-luna",
    })

    # Owner final retirement decision: the lane is declared retired, absent
    # from KILO_FREE_ROUTES, and no Space Bunny _KiloFreeRoute entry remains.
    retired_block = kilo_text.split("RETIRED_KILO_FREE_MODEL_IDS = frozenset(", 1)[1].split("})", 1)[0]
    assert "KILO_SPACE_BUNNY_MODEL_ID" in retired_block
    assert "model_id=KILO_SPACE_BUNNY_MODEL_ID" not in kilo_text
    assert "Kilo: Stealth Space Bunny Alpha" not in kilo_text

    assert "TEXT_PRIMARY_MODEL_ID = None" in canonical_text
    assert "VISION_PRIMARY_MODEL_ID = None" in canonical_text


def _live_route_table(text: str) -> str:
    """The live route table of the canonical product-tier contract.

    Only the route table is scanned for "must not appear" assertions. The
    retired-model and HOLD-identity constants outside the table may legitimately
    name a historical model.
    """
    marker = "PRODUCT_TIER_ROUTES: tuple[ProductTierDefinition, ...] = ("
    assert marker in text, "live product-tier route table not found"
    return text.split(marker, 1)[1]


def test_legacy_tier_registry_module_is_removed() -> None:
    """No second product-tier registry may return as a governance projection."""
    assert not TIER_REGISTRY.exists(), (
        "the unshipped B14 tier registry must stay deleted; "
        "product_tier_routes.py is the single product-tier route authority"
    )
    assert PRODUCT_TIERS.is_file(), "the live product-tier contract must remain"


def test_live_product_tier_contract_ships_no_route_values() -> None:
    """The shared declaration carries no model, provider or route values.

    #6828 3단계 moved the owner-decided routes into the private registry
    document, so the repository declaration must stay value-free: no route
    id, model id or provider id may reappear in the shipped source. The
    owner route decisions live in the private document now, not in the
    shipped source.
    """
    text = PRODUCT_TIERS.read_text(encoding="utf-8")

    # No executable route values are shipped any more.
    assert "TIER_FALLBACK_B14_MODELS" not in text
    assert "provider_id=" not in text
    assert "MUSE_ROUTE_STATUS" not in text
    # The HOLD identity markers are synthetic padiem-profile ids, not real
    # provider values; they survive as data-only identity markers.
    assert 'PLUS_HOLD_MODEL_ID = "padiem-profile/plus-hold"' in text

    # The authority boundary is explicit: the private registry document is
    # the only source of live routes.
    assert "single product-tier route authority" in text
    assert "tier_registry_v1" not in text

    # Every declared tier carries an empty route tuple: nothing dispatches
    # without the private registry document.
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location("shared_ptr_b67", PRODUCT_TIERS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    for label in module.ProductTierLabel:
        assert module.get_tier(label).routes == ()

def test_a9_and_a12_smokes_source_the_canonical_pin() -> None:
    for path in (A9_SCRIPT, A12_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert "from padiem_ai_core.model_primary import TEXT_PRIMARY_MODEL_ID" in text
        assert "PINNED_MODEL = TEXT_PRIMARY_MODEL_ID" in text
        assert "sensenova/sensenova-6.8-flash-lite" not in text


def test_a12_dependency_document_names_the_canonical_primary() -> None:
    text = A12_DOC.read_text(encoding="utf-8")
    assert "sensenova/sensenova-6.8-flash-lite" not in text
    assert "padiem_ai_core.model_primary" in text


def test_provider_registrations_remain_intact() -> None:
    for path in (SENSENOVA_PROVIDER, AGNES_PROVIDER, POOLSIDE_PROVIDER):
        assert path.is_file(), f"provider module deleted: {path.name}"
        text = path.read_text(encoding="utf-8")
        assert "legacy provider registration disabled: edit b14_models.json" in text


def test_b14_auto_chain_is_retired_entirely() -> None:
    # B7: the fixed chain (fixed_chain_v1) is retired, so the retired
    # provider ids cannot rejoin an executable auto lane at all.
    assert not ROUTING_POLICY.exists()
    pilot_sources = [
        path.read_text(encoding="utf-8")
        for path in ROUTING_POLICY.parent.rglob("*.py")
    ]
    assert all("fixed_chain_v1" not in text for text in pilot_sources)
    assert all("B14_AUTO_CHAIN" not in text for text in pilot_sources)
