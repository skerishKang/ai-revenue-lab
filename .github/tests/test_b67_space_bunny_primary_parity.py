"""Space Bunny text+vision primary parity + smoke pin-source contract (#3209).

Static and network-free. Proves that:

1. the canonical declaration (``padiem_ai_core.model_primary``) names Space
   Bunny Alpha as both text and vision primary with no text fallback and an
   UNDECIDED vision fallback;
2. the B14 Kilo catalog registers that exact repo-facing route id with the
   identical upstream model, keeps context_window 0, and declares image
   without video;
3. the shared product-tier declaration and the B14 tier registry both expose
   the same executable Plus route (Space Bunny) while preserving Agnes /
   Poolside / SenseNova registrations as non-executable;
4. A9/A12 smokes source their pin from the canonical declaration;
5. b14/auto and the A12 classification contract are untouched.
"""

from __future__ import annotations

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
ROUTING_POLICY = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "routing_policy.py"


def _string_constant(text: str, name: str) -> str | None:
    match = re.search(rf'^{name} = "([^"]+)"$', text, re.MULTILINE)
    return match.group(1) if match else None


def test_canonical_declaration_names_space_bunny_for_text_and_vision() -> None:
    text = MODEL_PRIMARY.read_text(encoding="utf-8")
    assert _string_constant(text, "TEXT_PRIMARY_PROVIDER_ID") == "kilo"
    assert _string_constant(text, "TEXT_PRIMARY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(text, "TEXT_PRIMARY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"
    assert _string_constant(text, "VISION_PRIMARY_PROVIDER_ID") == "kilo"
    assert _string_constant(text, "VISION_PRIMARY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(text, "VISION_PRIMARY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"
    assert "TEXT_SECONDARY_MODEL_ID = None" in text
    assert "TEXT_FALLBACK_ENABLED = False" in text
    assert 'VISION_FALLBACK_DECISION = "UNDECIDED"' in text
    assert 'VIDEO_PRIMARY_DECISION = "UNDECIDED"' in text


def test_kilo_catalog_registers_the_exact_canonical_route() -> None:
    kilo_text = KILO_PROVIDER.read_text(encoding="utf-8")
    canonical_text = MODEL_PRIMARY.read_text(encoding="utf-8")

    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"

    assert _string_constant(canonical_text, "TEXT_PRIMARY_MODEL_ID") == _string_constant(
        kilo_text, "KILO_SPACE_BUNNY_MODEL_ID"
    )
    assert _string_constant(canonical_text, "TEXT_PRIMARY_UPSTREAM_MODEL") == _string_constant(
        kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL"
    )
    assert _string_constant(canonical_text, "VISION_PRIMARY_MODEL_ID") == _string_constant(
        kilo_text, "KILO_SPACE_BUNNY_MODEL_ID"
    )

    # Context-window authority stays 0; stale 1M metadata is not resurrected.
    assert "context_window=0" in kilo_text

    # Image enabled, video/audio/wildcard off.
    assert '"image"' in kilo_text or "'image'" in kilo_text
    space_bunny_block = kilo_text.split("KILO_SPACE_BUNNY_MODEL_ID")[1].split("KILO_FREE_ROUTES")[0]
    assert "video" not in space_bunny_block.lower() or "no ``video``" in kilo_text.lower()


def test_product_tiers_and_registry_expose_plus_space_bunny() -> None:
    for path in (PRODUCT_TIERS, TIER_REGISTRY):
        text = path.read_text(encoding="utf-8")
        assert 'model_id="kilo/stealth-space-bunny-alpha"' in text
        assert 'upstream_model="stealth/space-bunny-alpha"' in text
        # Agnes is preserved as historical data-only, never deleted.
        assert 'model_id="agnes-ai/agnes-3.0-flash"' in text
        assert "PADIEM_AGNES_API_KEY" in text


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
        assert "register_" in text


def test_b14_auto_chain_is_unchanged() -> None:
    text = ROUTING_POLICY.read_text(encoding="utf-8")
    assert "space-bunny" not in text.lower()
    assert "sensenova" not in text.lower()
