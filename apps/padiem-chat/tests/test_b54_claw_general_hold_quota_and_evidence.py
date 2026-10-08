"""Early (pre-adapter) model HOLD: quota and evidence contracts — #3568/#2226.

``claw_general_routes`` refuses a Claw general submit before dispatch when the
selected tier has no executable model route and the caller supplied no explicit
``model_id``. ``test_3739_claw_explicit_model_selection.py`` pins the core of
that refusal (503 ``tier_unavailable``, adapter not called). This module pins the
*side-effect* contracts of the same branch, which nothing asserted before:

- the usage gate is never evaluated, so a HOLD can never consume or reserve
  quota (#2226 fail-closed);
- no Engine/B14/provider call is made;
- no Claw run is minted before the refusal, so the #3655 evidence seam stays
  closed even under the one-shot marker;
- the same holds for the Max tier, not only Plus.

The branch is only reachable while ``active_route_for()`` yields no executable
route, so this module restores the authoritative resolver for the route module,
mirroring the mechanism ``test_3739_claw_explicit_model_selection.py``
established. No conftest change and no source change.

No live Engine/B14/provider call: the P01 adapter is an in-process stub and a
B14 client spy proves no dispatch happens.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from padiem_control_plane import product_tier_routes

# Capture the authoritative resolver before the Chat suite autouse fixture
# replaces it with a synthetic route for unrelated tests.
ORIGINAL_ACTIVE_ROUTE_FOR = product_tier_routes.active_route_for

GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "7" * 32

_EVIDENCE_HEADERS_ALL = (
    "x-padiem-claw-run-id",
    "x-padiem-orchestration-run-id",
    "x-padiem-selected-route-id",
    "x-padiem-provider-attempts",
    "x-padiem-fallback-used",
)


@pytest.fixture(autouse=True)
def _preserve_the_real_route_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the Chat suite's synthetic Plus route for this hold-specific file."""
    import app.claw_general_routes as general_module

    monkeypatch.setattr(general_module, "active_route_for", ORIGINAL_ACTIVE_ROUTE_FOR)


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


def test_precondition_all_tiers_hold_with_no_executable_route() -> None:
    """Guard: this file is only meaningful while the real resolver HOLDs."""
    for label in (
        product_tier_routes.ProductTierLabel.PLUS,
        product_tier_routes.ProductTierLabel.PRO,
        product_tier_routes.ProductTierLabel.MAX,
    ):
        assert ORIGINAL_ACTIVE_ROUTE_FOR(label) is None


def test_hold_never_evaluates_the_usage_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A HOLD must not touch quota: the gate is ordered after the refusal (#2226)."""
    import app.claw_general_routes as general_module

    real_gate = general_module._usage_gate_denial
    calls: list[object] = []

    async def _spied_gate(request):
        calls.append(request)
        return await real_gate(request)

    monkeypatch.setattr(general_module, "_usage_gate_denial", _spied_gate)

    with _client(_stub_adapter()) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    assert calls == [], "the usage gate must not run on the early HOLD path"


def test_hold_makes_no_engine_or_provider_call() -> None:
    adapter = _stub_adapter()
    with _client(adapter) as client:
        b14_spy = MagicMock()
        client.app.state.b14_client = b14_spy
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    adapter.execute.assert_not_awaited()
    assert b14_spy.stream_text_auto.call_count == 0
    assert b14_spy.complete.call_count == 0


def test_hold_mints_no_claw_run_so_no_evidence_headers() -> None:
    with _client(_stub_adapter()) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())

    assert resp.status_code == 503
    for name in _EVIDENCE_HEADERS_ALL:
        assert name not in resp.headers


def test_hold_under_one_shot_evidence_still_mints_no_run_ref() -> None:
    """The adapter branch mints a run before failing; the early branch must not."""
    with _client(_stub_adapter()) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )

    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    for name in _EVIDENCE_HEADERS_ALL:
        assert name not in resp.headers


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
