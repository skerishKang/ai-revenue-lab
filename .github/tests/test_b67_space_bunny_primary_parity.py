"""Successor-pending canonical-primary parity contract (#3568).

Static and network-free. Space Bunny survives only as historical identity
constants, not as a registered model/provider. Padiem has no canonical
text/vision primary pending owner decision.

The two product-tier authorities are asserted separately, because they are NOT
the same surface:

* ``packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py``
  is the LIVE route contract that Chat, Claw and Control Plane resolve
  through. After the owner decisions #5009 (Plus/Pro/Max Muse primary) and
  #5218 (Free Google priority, active-only product tier declaration) it holds
  one EXECUTABLE route per tier and no legacy successor-pending hold route.
* ``apps/korean-ai-platform/app/pilot/tier_registry_v1.py`` is the legacy
  governance projection (the live contract states it is "not the live route").
  It still carries the #3568 Plus hold and its historical data-only routes.

The previous single shared assertion demanded the legacy hold shape in BOTH
files, which stopped matching the live contract when #5218 landed.
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
    assert "kilo" not in data["providers"]
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


def test_legacy_tier_registry_keeps_the_plus_hold_and_space_bunny_data_only() -> None:
    """The legacy governance projection still holds the #3568 Plus posture."""
    text = TIER_REGISTRY.read_text(encoding="utf-8")
    assert 'route_id="plus.hold.v1"' in text
    assert "model_id=PLUS_HOLD_MODEL_ID" in text
    assert 'model_id="kilo/stealth-space-bunny-alpha"' in text
    assert 'upstream_model="stealth/space-bunny-alpha"' in text
    assert "HOLD_AS_DATA_ONLY" in text
    assert 'model_id="agnes-ai/agnes-3.0-flash"' in text


def test_live_product_tier_contract_uses_google_and_holds_muse_without_the_legacy_plus_hold() -> None:
    """The live route contract carries the owner-decided routes only.

    Owner decision 2026-10-25: one executable Google route per tier with
    Muse held as data. The successor-pending Plus hold and superseded Space
    Bunny / Agnes routes are not live routes and must not reappear in the
    route table.
    """
    text = PRODUCT_TIERS.read_text(encoding="utf-8")

    # The owner-decided Google route is explicit; Muse is preserved as HOLD.
    assert 'route_id=f"{tier}.gemini-3.5-flash-lite.v1"' in text
    assert "model_id=TEST_PHASE_PRIMARY_B14_MODEL_ID" in text
    assert 'provider_id="google"' in text
    assert 'evidence="Owner test-phase Google primary decision 2026-10-25."' in text
    assert "MUSE_ROUTE_STATUS = ProductRouteStatus.HOLD_AS_DATA_ONLY" in text
    assert "status=MUSE_ROUTE_STATUS" in text

    # The historical HOLD identity survives as an identity marker only, and
    # the data-only status is still part of the contract vocabulary.
    assert 'PLUS_HOLD_MODEL_ID = "padiem-profile/plus-hold"' in text
    assert "HOLD_AS_DATA_ONLY" in text

    # The authority boundary between the two product-tier surfaces is explicit.
    assert "is a separate legacy governance projection, not the live route" in text

    table = _live_route_table(text)
    assert 'route_id="plus.hold.v1"' not in table, (
        "the legacy successor-pending Plus hold route must not be a live route"
    )
    assert "model_id=PLUS_HOLD_MODEL_ID" not in table, (
        "a HOLD identity marker must not be declared as a live route model"
    )
    assert "kilo/stealth-space-bunny-alpha" not in table, (
        "Space Bunny is historical data only and must not be a live route"
    )
    assert "stealth/space-bunny-alpha" not in table
    assert "agnes-ai/agnes-3.0-flash" not in table, (
        "the superseded Agnes route must not be a live route"
    )


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


def test_b14_auto_chain_is_unchanged() -> None:
    text = ROUTING_POLICY.read_text(encoding="utf-8")
    assert "space-bunny" not in text.lower()
    assert "sensenova" not in text.lower()
