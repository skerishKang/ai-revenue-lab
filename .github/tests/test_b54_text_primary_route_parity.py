"""Canonical text-primary route parity + smoke pin-source contract (#3199 follow-up).

Static and network-free. Proves that:

  1. the canonical text-primary declaration (``padiem_ai_core.text_primary``)
     names Space Bunny Alpha on the Kilo Gateway free lane;
  2. the B14 Kilo catalog registers that exact repo-facing route id with the
     identical upstream model, so the two authorities can never drift;
  3. the A9/A12 production smokes source their pinned model from the
     canonical declaration and no longer hardcode SenseNova;
  4. the A12 gate document no longer pins SenseNova;
  5. the SenseNova provider registration remains intact (provider-specific
     registration is deliberately preserved; it is just not the text primary).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEXT_PRIMARY_MODULE = ROOT / "packages" / "padiem-ai-core" / "padiem_ai_core" / "text_primary.py"
KILO_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "kilo_provider.py"
SENSENOVA_PROVIDER = ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "sensenova_provider.py"
A9_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a9_production_smoke.py"
A12_SCRIPT = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a12_stream_replay_production_smoke.py"
A12_DOC = ROOT / "docs" / "operations" / "A12_STREAM_REPLAY_GATE_DEPENDENCIES.md"


def _string_constant(text: str, name: str) -> str:
    match = re.search(rf'^{name}\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, f"{name} string assignment not found"
    return match.group(1)


def test_canonical_text_primary_declaration_names_space_bunny_alpha() -> None:
    text = TEXT_PRIMARY_MODULE.read_text(encoding="utf-8")
    assert _string_constant(text, "TEXT_PRIMARY_PROVIDER_ID") == "kilo"
    assert _string_constant(text, "TEXT_PRIMARY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(text, "TEXT_PRIMARY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"


def test_kilo_catalog_registers_the_exact_canonical_route() -> None:
    kilo_text = KILO_PROVIDER.read_text(encoding="utf-8")
    canonical_text = TEXT_PRIMARY_MODULE.read_text(encoding="utf-8")

    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_MODEL_ID") == "kilo/stealth-space-bunny-alpha"
    assert _string_constant(kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL") == "stealth/space-bunny-alpha"

    # Parity across the two authorities: the canonical declaration and the
    # B14 catalog must name the same route id and upstream model.
    assert _string_constant(canonical_text, "TEXT_PRIMARY_MODEL_ID") == _string_constant(
        kilo_text, "KILO_SPACE_BUNNY_MODEL_ID"
    )
    assert _string_constant(canonical_text, "TEXT_PRIMARY_UPSTREAM_MODEL") == _string_constant(
        kilo_text, "KILO_SPACE_BUNNY_UPSTREAM_MODEL"
    )

    # The route is registered as an explicit bounded free route, and no Kilo
    # capability set declares vision/multimodal tokens (text role only).
    assert "model_id=KILO_SPACE_BUNNY_MODEL_ID" in kilo_text
    assert 'capabilities=frozenset({"chat", "coding", "free"})' in kilo_text
    capability_sets = re.findall(r"capabilities=frozenset\(\{([^}]*)\}\)", kilo_text)
    assert capability_sets, "no capability declarations found"
    for entry in capability_sets:
        assert "vision" not in entry
        assert "image" not in entry


def test_a9_and_a12_smokes_source_the_canonical_pin() -> None:
    for path in (A9_SCRIPT, A12_SCRIPT):
        text = path.read_text(encoding="utf-8")
        assert "from padiem_ai_core.text_primary import TEXT_PRIMARY_MODEL_ID" in text
        assert "PINNED_MODEL = TEXT_PRIMARY_MODEL_ID" in text
        assert "sensenova" not in text.lower()


def test_a12_dependency_document_no_longer_pins_sensenova() -> None:
    text = A12_DOC.read_text(encoding="utf-8")
    assert "sensenova/sensenova-6.8-flash-lite" not in text
    assert "padiem_ai_core.text_primary" in text


def test_sensenova_provider_registration_remains_intact() -> None:
    text = SENSENOVA_PROVIDER.read_text(encoding="utf-8")
    assert _string_constant(text, "SENSENOVA_MODEL_ID") == "sensenova/sensenova-6.8-flash-lite"
    assert "register_sensenova_provider()" in text
