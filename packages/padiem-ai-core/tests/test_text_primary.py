"""Contract tests for the canonical text-primary declaration (#3199 follow-up).

The declaration is a stdlib-only constant module; these tests pin the owner
decision (2026-09-29): the platform text primary is Space Bunny Alpha on the
keyless Kilo Gateway free lane, and SenseNova is not the text primary.
"""

from __future__ import annotations

import ast
import pathlib

import padiem_ai_core.text_primary as text_primary


def test_canonical_text_primary_is_space_bunny_alpha_via_kilo() -> None:
    assert text_primary.TEXT_PRIMARY_PROVIDER_ID == "kilo"
    assert text_primary.TEXT_PRIMARY_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert text_primary.TEXT_PRIMARY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"


def test_sensenova_is_not_the_canonical_text_primary() -> None:
    assert "sensenova" not in text_primary.TEXT_PRIMARY_MODEL_ID.lower()
    assert "sensenova" not in text_primary.TEXT_PRIMARY_UPSTREAM_MODEL.lower()
    assert "sensenova" not in text_primary.TEXT_PRIMARY_PROVIDER_ID.lower()


def test_vision_primary_stays_undecided() -> None:
    # The owner has not selected a vision primary; this module assigns no
    # vision role and activates no multimodal routing.
    assert text_primary.VISION_PRIMARY_DECISION == "UNDECIDED"


def test_declaration_imports_only_the_future_annotations_pragma() -> None:
    source = pathlib.Path(text_primary.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert len(imports) == 1
    only = imports[0]
    assert isinstance(only, ast.ImportFrom)
    assert only.module == "__future__"
