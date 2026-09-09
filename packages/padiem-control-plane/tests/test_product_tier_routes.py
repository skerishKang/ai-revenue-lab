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

def _executables() -> dict[ProductTierLabel, ProductTierRoute]:
    found: dict[ProductTierLabel, ProductTierRoute] = {}
    for tier in PRODUCT_TIER_ROUTES:
        route = active_route_for(tier.label)
        if route is not None:
            found[tier.label] = route
    return found

def test_contract_defines_exactly_three_padiem_tiers() -> None:
    assert [tier.label for tier in PRODUCT_TIER_ROUTES] == [
        ProductTierLabel.PLUS,
        ProductTierLabel.PRO,
        ProductTierLabel.MAX,
    ]
    assert PRODUCT_TIER_POLICY_VERSION == "padiem.product_tier_routes.v1"

def test_current_truth_plus_laguna_pro_nemotron_max_hold() -> None:
    executables = _executables()
    assert executables[ProductTierLabel.PLUS].model_id == "kilo/poolside-laguna-s-2.1-free"
    assert executables[ProductTierLabel.PRO].model_id == "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    assert active_route_for(ProductTierLabel.MAX) is None

def test_no_user_visible_auto_or_fallback_anywhere() -> None:
    for tier in PRODUCT_TIER_ROUTES:
        assert tier.silent_fallback_allowed is False
        for token in ("auto", "fallback"):
            assert token not in tier.label.value.lower()
            for route in tier.routes:
                assert token not in route.route_id.lower()

def test_executable_routes_are_explicit_anonymous_and_unretired() -> None:
    for tier, route in _executables().items():
        assert route.provider_id, f"{tier.value}: explicit provider_id required"
        assert route.model_id, f"{tier.value}: explicit model_id required"
        assert route.model_id.startswith(f"{route.provider_id}/")
        assert route.model_id not in RETIRED_PRODUCT_MODEL_IDS
        assert route.evidence
        assert route.credential_mode is ProductCredentialMode.ANONYMOUS
        assert route.credential_binding is None

def test_retired_lanes_are_declared_data_only_with_reasons() -> None:
    retired = [
        route
        for tier in PRODUCT_TIER_ROUTES
        for route in tier.routes
        if route.status is ProductRouteStatus.RETIRED_AS_DATA_ONLY
    ]
    # Only lanes that were ever product-relevant are kept as historical route
    # entries (minimax backed Pro once); every retired model id is declared in
    # the frozenset and must never appear executable anywhere below.
    assert {route.model_id for route in retired} == {"kilo/minimax-minimax-m3-free"}
    assert {route.model_id for route in retired} <= set(RETIRED_PRODUCT_MODEL_IDS)
    assert all(route.retired_reason and "RETIRED" in route.retired_reason for route in retired)
    assert "kilo/tencent-hy3-free" in RETIRED_PRODUCT_MODEL_IDS

def test_max_holds_qwen_glm_on_sentinel_only() -> None:
    max_routes = get_tier(ProductTierLabel.MAX).routes
    assert {r.model_family for r in max_routes} >= {"qwen", "glm"}
    assert all(r.status is ProductRouteStatus.HOLD_AS_DATA_ONLY for r in max_routes)
    assert all(r.model_id in (None, MAX_HOLD_MODEL_ID) for r in max_routes)

def test_two_executable_routes_in_one_tier_fail_closed() -> None:
    plus = get_tier(ProductTierLabel.PLUS)
    duplicate = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=plus.routes + (
            ProductTierRoute(
                route_id="plus.duplicate.v1",
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
            (duplicate, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX))
        )

def test_max_executable_fails_closed() -> None:
    max_exec = ProductTierDefinition(
        label=ProductTierLabel.MAX,
        routes=(
            ProductTierRoute(
                route_id="max.exec.v1",
                status=ProductRouteStatus.EXECUTABLE,
                model_family="qwen",
                provider_id="qwen",
                model_id="qwen/ready",
                evidence="nope",
            ),
        ),
    )
    with pytest.raises(ProductTierRoutesError, match="must not expose an executable route"):
        validate_product_tier_routes(
            (get_tier(ProductTierLabel.PLUS), get_tier(ProductTierLabel.PRO), max_exec)
        )

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
            (get_tier(ProductTierLabel.PLUS), tier, get_tier(ProductTierLabel.MAX))
        )

def test_silent_fallback_serving_is_inexpressible() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(),
        silent_fallback_allowed=True,
    )
    with pytest.raises(ProductTierRoutesError, match="silent fallback"):
        validate_product_tier_routes(
            (tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX))
        )

def test_unsupported_policy_version_fails_closed() -> None:
    tier = ProductTierDefinition(
        label=ProductTierLabel.PLUS,
        routes=(),
        policy_version="padiem.product_tier_routes.v999",
    )
    with pytest.raises(ProductTierRoutesError, match="unsupported policy version"):
        validate_product_tier_routes(
            (tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX))
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
            (tier, get_tier(ProductTierLabel.PRO), get_tier(ProductTierLabel.MAX))
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

def test_parity_with_b14_tier_registry_active_routes() -> None:
    registry = _registry_executable_model_ids()
    assert sorted(registry) == [
        "plus.kilo-laguna-s-2.1-free.v1",
        "pro.kilo-nemotron-3-ultra-free.v1",
    ]
    executables = _executables()
    assert (
        registry["plus.kilo-laguna-s-2.1-free.v1"]
        == executables[ProductTierLabel.PLUS].model_id
    )
    assert (
        registry["pro.kilo-nemotron-3-ultra-free.v1"]
        == executables[ProductTierLabel.PRO].model_id
    )


def test_parity_with_chat_model_policy_derivation() -> None:
    """#2099 STEP-2: Chat derives tier routes from this contract.

    Locks the derivation itself and forbids literal regressions that would
    re-create the duplicated source of truth #2099 exists to remove.
    """
    source = CHAT_MODEL_POLICY_PATH.read_text(encoding="utf-8")
    assert "from padiem_control_plane.product_tier_routes import (" in source
    assert "LOW_B14_MODEL_ID = _contract_route_id(ProductTierLabel.PLUS)" in source
    assert "MEDIUM_B14_MODEL_ID = _contract_route_id(ProductTierLabel.PRO)" in source
    assert "MAX_HOLD_MODEL_ID = _CONTRACT_MAX_HOLD_MODEL_ID" in source
    assert "RETIRED_B14_MODEL_IDS = frozenset(RETIRED_PRODUCT_MODEL_IDS)" in source
    assert '"kilo/' not in source
    assert "'kilo/" not in source


def test_parity_with_b14_kilo_catalog_and_retirement() -> None:
    source = KILO_PROVIDER_PATH.read_text(encoding="utf-8")
    executables = _executables()

    laguna_constant = re.search(r'^KILO_LAGUNA_MODEL_ID = "([^"]+)"$', source, re.MULTILINE)
    nemotron_constant = re.search(
        r"^KILO_NEMOTRON_MODEL_ID = \"([^\"]+)\"$", source, re.MULTILINE
    )
    assert laguna_constant and nemotron_constant
    assert laguna_constant.group(1) == executables[ProductTierLabel.PLUS].model_id
    assert nemotron_constant.group(1) == executables[ProductTierLabel.PRO].model_id

    # Both live model IDs must still be assembled into KILO_FREE_ROUTES.
    routes_block = re.search(r"KILO_FREE_ROUTES = \((.*?)\n\)", source, re.DOTALL)
    assert routes_block, "KILO_FREE_ROUTES block not found"
    assert "model_id=KILO_LAGUNA_MODEL_ID" in routes_block.group(1)
    assert "model_id=KILO_NEMOTRON_MODEL_ID" in routes_block.group(1)
    assert "KILO_MINIMAX_M3_MODEL_ID," not in routes_block.group(1)
    assert "KILO_HY3_MODEL_ID," not in routes_block.group(1)

    retired_block = re.search(
        r"RETIRED_KILO_FREE_MODEL_IDS = frozenset\(\s*\{(.*?)\}", source, re.DOTALL
    )
    assert retired_block, "B14 retirement block not found"
    assert "KILO_MINIMAX_M3_MODEL_ID" in retired_block.group(1)
    assert "KILO_HY3_MODEL_ID" in retired_block.group(1)

    for name, model_id in (
        ("KILO_MINIMAX_M3_MODEL_ID", "kilo/minimax-minimax-m3-free"),
        ("KILO_HY3_MODEL_ID", "kilo/tencent-hy3-free"),
    ):
        constant = re.search(rf'^{name} = "([^"]+)"$', source, re.MULTILINE)
        assert constant and constant.group(1) == model_id
        assert model_id in RETIRED_PRODUCT_MODEL_IDS


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
