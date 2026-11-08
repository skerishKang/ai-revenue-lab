"""#6828 2-2 — the control plane reads the same private tiers as B14.

The declaration module stays pure; this reader is the switch-aware one. With the
switch off the declaration answers, with it on the private document answers, and
an unusable document declares no executable route.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from padiem_control_plane.product_tier_routes import (
    PRODUCT_TIER_ROUTES,
    ProductTierLabel,
)
from padiem_control_plane.product_tier_routes_private import (
    effective_active_route_for,
    effective_product_tier_routes,
)

SWITCH = "PADIEM_MODELS_REGISTRY"
FIXTURE = Path(__file__).parent / "fixtures" / "models_private_fixture.json"


@pytest.fixture(autouse=True)
def _clear_switch(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv("PADIEM_MODELS_REGISTRY_OVERRIDE", raising=False)


def _private(tmp_path: Path) -> Path:
    target = tmp_path / "models-private.json"
    shutil.copyfile(FIXTURE, target)
    os.chmod(target, 0o600)
    return target


def test_switch_off_answers_the_pure_declaration():
    assert effective_product_tier_routes() is PRODUCT_TIER_ROUTES
    declared = next(tier for tier in PRODUCT_TIER_ROUTES
                    if tier.label is ProductTierLabel.PLUS)
    executable = next(route for route in declared.routes
                      if route.status.value == "executable")
    assert effective_active_route_for(ProductTierLabel.PLUS).model_id == executable.model_id


def test_switch_on_uses_the_private_tiers(tmp_path, monkeypatch):
    monkeypatch.setenv(SWITCH, str(_private(tmp_path)))
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    route = effective_active_route_for(ProductTierLabel.PLUS)

    assert route is not None
    assert route.route_id == "plus.private.v1"
    assert route.model_id == document["tiers"]["plus"]["primary"]
    assert route.provider_id == "example-provider"
    assert route.credential_binding == "PADIEM_B14_CREDENTIAL_99"
    free = effective_active_route_for(ProductTierLabel.FREE)
    assert free.model_id == document["tiers"]["free"]["primary"]
    # A grade the document does not name stays declared without a route.
    assert effective_active_route_for(ProductTierLabel.ADMIN) is None


def test_switch_on_without_a_usable_document_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv(SWITCH, str(tmp_path / "absent.json"))

    assert effective_product_tier_routes() == tuple(
        tier for tier in effective_product_tier_routes())
    assert all(not tier.routes for tier in effective_product_tier_routes())
    assert effective_active_route_for(ProductTierLabel.FREE) is None
    assert effective_active_route_for(ProductTierLabel.PRO) is None


def test_switch_on_with_an_invalid_document_is_fail_closed(tmp_path, monkeypatch):
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["version"] = "padiem.models.private.v2"
    target = tmp_path / "models-private.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(target, 0o600)
    monkeypatch.setenv(SWITCH, str(target))

    assert effective_active_route_for(ProductTierLabel.MAX) is None
