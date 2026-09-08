"""Contract tests for the #2088 ACT-1 explicit tier registry.

Proves the eight ACT-1 acceptance points:
1. only "Padiem Plus" / "Padiem Pro" / "Padiem Max" labels exist
2. no user-visible "auto" label exists
3. every executable tier route has an explicit provider_id + model_id
4. no silent-fallback capability is expressible or enabled
5. Qwen/GLM for Padiem Max are HOLD_AS_DATA_ONLY, never executable
6. credential fields carry binding names only, never secret values
7. importing the registry performs no network or provider side effects
8. the existing b14/auto runtime is untouched by this contract
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.pilot.tier_registry_v1 import (
    CredentialMode,
    RouteStatus,
    SCHEMA_VERSION,
    TierDefinition,
    TierLabel,
    TierRoute,
    TierRegistryError,
    TIER_REGISTRY,
    active_route_for,
    get_tier,
    validate_tier_registry,
)
from app.pilot.catalog import get_catalog_by_id
from app.pilot.kilo_provider import RETIRED_KILO_FREE_MODEL_IDS

APP_DIR = Path(__file__).resolve().parents[1]
REGISTRY_PATH = APP_DIR / "app" / "pilot" / "tier_registry_v1.py"
CONTRACT_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "padiem-control-plane"
    / "padiem_control_plane"
    / "product_tier_routes.py"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
ACT1_BASE = "eec57fe863b9cc9038039dcc33e4ecc7b135ed30"
# #2097 re-baseline: the scope lock must pin the #2088/#2091 branch range to
# its own merge commit. Comparing against a moving HEAD made this test fail on
# every legitimate later merge to main (it was only passing in CI via the
# shallow-checkout skip).
ACT1_MERGED_INTO_MAIN = "909d0b908439bbf49da678ed8f209da8d0da658c"


def all_routes() -> list[tuple[TierLabel, TierRoute]]:
    return [(tier.label, route) for tier in TIER_REGISTRY for route in tier.routes]


def test_only_three_padiem_tier_labels() -> None:
    assert [tier.label for tier in TIER_REGISTRY] == [
        TierLabel.PLUS,
        TierLabel.PRO,
        TierLabel.MAX,
    ]
    assert {tier.label.value for tier in TIER_REGISTRY} == {
        "Padiem Plus",
        "Padiem Pro",
        "Padiem Max",
    }
    assert {label.value for label in TierLabel} == {
        "Padiem Plus",
        "Padiem Pro",
        "Padiem Max",
    }


def test_no_user_visible_auto_label() -> None:
    for tier in TIER_REGISTRY:
        value = tier.label.value.lower()
        assert "auto" not in value
        assert "fallback" not in value
    for _, route in all_routes():
        assert "auto" not in route.route_id.lower()


def test_executable_routes_have_explicit_provider_and_model() -> None:
    executables = [
        (tier, route) for tier, route in all_routes() if route.status is RouteStatus.EXECUTABLE
    ]
    assert executables, "registry must carry at least one explicit executable route"
    for tier, route in executables:
        assert route.route_id
        assert route.provider_id, f"{tier.value}: executable route lacks provider_id"
        assert route.model_id, f"{tier.value}: executable route lacks model_id"
        assert route.model_id.startswith(f"{route.provider_id}/")
        assert route.evidence

    assert active_route_for(TierLabel.PLUS) is not None
    assert active_route_for(TierLabel.PRO) is not None
    assert active_route_for(TierLabel.MAX) is None

def _contract_executable_model_ids() -> dict[str, str]:
    """Read-only scan of the shared contract's EXECUTABLE route declarations."""
    source = CONTRACT_PATH.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for match in re.finditer(r"ProductTierRoute\((.*?)\n\s+\)", source, re.DOTALL):
        body = match.group(1)
        status = re.search(r"status=ProductRouteStatus\.(\w+)", body)
        model = re.search(r'model_id="([^"]+)"', body)
        route_id = re.search(r'route_id="([^"]+)"', body)
        if status and model and route_id and status.group(1) == "EXECUTABLE":
            found[route_id.group(1)] = model.group(1)
    return found

def test_plus_pro_registry_routes_match_shared_contract() -> None:
    """#2099 STEP-2 re-target: registry ↔ contract parity (Chat ↔ contract is
    locked by apps/padiem-chat/tests/test_model_policy.py and the control-plane
    derivation guard)."""
    contract = _contract_executable_model_ids()
    assert sorted(contract) == [
        "plus.kilo-laguna-s-2.1-free.v1",
        "pro.kilo-nemotron-3-ultra-free.v1",
    ]
    assert contract["plus.kilo-laguna-s-2.1-free.v1"] == active_route_for(TierLabel.PLUS).model_id
    assert contract["pro.kilo-nemotron-3-ultra-free.v1"] == active_route_for(TierLabel.PRO).model_id

def test_executable_registry_routes_exist_in_b14_catalog() -> None:
    """#2085 ACT-1 drift guard: registry may certify only registered B14 lanes."""
    for tier, route in all_routes():
        if route.status is RouteStatus.EXECUTABLE:
            assert get_catalog_by_id(route.model_id) is not None, (
                f"{tier.value}: executable registry route {route.model_id!r} "
                "is not registered in the B14 catalog"
            )

def test_no_executable_registry_route_is_retired() -> None:
    for tier, route in all_routes():
        if route.status is RouteStatus.EXECUTABLE:
            assert route.model_id not in RETIRED_KILO_FREE_MODEL_IDS, (
                f"{tier.value}: retired lane {route.model_id!r} must never be executable"
            )

def test_retired_minimax_pro_lane_is_data_only_and_documented() -> None:
    minimax_routes = [
        route
        for _, route in all_routes()
        if route.model_id == "kilo/minimax-minimax-m3-free"
    ]
    assert minimax_routes
    for route in minimax_routes:
        assert route.status is RouteStatus.HOLD_AS_DATA_ONLY
        assert route.hold_reason and "RETIRED" in route.hold_reason
        assert "auto" not in route.route_id.lower()

def test_no_silent_fallback_anywhere() -> None:
    for tier in TIER_REGISTRY:
        assert tier.silent_fallback_allowed is False
    with pytest.raises(TierRegistryError, match="silent fallback"):
        validate_tier_registry(
            (
                TierDefinition(
                    label=TierLabel.PLUS,
                    routes=(),
                    silent_fallback_allowed=True,
                ),
                TierDefinition(label=TierLabel.PRO, routes=()),
                TierDefinition(label=TierLabel.MAX, routes=()),
            )
        )


def test_max_tier_qwen_glm_are_hold_only() -> None:
    max_routes = {route.model_family: route for route in get_tier(TierLabel.MAX).routes}
    assert {"qwen", "glm"} <= set(max_routes)
    for family in ("qwen", "glm"):
        route = max_routes[family]
        assert route.status is RouteStatus.HOLD_AS_DATA_ONLY
        assert route.hold_reason
        assert route.provider_id is None
        assert route.model_id is None
    assert active_route_for(TierLabel.MAX) is None
    with pytest.raises(TierRegistryError, match="must not expose an executable route"):
        validate_tier_registry(
            (
                get_tier(TierLabel.PLUS),
                get_tier(TierLabel.PRO),
                TierDefinition(
                    label=TierLabel.MAX,
                    routes=(
                        TierRoute(
                            route_id="max.qwen.executable.v1",
                            status=RouteStatus.EXECUTABLE,
                            model_family="qwen",
                            provider_id="qwen",
                            model_id="qwen/some-model",
                            evidence="hypothetical",
                        ),
                    ),
                ),
            )
        )


def test_credential_fields_are_binding_names_only() -> None:
    for tier, route in all_routes():
        binding = route.credential_binding
        if route.credential_mode is CredentialMode.ANONYMOUS:
            assert binding is None, f"{tier.value}/{route.route_id}: anonymous route has binding"
            continue
        assert binding is not None
        assert binding.isupper()
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*", binding)
        for marker in ("sk-", "=", "/", ":"):
            assert marker not in binding
        assert binding.startswith("PADIEM_")
    with pytest.raises(TierRegistryError, match="binding name"):
        validate_tier_registry(
            (
                TierDefinition(
                    label=TierLabel.PLUS,
                    routes=(
                        TierRoute(
                            route_id="plus.bad-secret.v1",
                            status=RouteStatus.CANDIDATE_DATA_ONLY,
                            model_family="bad",
                            credential_mode=CredentialMode.PLATFORM_SECRET_BINDING,
                            credential_binding="sk-live-abcdef123456",
                            hold_reason="negative test",
                        ),
                    ),
                ),
                get_tier(TierLabel.PRO),
                get_tier(TierLabel.MAX),
            )
        )


def test_executable_route_without_provider_fails_closed() -> None:
    with pytest.raises(TierRegistryError, match="explicit provider_id"):
        validate_tier_registry(
            (
                TierDefinition(
                    label=TierLabel.PLUS,
                    routes=(
                        TierRoute(
                            route_id="plus.no-provider.v1",
                            status=RouteStatus.EXECUTABLE,
                            model_family="ghost",
                            model_id="ghost/model",
                            evidence="negative test",
                        ),
                    ),
                ),
                get_tier(TierLabel.PRO),
                get_tier(TierLabel.MAX),
            )
        )


def test_import_performs_no_network_or_provider_side_effects() -> None:
    script = f"""
import socket
import importlib.util
import sys

class _NoNetwork(socket.socket):
    def __init__(self, *args, **kwargs):
        raise AssertionError("network access attempted during import")

socket.socket = _NoNetwork
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(
    AssertionError("network access attempted during import")
)

spec = importlib.util.spec_from_file_location("tier_registry_isolated", {str(REGISTRY_PATH)!r})
module = importlib.util.module_from_spec(spec)
sys.modules["tier_registry_isolated"] = module
spec.loader.exec_module(module)
assert module.SCHEMA_VERSION == {SCHEMA_VERSION!r}
assert len(module.TIER_REGISTRY) == 3
print("IMPORT_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout

    source = REGISTRY_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import httpx",
        "import requests",
        "import socket",
        "urllib",
        "from app",
        "import app",
        "os.environ",
        "open(",
        "register_platform_provider",
        "requests.post",
    ):
        assert forbidden not in source, f"registry module must not contain {forbidden!r}"


def test_existing_b14_auto_runtime_untouched() -> None:
    for name in ("gateway.py", "routing_policy.py", "router_core.py", "platform.py", "catalog.py"):
        source = (APP_DIR / "app" / "pilot" / name).read_text(encoding="utf-8")
        assert "tier_registry" not in source, f"{name} must not be wired to the new registry"

    for pinned in (ACT1_BASE, ACT1_MERGED_INTO_MAIN):
        probe = subprocess.run(
            ["git", "cat-file", "-e", f"{pinned}^{{commit}}"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
        if probe.returncode != 0:
            pytest.skip("ACT-1 scope-lock commits not available (shallow CI checkout)")

    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            ACT1_BASE,
            ACT1_MERGED_INTO_MAIN,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    committed = [line for line in result.stdout.splitlines() if line.strip()]
    allowed = {
        "apps/korean-ai-platform/app/pilot/tier_registry_v1.py",
        "apps/korean-ai-platform/tests/test_tier_registry_v1.py",
    }
    assert set(committed) <= allowed, f"unexpected committed changes: {committed}"
