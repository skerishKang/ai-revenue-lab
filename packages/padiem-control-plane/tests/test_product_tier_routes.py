"""#2099 STEP-1: shared product-tier route contract tests.

Self-validation and the standard no-I/O import guard stay here. Since
#6828 3단계 the declaration carries no model or provider value, so every
value-bearing expectation runs against the placeholder fixture through the
switch-aware reader (``product_tier_routes_private``). All scans are
read-only text parsing — no cross-app runtime imports.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from padiem_control_plane.product_tier_routes import (
    MAX_HOLD_MODEL_ID,
    PLUS_HOLD_MODEL_ID,
    PRO_HOLD_MODEL_ID,
    PRODUCT_TIER_POLICY_VERSION,
    PRODUCT_TIER_ROUTES,
    RETIRED_PRODUCT_MODEL_IDS,
    ProductCredentialMode,
    ProductRouteStatus,
    ProductTierDefinition,
    ProductTierLabel,
    ProductTierRoute,
    ProductTierRoutesError,
    active_route_for,
    get_tier,
    is_free_execution_candidate,
    validate_product_tier_routes,
)
from padiem_control_plane.product_tier_routes_private import (
    effective_active_route_for,
    effective_product_tier_routes,
    free_fallback_model_id,
    free_lane_model_ids,
    free_primary_model_id,
    paid_primary_model_id,
    tier_fallback_rosters,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_PATH = PACKAGE_ROOT / "padiem_control_plane" / "product_tier_routes.py"
CHAT_MODEL_POLICY_PATH = REPO_ROOT / "apps" / "padiem-chat" / "app" / "model_policy.py"
SWITCH = "PADIEM_MODELS_REGISTRY"
FIXTURE = Path(__file__).parent / "fixtures" / "models_private_fixture.json"


@pytest.fixture(autouse=True)
def _clear_switch(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.delenv("PADIEM_MODELS_REGISTRY_OVERRIDE", raising=False)


@pytest.fixture
def private_switch(tmp_path, monkeypatch) -> dict:
    """The placeholder fixture document, installed as the private registry."""
    return _install(json.loads(FIXTURE.read_text(encoding="utf-8")), tmp_path, monkeypatch)


def _install(document: dict, tmp_path, monkeypatch) -> dict:
    target = tmp_path / "models-private.json"
    target.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(target, 0o600)
    monkeypatch.setenv(SWITCH, str(target))
    return document


def _document_with_admin() -> dict:
    """The fixture plus an administrator tier, for five-grade expectations."""
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    document["tiers"]["admin"] = {
        "primary": document["tiers"]["max"]["primary"], "fallback": []}
    return document


def _effective_executables() -> dict[ProductTierLabel, ProductTierRoute]:
    found: dict[ProductTierLabel, ProductTierRoute] = {}
    for tier in effective_product_tier_routes():
        route = effective_active_route_for(tier.label)
        if route is not None:
            found[tier.label] = route
    return found


def test_contract_defines_exactly_all_padiem_tiers() -> None:
    assert [tier.label for tier in PRODUCT_TIER_ROUTES] == list(ProductTierLabel)
    assert PRODUCT_TIER_POLICY_VERSION == "padiem.product_tier_routes.v1"


def test_the_declaration_itself_carries_no_executable_route() -> None:
    """#6828 3단계: an unswitched host fails closed — nothing to dispatch."""
    for tier in PRODUCT_TIER_ROUTES:
        assert tier.routes == ()
        assert active_route_for(tier.label) is None
    assert free_primary_model_id() == ""
    assert free_fallback_model_id() == ""
    assert paid_primary_model_id() == ""
    assert free_lane_model_ids() == ()
    assert tier_fallback_rosters() == {}


def test_admin_tier_matches_the_paid_primary_per_the_private_document(tmp_path, monkeypatch) -> None:
    document = _install(_document_with_admin(), tmp_path, monkeypatch)
    max_route = effective_active_route_for(ProductTierLabel.MAX)
    admin = effective_active_route_for(ProductTierLabel.ADMIN)
    assert max_route is not None and admin is not None
    assert admin.status is max_route.status
    assert admin.model_family == max_route.model_family
    assert admin.provider_id == max_route.provider_id
    assert admin.model_id == max_route.model_id
    assert admin.upstream_model == max_route.upstream_model
    assert admin.credential_mode is max_route.credential_mode
    assert admin.credential_binding == max_route.credential_binding
    rosters = tier_fallback_rosters()
    assert rosters["admin"] == rosters["max"]
    assert admin.model_id == document["tiers"]["admin"]["primary"]


def test_current_tiers_resolve_from_the_private_document(tmp_path, monkeypatch) -> None:
    document = _install(_document_with_admin(), tmp_path, monkeypatch)
    routes = _effective_executables()
    assert set(routes) == set(ProductTierLabel)
    free = routes[ProductTierLabel.FREE]
    assert free.model_id == document["tiers"]["free"]["primary"]
    assert free.route_id == "free.private.v1"
    assert free.provider_id == "example-provider"
    assert free.credential_binding == "PADIEM_B14_CREDENTIAL_99"
    for grade, label in (("plus", ProductTierLabel.PLUS), ("pro", ProductTierLabel.PRO),
                         ("max", ProductTierLabel.MAX), ("admin", ProductTierLabel.ADMIN)):
        assert routes[label].model_id == document["tiers"][grade]["primary"]
        assert routes[label].model_id == paid_primary_model_id()
    rosters = tier_fallback_rosters()
    assert rosters["free"] == tuple(document["tiers"]["free"]["fallback"])
    for grade in ("plus", "pro", "max"):
        tier = document["tiers"][grade]
        assert rosters[grade] == (tier["primary"], *tier["fallback"])


def test_no_user_visible_auto_or_fallback_anywhere(private_switch) -> None:
    for tiers in (PRODUCT_TIER_ROUTES, effective_product_tier_routes()):
        for tier in tiers:
            assert tier.silent_fallback_allowed is False
            for token in ("auto", "fallback"):
                assert token not in tier.label.value.lower()
                for route in tier.routes:
                    assert token not in route.route_id.lower()


def test_executable_routes_are_explicit_secret_bound_and_unretired(tmp_path, monkeypatch) -> None:
    _install(_document_with_admin(), tmp_path, monkeypatch)
    executables = _effective_executables()
    assert len(executables) == 5
    for tier, route in executables.items():
        assert route.provider_id, f"{tier.value}: explicit provider_id required"
        assert route.model_id, f"{tier.value}: explicit model_id required"
        assert route.model_id.startswith(f"{route.provider_id}/")
        assert route.model_id not in RETIRED_PRODUCT_MODEL_IDS
        assert route.evidence


def test_two_executable_routes_in_one_tier_fail_closed() -> None:
    plus = get_tier(ProductTierLabel.PLUS)
    duplicate = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=plus.routes + (
            ProductTierRoute(
                route_id="plus.duplicate-a.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="first",
                provider_id="example-provider",
                model_id="example-provider/duplicate-a",
                evidence="forbidden",
            ),
            ProductTierRoute(
                route_id="plus.duplicate-b.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="second",
                provider_id="example-provider",
                model_id="example-provider/duplicate-b",
                evidence="forbidden",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="at most one executable"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), duplicate, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )


def test_two_max_executable_routes_fail_closed() -> None:
    extra_a = ProductTierRoute(
        route_id="max.duplicate-a.v1", status=ProductRouteStatus.EXECUTABLE,
        model_family="first", provider_id="example-provider",
        model_id="example-provider/duplicate-a", evidence="synthetic",
    )
    extra_b = ProductTierRoute(
        route_id="max.duplicate-b.v1", status=ProductRouteStatus.EXECUTABLE,
        model_family="second", provider_id="example-provider",
        model_id="example-provider/duplicate-b", evidence="synthetic",
    )
    bad = ProductTierDefinition(label=ProductTierLabel.MAX, routes=(extra_a, extra_b))
    with pytest.raises(ProductTierRoutesError, match="at most one executable"):
        validate_product_tier_routes((get_tier(ProductTierLabel.FREE), get_tier(ProductTierLabel.PLUS), get_tier(ProductTierLabel.PRO), bad, get_tier(ProductTierLabel.ADMIN)))


def test_a_retired_route_entry_must_name_a_retired_model() -> None:
    """The public retired set is empty (#6828 3단계): retirement authority is
    the B14 catalog read from the private registry, so a data-only route may
    not claim a retirement the repository cannot evidence."""
    tier = ProductTierDefinition(
        label=ProductTierLabel.PRO,
        routes=(
            ProductTierRoute(
                route_id="pro.resurrect.v1",
                status=ProductRouteStatus.RETIRED_AS_DATA_ONLY,
                model_family="placeholder",
                model_id="example-provider/example-model-1",
                retired_reason="synthetic",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="retired route entries must name a retired model id"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), get_tier(ProductTierLabel.PLUS), tier, get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )


def test_silent_fallback_serving_is_inexpressible() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(),
        silent_fallback_allowed=True,
    )
    with pytest.raises(ProductTierRoutesError, match="silent fallback"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )


def test_unsupported_policy_version_fails_closed() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(),
        policy_version="padiem.product_tier_routes.v999",
    )
    with pytest.raises(ProductTierRoutesError, match="unsupported policy version"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )


def test_undocumented_non_executable_route_fails_closed() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(
            ProductTierRoute(
                route_id="plus.silent-hold.v1",
                status=ProductRouteStatus.HOLD_AS_DATA_ONLY,
                model_family="mystery",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="hold/retirement reason"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )


def test_active_tier_routes_are_enabled_rows_of_the_private_document(tmp_path, monkeypatch) -> None:
    models = {row["id"]: row for row in _install(_document_with_admin(), tmp_path, monkeypatch)["models"]}
    assert len(_effective_executables()) == 5
    for label, route in _effective_executables().items():
        assert models[route.model_id]["enabled"] is True


def test_parity_with_chat_model_policy_derivation() -> None:
    source = CHAT_MODEL_POLICY_PATH.read_text(encoding="utf-8")
    assert "from padiem_control_plane.product_tier_routes import (" in source
    assert "_CONTRACT_PLUS_HOLD_MODEL_ID" in source
    assert "LOW_B14_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "MEDIUM_B14_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "MAX_HOLD_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)" in source
    # No shipped literal may name a registered route: every id in the chat
    # policy is derived from the contract or is a synthetic hold marker.
    import ast
    import re
    literals = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    id_like = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
    suspicious = [
        lit for lit in literals
        if "/" in lit and id_like.fullmatch(lit)
        and not lit.startswith(("padiem-profile/", "padiem."))
    ]
    assert suspicious == []


def test_the_free_candidate_rule_is_deployment_scoped_and_value_free(monkeypatch) -> None:
    from padiem_control_plane.product_tier_routes_private import (
        effective_is_free_execution_candidate,
    )

    monkeypatch.setenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS", "example-provider")
    assert effective_is_free_execution_candidate("example-provider/example-model-free")
    assert not effective_is_free_execution_candidate("example-provider/example-model-1")
    assert not effective_is_free_execution_candidate("other-provider/example-model-free")
    assert not effective_is_free_execution_candidate("example-model-free")
    assert not effective_is_free_execution_candidate(None)
    assert not effective_is_free_execution_candidate("")
    monkeypatch.delenv("PADIEM_B14_FREE_CANDIDATE_PROVIDERS")
    assert not effective_is_free_execution_candidate("example-provider/example-model-free")


def test_contract_module_is_stdlib_only_and_side_effect_free() -> None:
    source = CONTRACT_PATH.read_text(encoding="utf-8")
    # Tokens are split by concatenation so this scanner never self-matches the
    # package-wide CI side-effect guard (which scans every *.py in the package).
    _i = "import "
    forbidden = (
        _i + "httpx",
        _i + "requests",
        _i + "socket",
        "urllib",
        "from app",
        _i + "app",
        "os.environ",
        "open(",
        "register_platform_provider",
        "sqlite",
        "asyncio",
        "subprocess",
        "threading",
    )
    for token in forbidden:
        assert token not in source, f"contract module must not contain {token!r}"

    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "contract must not use relative package imports"
            if node.module:
                imported.add(node.module)
    assert imported <= {"__future__", "dataclasses", "enum", "re"}, (
        f"contract imports exceed the stdlib allow-list: {imported}"
    )

    # Import already happened at this point (module-level fixtures above); if
    # importing performed file/socket/env side effects the guard scans and the
    # package-wide CI side-effect assertion cover, tests would fail loudly.
    import padiem_control_plane.product_tier_routes as contract_module
    assert contract_module.PRODUCT_TIER_POLICY_VERSION == PRODUCT_TIER_POLICY_VERSION
