"""Contract tests for the canonical model-primary declaration (#3209)."""

from __future__ import annotations

import ast
import pathlib

import padiem_ai_core.model_primary as model_primary


def test_canonical_text_primary_is_space_bunny_alpha_via_kilo() -> None:
    assert model_primary.TEXT_PRIMARY_PROVIDER_ID == "kilo"
    assert model_primary.TEXT_PRIMARY_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert model_primary.TEXT_PRIMARY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"


def test_canonical_vision_primary_is_space_bunny_alpha_via_kilo() -> None:
    assert model_primary.VISION_PRIMARY_PROVIDER_ID == "kilo"
    assert model_primary.VISION_PRIMARY_MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert model_primary.VISION_PRIMARY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"


def test_text_secondary_and_fallback_are_none() -> None:
    assert model_primary.TEXT_SECONDARY_MODEL_ID is None
    assert model_primary.TEXT_FALLBACK_ENABLED is False


def test_vision_fallback_stays_undecided_and_video_stays_off() -> None:
    assert model_primary.VISION_FALLBACK_MODEL_ID is None
    assert model_primary.VISION_FALLBACK_DECISION == "UNDECIDED"
    assert model_primary.VIDEO_PRIMARY_DECISION == "UNDECIDED"


def test_sensenova_is_not_the_canonical_primary() -> None:
    for value in (
        model_primary.TEXT_PRIMARY_MODEL_ID,
        model_primary.TEXT_PRIMARY_UPSTREAM_MODEL,
        model_primary.TEXT_PRIMARY_PROVIDER_ID,
        model_primary.VISION_PRIMARY_MODEL_ID,
        model_primary.VISION_PRIMARY_UPSTREAM_MODEL,
        model_primary.VISION_PRIMARY_PROVIDER_ID,
    ):
        assert "sensenova" not in value.lower()


def test_declaration_is_stdlib_only_and_side_effect_free() -> None:
    source = pathlib.Path(model_primary.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "contract must not use relative package imports"
            if node.module:
                imported.add(node.module.split(".")[0])
    assert imported <= {"__future__"}, f"contract imports exceed allow-list: {imported}"
    for token in (
        "import httpx",
        "import requests",
        "import socket",
        "urllib",
        "os.environ",
        "open(",
        "register_platform_provider",
        "sqlite",
        "asyncio",
        "subprocess",
    ):
        assert token not in source, f"contract module must not contain {token!r}"
