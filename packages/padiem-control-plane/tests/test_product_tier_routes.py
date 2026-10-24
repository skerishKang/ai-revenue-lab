"""#2099 STEP-1: shared product-tier route contract tests.

Self-validation, birth-time parity locks against the three existing sources of
the same truth (B14 tier registry, Chat model_policy literals, B14
kilo_provider catalog/retirement), and the standard no-I/O import guard.
All scans are read-only text parsing — no cross-app runtime imports.
"""

from __future__ import annotations

import ast
import re
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
    validate_product_tier_routes,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PACKAGE_ROOT.parents[1]
CONTRACT_PATH = PACKAGE_ROOT / "padiem_control_plane" / "product_tier_routes.py"
CHAT_MODEL_POLICY_PATH = REPO_ROOT / "apps" / "padiem-chat" / "app" / "model_policy.py"
REGISTRY_PATH = REPO_ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "tier_registry_v1.py"
KILO_PROVIDER_PATH = REPO_ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "kilo_provider.py"
AGNES_PROVIDER_PATH = REPO_ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "agnes_provider.py"
BAI_PROVIDER_PATH = REPO_ROOT / "apps" / "korean-ai-platform" / "app" / "pilot" / "bai_provider.py"

def _executables() -> dict[ProductTierLabel, ProductTierRoute]:
    found: dict[ProductTierLabel, ProductTierRoute] = {}
    for tier in PRODUCT_TIER_ROUTES:
        route = active_route_for(tier.label)
        if route is not None:
            found[tier.label] = route
    return found

def test_contract_defines_exactly_all_padiem_tiers() -> None:
    assert [tier.label for tier in PRODUCT_TIER_ROUTES] == list(ProductTierLabel)
    assert PRODUCT_TIER_POLICY_VERSION == "padiem.product_tier_routes.v1"

def test_admin_tier_runs_on_opencode_go_muse_per_owner_decision_2026_10_24() -> None:
    from padiem_control_plane.product_tier_routes import TIER_FALLBACK_B14_MODELS
    max_route = active_route_for(ProductTierLabel.MAX)
    admin = active_route_for(ProductTierLabel.ADMIN)
    assert max_route is not None and admin is not None
    assert admin.route_id == "admin.muse-spark-1.3-contributor.v1"
    assert admin.status is max_route.status
    assert admin.model_family == max_route.model_family
    assert admin.provider_id == max_route.provider_id
    assert admin.model_id == max_route.model_id
    assert admin.upstream_model == max_route.upstream_model
    assert admin.credential_mode is max_route.credential_mode
    assert admin.credential_binding == max_route.credential_binding
    assert TIER_FALLBACK_B14_MODELS["admin"] == TIER_FALLBACK_B14_MODELS["max"]

def test_current_tiers_contain_only_active_models() -> None:
    from padiem_control_plane.product_tier_routes import MUSE_B14_MODEL_ID, FREE_PRIMARY_B14_MODEL_ID, TIER_FALLBACK_B14_MODELS
    routes = _executables()
    assert set(routes) == set(ProductTierLabel)
    assert routes[ProductTierLabel.FREE].model_id == FREE_PRIMARY_B14_MODEL_ID
    assert routes[ProductTierLabel.FREE].route_id == "free.gemini-3.1-flash-lite.v1"
    assert routes[ProductTierLabel.FREE].provider_id == "google"
    assert TIER_FALLBACK_B14_MODELS["free"] == ("google/gemma-4-26b-a4b-it", "google/gemini-3.5-flash-lite", "google/gemma-4-31b-it")
    for label in (ProductTierLabel.PLUS, ProductTierLabel.PRO, ProductTierLabel.MAX, ProductTierLabel.ADMIN):
        assert routes[label].model_id == MUSE_B14_MODEL_ID
    assert all(len(tier.routes) == 1 for tier in PRODUCT_TIER_ROUTES)
    assert all(r.status is ProductRouteStatus.EXECUTABLE for r in routes.values())

def test_no_user_visible_auto_or_fallback_anywhere() -> None:
    for tier in PRODUCT_TIER_ROUTES:
        assert tier.silent_fallback_allowed is False
        for token in ("auto", "fallback"):
            assert token not in tier.label.value.lower()
            for route in tier.routes:
                assert token not in route.route_id.lower()


def test_executable_routes_are_explicit_secret_bound_and_unretired() -> None:
    executables = _executables()
    assert len(executables) == 5
    for tier, route in executables.items():
        assert route.provider_id, f"{tier.value}: explicit provider_id required"
        assert route.model_id, f"{tier.value}: explicit model_id required"
        assert route.model_id.startswith(f"{route.provider_id}/")
        assert route.model_id not in RETIRED_PRODUCT_MODEL_IDS
        assert route.evidence
def test_no_historical_routes_in_current_product_tiers() -> None:
    assert all(route.status is ProductRouteStatus.EXECUTABLE for tier in PRODUCT_TIER_ROUTES for route in tier.routes)

def test_max_has_only_current_muse_route() -> None:
    assert len(get_tier(ProductTierLabel.MAX).routes) == 1

def test_two_executable_routes_in_one_tier_fail_closed() -> None:
    plus = get_tier(ProductTierLabel.PLUS)
    duplicate = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=plus.routes + (
            ProductTierRoute(
                route_id="plus.duplicate-a.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="first",
                provider_id="kilo",
                model_id="kilo/first",
                evidence="forbidden",
            ),
            ProductTierRoute(
                route_id="plus.duplicate-b.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="second",
                provider_id="kilo",
                model_id="kilo/second",
                evidence="forbidden",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="at most one executable"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.FREE), duplicate, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX), get_tier(ProductTierLabel.ADMIN))
        )

def test_two_max_executable_routes_fail_closed() -> None:
    max_tier = get_tier(ProductTierLabel.MAX)
    extra_route = ProductTierRoute(
        route_id="max.duplicate.v1", status=ProductRouteStatus.EXECUTABLE,
        model_family="test", provider_id="qwen", model_id="qwen/ready", evidence="synthetic",
    )
    bad = ProductTierDefinition(label=ProductTierLabel.MAX, routes=max_tier.routes + (extra_route,))
    with pytest.raises(ProductTierRoutesError, match="at most one executable"):
        validate_product_tier_routes((get_tier(ProductTierLabel.FREE), get_tier(ProductTierLabel.PLUS), get_tier(ProductTierLabel.PRO), bad, get_tier(ProductTierLabel.ADMIN)))

def test_retired_model_as_executable_fails_closed() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PRO,
        routes=(
            ProductTierRoute(
                route_id="pro.resurrect.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="minimax-m3",
                provider_id="kilo",
                model_id="kilo/minimax-minimax-m3-free",
                evidence="forbidden",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="retired model may never be executable"):
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


def _registry_executable_model_ids() -> dict[str, str]:
    """Parse TierRoute blocks from the B14 registry source (read-only)."""
    source = REGISTRY_PATH.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for match in re.finditer(r"TierRoute\((.*?)\n\s+\)", source, re.DOTALL):
        body = match.group(1)
        status = re.search(r"status=RouteStatus\.(\w+)", body)
        model = re.search(r'model_id="([^"]+)"', body)
        route_id = re.search(r'route_id="([^"]+)"', body)
        if status and model and route_id and status.group(1) == "EXECUTABLE":
            found[route_id.group(1)] = model.group(1)
    return found


def test_active_tier_routes_match_the_current_b14_model_registry() -> None:
    import json
    from padiem_control_plane.product_tier_routes import MUSE_B14_MODEL_ID, FREE_PRIMARY_B14_MODEL_ID
    file=REPO_ROOT/"apps"/"korean-ai-platform"/"app"/"pilot"/"b14_models.json"
    models={row["id"]: row for row in json.loads(file.read_text(encoding="utf-8"))["models"]}
    assert len(_executables())==5
    for label, route in _executables().items():
        expected = FREE_PRIMARY_B14_MODEL_ID if label is ProductTierLabel.FREE else MUSE_B14_MODEL_ID
        assert route.model_id == expected
        assert models[route.model_id]["enabled"] is True

def test_parity_with_chat_model_policy_derivation() -> None:
    source = CHAT_MODEL_POLICY_PATH.read_text(encoding="utf-8")
    assert "from padiem_control_plane.product_tier_routes import (" in source
    assert "_CONTRACT_PLUS_HOLD_MODEL_ID" in source
    assert "LOW_B14_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "MEDIUM_B14_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "MAX_HOLD_MODEL_ID = _contract_route_or_hold_id(" in source
    assert "RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)" in source
    assert '"kilo/' not in source
    assert "'kilo/" not in source

def test_selected_routes_match_current_google_and_muse_registry() -> None:
    from padiem_control_plane.product_tier_routes import MUSE_B14_MODEL_ID, FREE_PRIMARY_B14_MODEL_ID
    executables = _executables()
    assert executables[ProductTierLabel.FREE].model_id == FREE_PRIMARY_B14_MODEL_ID
    for label in (ProductTierLabel.PLUS, ProductTierLabel.PRO, ProductTierLabel.MAX):
        assert executables[label].model_id == MUSE_B14_MODEL_ID

def test_retired_kilo_models_are_never_executable() -> None:
    assert all(route.model_id not in RETIRED_PRODUCT_MODEL_IDS for route in _executables().values())

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
