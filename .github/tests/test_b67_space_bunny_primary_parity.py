"""Successor-pending canonical-primary parity contract (#3568).

Static and network-free. Space Bunny remains registered as historical/manual
B14 metadata, but Padiem has no canonical text/vision primary and no executable
Plus route until an explicit successor is selected.
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


def test_kilo_catalog_preserves_space_bunny_only_as_non_primary_metadata() -> None:
    kilo_text = KILO_PROVIDER.read_text(encoding="utf-8")
    canonical_text = MODEL_PRIMARY.read_text(encoding="utf-8")

    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_CREDENTIAL_BINDING") == "PADIEM_KILO_API_KEY"
    assert "credential_source=CredentialSource.NONE" in kilo_text

    assert "TEXT_PRIMARY_MODEL_ID = None" in canonical_text
    assert "VISION_PRIMARY_MODEL_ID = None" in canonical_text
    assert "context_window=0" in kilo_text


def test_product_tiers_and_registry_hold_plus_space_bunny() -> None:
    for path in (PRODUCT_TIERS, TIER_REGISTRY):
        text = path.read_text(encoding="utf-8")
        assert 'route_id="plus.hold.v1"' in text
        assert "model_id=PLUS_HOLD_MODEL_ID" in text
        assert 'model_id="kilo/stealth-space-bunny-alpha"' in text
        assert 'upstream_model="stealth/space-bunny-alpha"' in text
        assert "HOLD_AS_DATA_ONLY" in text
        assert 'model_id="agnes-ai/agnes-3.0-flash"' in text


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
