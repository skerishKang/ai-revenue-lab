"""Contract tests for the model-neutral canonical primary declaration (#3568)."""

from __future__ import annotations

import ast
import pathlib

import padiem_ai_core.model_primary as model_primary


def test_text_primary_is_ling_3_1_flash_successor() -> None:
    assert model_primary.TEXT_PRIMARY_DECISION == (
        "Owner successor selection 2026-10-06 (Ling 3.1 Flash, Kilo gateway)"
    )
    assert model_primary.TEXT_PRIMARY_PROVIDER_ID == "kilo"
    assert model_primary.TEXT_PRIMARY_MODEL_ID == "kilo/inclusionai-ling-3.1-flash"
    assert model_primary.TEXT_PRIMARY_UPSTREAM_MODEL == "inclusionai/ling-3.1-flash"


def test_vision_primary_is_pending_successor_selection() -> None:
    assert model_primary.VISION_PRIMARY_DECISION == "PENDING_SUCCESSOR_SELECTION"
    assert model_primary.VISION_PRIMARY_PROVIDER_ID is None
    assert model_primary.VISION_PRIMARY_MODEL_ID is None
    assert model_primary.VISION_PRIMARY_UPSTREAM_MODEL is None


def test_secondary_and_fallback_are_not_silently_promoted() -> None:
    assert model_primary.TEXT_SECONDARY_MODEL_ID is None
    assert model_primary.TEXT_FALLBACK_ENABLED is False
    assert model_primary.VISION_FALLBACK_MODEL_ID is None
    assert model_primary.VISION_FALLBACK_DECISION == "UNDECIDED"
    assert model_primary.VIDEO_PRIMARY_DECISION == "UNDECIDED"


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
