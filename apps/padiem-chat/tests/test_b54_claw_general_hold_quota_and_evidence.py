"""Early (pre-adapter) model HOLD: quota and evidence contracts — #3568/#2226.

``claw_general_routes`` refuses a Claw general submit before dispatch when the
selected tier has no executable model route and the caller supplied no explicit
``model_id``. ``test_3739_claw_explicit_model_selection.py`` pins the core of
that refusal (503 ``tier_unavailable``, adapter not called). This module pins the
*side-effect* contracts of the same branch, which nothing asserted before:

- the usage gate is never evaluated, so a HOLD can never consume or reserve
  quota (#2226 fail-closed);
- no canonical P01 dispatch happens (the composed adapter is never awaited);
- no Claw run is minted before the refusal — asserted at the real call seam
  (``app.claw_general_routes.create_claw_run``), not inferred from the absence
  of evidence headers (#3754 review round 1) — so the #3655 evidence seam stays
  closed even under the one-shot marker;
- the same holds for the Max tier, not only Plus.

The branch is only reachable while the route resolver yields no executable
route, so this module installs its own module-local HOLD resolver through the
same seams ``tests/conftest.py`` already uses. That reproduces the HOLD
condition *inside the test*; it does not assert anything about the real product
policy, so the file keeps passing whichever way model registration moves
(#3754 review round 1: the former precondition pinned the live resolver to
permanent HOLD). No conftest change and no source change.

No live Engine/B14/provider call: the P01 adapter is an in-process stub and its
``execute`` is the actual dispatch boundary this file spies on. The previous
``app.state.b14_client`` mock was removed: that client is not on the Claw
general dispatch path at all, so counting its calls proved nothing.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

import app.claw_general_routes as general_routes_module
from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from padiem_control_plane import product_tier_routes

# Capture the route module's real mint entry point before any test patches it,
# so the spy can delegate (the seam stays behavioural, not just a counter).
REAL_CREATE_CLAW_RUN = general_routes_module.create_claw_run

GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "7" * 32

_EVIDENCE_HEADERS_ALL = (
    "x-padiem-claw-run-id",
    "x-padiem-orchestration-run-id",
    "x-padiem-selected-route-id",
    "x-padiem-provider-attempts",
    "x-padiem-fallback-used",
)

_HOLDABLE_TIERS = (
    product_tier_routes.ProductTierLabel.PLUS,
    product_tier_routes.ProductTierLabel.PRO,
    product_tier_routes.ProductTierLabel.MAX,
)


@pytest.fixture(autouse=True)
def module_hold_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reproduce the no-executable-route HOLD for every tier, module-locally.

    This is a test-local HOLD reproduction, not a claim about the product: the
    real resolver (and real model registration) stays untouched. The seams are
    the same ones ``tests/conftest.py`` patches — the control-plane module and
    the by-value reference ``claw_general_routes`` imported — so the route under
    test resolves through this fixture's HOLD resolver and nothing else.
    """

    def _hold_route_for(label: product_tier_routes.ProductTierLabel):
        return None

    monkeypatch.setattr(product_tier_routes, "active_route_for", _hold_route_for)
    monkeypatch.setattr(general_routes_module, "active_route_for", _hold_route_for)


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-hold-quota-client.apps.googleusercontent.com",
        google_client_secret="claw-hold-quota-google-secret",
        session_secret="claw-hold-quota-session-secret-not-real",
        session_max_age_seconds=3600,
    )


class _AuthStore:
    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


def _stub_adapter() -> MagicMock:
    """A stub that would succeed, so a HOLD proves the route refused early."""
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    adapter.execute = AsyncMock(return_value=MagicMock())
    return adapter


@contextmanager
def _client(adapter=None):
    app = create_app(
        settings=_settings(), history_store=_AuthStore(), claw_p01_adapter=adapter
    )
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _payload(**extra) -> dict:
    payload = {"messages": [{"role": "user", "content": "일반 요청입니다."}], "tier": "plus"}
    payload.update(extra)
    return payload


def test_module_hold_resolver_reproduces_no_executable_route() -> None:
    """The injected resolver itself yields no executable route for any tier."""
    for label in _HOLDABLE_TIERS:
        assert general_routes_module.active_route_for(label) is None
        assert product_tier_routes.active_route_for(label) is None


def test_hold_never_evaluates_the_usage_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A HOLD must not touch quota: the gate is ordered after the refusal (#2226)."""
    real_gate = general_routes_module._usage_gate_denial
    calls: list[object] = []

    async def _spied_gate(request):
        calls.append(request)
        return await real_gate(request)

    monkeypatch.setattr(general_routes_module, "_usage_gate_denial", _spied_gate)

    with _client(_stub_adapter()) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    assert calls == [], "the usage gate must not run on the early HOLD path"


def test_hold_mints_no_claw_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The early HOLD is proven before the route mints its Claw run (#3754 r1)."""
    calls: list[tuple[tuple, dict]] = []

    def _spied_create_claw_run(*args, **kwargs):
        calls.append((args, kwargs))
        return REAL_CREATE_CLAW_RUN(*args, **kwargs)

    monkeypatch.setattr(general_routes_module, "create_claw_run", _spied_create_claw_run)

    with _client(_stub_adapter()) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    assert calls == [], "the early HOLD must not mint a Claw run"


def test_hold_under_one_shot_evidence_still_mints_no_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The adapter branch mints a run before failing; the early branch must not."""
    calls: list[tuple[tuple, dict]] = []

    def _spied_create_claw_run(*args, **kwargs):
        calls.append((args, kwargs))
        return REAL_CREATE_CLAW_RUN(*args, **kwargs)

    monkeypatch.setattr(general_routes_module, "create_claw_run", _spied_create_claw_run)

    with _client(_stub_adapter()) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    assert calls == [], "no Claw run may be minted even in one-shot evidence mode"
    for name in _EVIDENCE_HEADERS_ALL:
        assert name not in resp.headers


def test_hold_makes_no_canonical_p01_dispatch() -> None:
    """The composed adapter is the real dispatch boundary and is never awaited."""
    adapter = _stub_adapter()
    with _client(adapter) as client:
        # The stub handed to create_app is what the route resolves at dispatch
        # time; this pins the spy to the actual seam, not a detached double.
        assert client.app.state.claw_p01_adapter is adapter
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    adapter.execute.assert_not_awaited()


def test_hold_applies_to_max_tier_as_well() -> None:
    adapter = _stub_adapter()
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload(tier="max"))

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    adapter.execute.assert_not_awaited()


def test_hold_message_is_bounded_and_exposes_no_internal_material() -> None:
    with _client(_stub_adapter()) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    text = resp.text
    for forbidden in ("tier_hold", "P01", "kagent", "Space Bunny", "space-bunny", "None"):
        assert forbidden not in text
    assert "detail" not in resp.json()["error"]
