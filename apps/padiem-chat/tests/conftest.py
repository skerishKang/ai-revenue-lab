from __future__ import annotations

import importlib
from pathlib import Path

import httpx
import pytest
from starlette import testclient as starlette_testclient

import app.model_policy as model_policy_module
from app.same_origin_guard import MUTATING_METHODS, expected_browser_origin
from padiem_control_plane import product_tier_routes as tier_routes

# A real same-origin browser always attaches Origin to a mutation, so an ASGI
# test client that omits it is not representing the traffic #3476 guards. The
# marker lets a test assert the missing-Origin case on purpose.
NO_BROWSER_ORIGIN_MARKER = "x-test-no-origin"


def _attach_reviewed_browser_origin(app: object, request: httpx.Request) -> None:
    if str(request.method).upper() not in MUTATING_METHODS:
        return
    if NO_BROWSER_ORIGIN_MARKER in request.headers:
        del request.headers[NO_BROWSER_ORIGIN_MARKER]
        return
    if request.headers.get("origin") is not None:
        return
    expected = expected_browser_origin(getattr(getattr(app, "state", None), "settings", None))
    if expected is not None:
        request.headers["origin"] = expected


@pytest.fixture(autouse=True)
def _simulate_same_origin_browser_mutations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ASGI test transport behave like a same-origin browser.

    Without this, #3476's Origin rule would be asserted only by
    ``test_3476_same_origin_guard.py`` and every unrelated cookie-authenticated
    mutation test would fail as a false positive. The expectation is read from
    the app under test, never hardcoded, so a test can never inject an Origin
    its own configuration would deny.
    """

    asgi_handle = httpx.ASGITransport.handle_async_request

    async def _asgi_handle(self: httpx.ASGITransport, request: httpx.Request):
        _attach_reviewed_browser_origin(self.app, request)
        return await asgi_handle(self, request)

    sync_handle = starlette_testclient._TestClientTransport.handle_request

    def _sync_handle(self: object, request: httpx.Request):
        _attach_reviewed_browser_origin(self.app, request)
        return sync_handle(self, request)

    monkeypatch.setattr(httpx.ASGITransport, "handle_async_request", _asgi_handle)
    monkeypatch.setattr(
        starlette_testclient._TestClientTransport,
        "handle_request",
        _sync_handle,
    )


_HOLD_POLICY_MODULES = {
    "test_attachments.py",
    "test_auth_history.py",
    "test_model_policy.py",
    "test_plus_space_bunny_image.py",
    "test_saved_outputs.py",
    "test_tier_route_consumer_coverage.py",
    "test_unassigned_profile_gate.py",
}


@pytest.fixture(autouse=True)
def _synthetic_plus_route_for_non_policy_contracts(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unrelated regressions independent from successor-model selection.

    Production source remains fail-closed with no executable Plus route. Tests whose
    purpose is to verify that HOLD state are excluded above. Every other Chat test
    gets one synthetic Plus route so it can keep testing its own contract.
    """

    module_name = Path(str(request.fspath)).name
    if module_name in _HOLD_POLICY_MODULES:
        return

    model_id = model_policy_module.DEFAULT_B14_MODEL_ID
    executable = frozenset({model_id})
    synthetic_route = tier_routes.ProductTierRoute(
        route_id="test.plus.synthetic.v1",
        status=tier_routes.ProductRouteStatus.EXECUTABLE,
        model_family="test",
        provider_id="test",
        model_id=model_id,
        evidence="test-only synthetic Plus route",
    )

    def _active_route_for(label: tier_routes.ProductTierLabel):
        if label is tier_routes.ProductTierLabel.PLUS:
            return synthetic_route
        return None

    monkeypatch.setattr(
        model_policy_module,
        "EXECUTABLE_B14_MODEL_IDS",
        executable,
    )
    monkeypatch.setattr(tier_routes, "active_route_for", _active_route_for)

    # Runtime modules imported the route resolver by value, so patch those local
    # references too. Missing optional modules are harmless for unrelated tests.
    for module_name_to_patch in (
        "app.model_policy",
        "app.claw_routes",
        "app.claw_general_routes",
        "kagent.p01_adapter",
        "kagent.p01_orchestration_client",
    ):
        try:
            module_to_patch = importlib.import_module(module_name_to_patch)
        except ImportError:
            continue
        if hasattr(module_to_patch, "active_route_for"):
            monkeypatch.setattr(
                module_to_patch,
                "active_route_for",
                _active_route_for,
            )

    for module_name_to_patch in (
        "kagent.p01_orchestration_client",
        "kagent.p01_approval_continuation",
    ):
        try:
            module_to_patch = importlib.import_module(module_name_to_patch)
        except ImportError:
            continue
        if hasattr(module_to_patch, "PADIEM_EXECUTABLE_MODEL_IDS"):
            monkeypatch.setattr(
                module_to_patch,
                "PADIEM_EXECUTABLE_MODEL_IDS",
                executable,
            )

    # A few tests imported immutable policy sets directly at module load time.
    module = request.module
    if hasattr(module, "EXECUTABLE_B14_MODEL_IDS"):
        monkeypatch.setattr(
            module,
            "EXECUTABLE_B14_MODEL_IDS",
            executable,
            raising=False,
        )
    if hasattr(module, "PADIEM_EXECUTABLE_MODEL_IDS"):
        monkeypatch.setattr(
            module,
            "PADIEM_EXECUTABLE_MODEL_IDS",
            executable,
            raising=False,
        )
