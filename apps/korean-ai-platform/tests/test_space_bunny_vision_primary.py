"""Retirement contract for the historical Space Bunny B14 lane (#3568, LOCAL4 final).

Space Bunny executes nowhere: no product execution, no manual execution, no
auto route, no fallback. These tests pin that end state without any live
provider call while preserving the historical metadata constants.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import NoSafeRoute
from app.pilot.kilo_provider import (
    KILO_SPACE_BUNNY_CREDENTIAL_BINDING,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_UPSTREAM_MODEL,
    RETIRED_KILO_FREE_MODEL_IDS,
)
from app.pilot.router_core import resolve_manual_route

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_PATH = (
    REPO_ROOT
    / "packages"
    / "padiem-ai-core"
    / "padiem_ai_core"
    / "model_primary.py"
)


def test_space_bunny_is_not_canonical_primary_and_is_unregistered() -> None:
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    assert 'TEXT_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"' in text
    assert "TEXT_PRIMARY_MODEL_ID = None" in text
    assert "TEXT_PRIMARY_UPSTREAM_MODEL = None" in text
    assert 'VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"' in text
    assert "VISION_PRIMARY_MODEL_ID = None" in text
    assert "VISION_PRIMARY_UPSTREAM_MODEL = None" in text
    assert "TEXT_SECONDARY_MODEL_ID = None" in text
    assert "TEXT_FALLBACK_ENABLED = False" in text

    # SPACE_BUNNY_IN_CATALOG=NO: the retired lane is fully unregistered.
    assert get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID) is None
    assert KILO_SPACE_BUNNY_MODEL_ID in RETIRED_KILO_FREE_MODEL_IDS
    # Historical identity metadata is preserved.
    assert KILO_SPACE_BUNNY_UPSTREAM_MODEL == "stealth/space-bunny-alpha"


def test_space_bunny_manual_resolution_fails_closed() -> None:
    # SPACE_BUNNY_MANUAL_RESOLVE=FAIL_CLOSED.
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(KILO_SPACE_BUNNY_MODEL_ID)
    assert info.value.reason_code == "model_not_in_catalog"
    assert info.value.upstream_called is False


def test_space_bunny_auth_special_case_is_removed() -> None:
    # SPACE_BUNNY_AUTH_SPECIAL_CASE=REMOVED: the adapter never issues an
    # Authorization header for the retired lane, even with the historical
    # binding present in the environment.
    previous = os.environ.get(KILO_SPACE_BUNNY_CREDENTIAL_BINDING)
    try:
        os.environ[KILO_SPACE_BUNNY_CREDENTIAL_BINDING] = (
            "TEST_ONLY_NOT_A_REAL_CREDENTIAL"
        )
        spec = ps.get_platform_provider("kilo")
        assert spec is not None
        headers = plat._request_headers(spec, model_id=KILO_SPACE_BUNNY_MODEL_ID)
        assert headers == {"Content-Type": "application/json"}
        assert "Authorization" not in headers
    finally:
        if previous is None:
            os.environ.pop(KILO_SPACE_BUNNY_CREDENTIAL_BINDING, None)
        else:
            os.environ[KILO_SPACE_BUNNY_CREDENTIAL_BINDING] = previous


def test_other_provider_registrations_are_preserved_but_not_secondary() -> None:
    for model_id, provider_id in (
        ("sensenova/sensenova-6.8-flash-lite", "sensenova"),
        ("agnes-ai/agnes-3.0-flash", "agnes-ai"),
        ("poolside/laguna-s-2.1", "poolside"),
    ):
        model = get_catalog_by_id(model_id)
        assert model is not None, f"{model_id} provider registration was deleted"
        assert model.platform_provider_id == provider_id
        # None of them is the retired Space Bunny lane.
        assert model.model_id != KILO_SPACE_BUNNY_MODEL_ID

    sensenova = get_catalog_by_id("sensenova/sensenova-6.8-flash-lite")
    assert sensenova is not None
    # SenseNova stays a chat/coding lane only; it is not an active product
    # secondary and carries no image capability.
    assert "image" not in sensenova.capabilities
