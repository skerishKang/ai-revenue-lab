"""#3566/#3523 model-unavailable HOLD UX for the Claw general composer.

While a selected tier has no executable model route (#3568), a general Claw
submit is refused by the P01 adapter before any Engine/B14/provider dispatch
(``tier_hold`` / ``max_tier_hold``, ``NOT_DISPATCHED``). That is a product
state, not an engine failure, so the browser must never see a generic
``502 engine_execution_failed`` for it.

Contract pinned here:

- ``tier_hold`` / ``max_tier_hold`` project as the same fail-closed family the
  other tiers already use for a pre-dispatch refusal: ``503 tier_unavailable``
  with a user-facing HOLD message;
- the quota reservation is refunded (NOT_DISPATCHED, #2226), never consumed;
- no Engine/B14/provider call is made;
- non-HOLD engine failures keep the existing 502 projection unchanged.

No live Engine/provider call is made: the adapter is injected as a stub.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from kagent.p01_adapter import P01AdapterError, P01DispatchClass

APP_DIR = Path(__file__).resolve().parents[1]
GENERAL_ROUTE_SOURCE = (APP_DIR / "app" / "claw_general_routes.py").read_text(encoding="utf-8")

GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "8" * 32


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="claw-hold-client.apps.googleusercontent.com",
        google_client_secret="claw-hold-google-secret",
        session_secret="claw-hold-session-secret-not-a-real-credential",
        session_max_age_seconds=3600,
    )


class _AuthStore:
    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str):
        return None


def _make_outcome(*, answer: str | None = "P01 결과"):
    status_mock = MagicMock()
    status_mock.value = "completed"
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_general"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_general"
    outcome.p01_event_count = 1
    return outcome


def _make_adapter(*, outcome=None, execute_error: Exception | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    if execute_error is not None:
        adapter.execute = AsyncMock(side_effect=execute_error)
    else:
        adapter.execute = AsyncMock(return_value=outcome or _make_outcome())
    return adapter


@contextmanager
def _client(adapter=None):
    app = create_app(settings=_settings(), history_store=_AuthStore(), claw_p01_adapter=adapter)
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


def _force_executable_route_for_max(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let tier="max" reach adapter.execute instead of the route's own
    early tier_unavailable refusal, so the adapter-level max_tier_hold
    HOLD branch is what the tests actually exercise."""
    import app.claw_general_routes as claw_general_routes
    import app.model_policy as model_policy_module
    from padiem_control_plane import product_tier_routes as tier_routes

    synthetic = tier_routes.ProductTierRoute(
        route_id="test.max.synthetic.v1",
        status=tier_routes.ProductRouteStatus.EXECUTABLE,
        model_family="test",
        provider_id="test",
        model_id=model_policy_module.DEFAULT_B14_MODEL_ID,
        evidence="test-only synthetic Max route",
    )
    monkeypatch.setattr(
        claw_general_routes, "active_route_for", lambda label: synthetic
    )


def _hold_error(code: str) -> P01AdapterError:
    return P01AdapterError(
        code,
        "선택한 등급은 현재 실행 가능한 모델 경로가 없습니다 (HOLD).",
        dispatch_class=P01DispatchClass.NOT_DISPATCHED,
    )


# ── HOLD projects as a bounded product state, never a generic 502 ───────────


def test_plus_tier_hold_projects_as_tier_unavailable_503() -> None:
    adapter = _make_adapter(execute_error=_hold_error("tier_hold"))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 503
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "tier_unavailable"
    # User-facing model-unavailable message, not a generic failure.
    assert "모델" in body["error"]["message"]
    # The closed failure vocabulary must not leak an "unknown" engine detail.
    assert "detail" not in body["error"]
    adapter.execute.assert_awaited_once()


def test_max_tier_hold_from_adapter_also_projects_as_tier_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_executable_route_for_max(monkeypatch)
    adapter = _make_adapter(execute_error=_hold_error("max_tier_hold"))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload(tier="max"))
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"]["code"] == "tier_unavailable"
    assert "detail" not in body["error"]
    adapter.execute.assert_awaited_once()


def test_hold_response_message_is_bounded_and_exposes_no_internal_material() -> None:
    adapter = _make_adapter(execute_error=_hold_error("tier_hold"))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    text = resp.text
    # No adapter internals, no model/provider identifiers, no stack hints.
    for forbidden in ("tier_hold", "P01", "kagent", "Space Bunny", "space-bunny", "None"):
        assert forbidden not in text


# ── #3662/#3655 evidence seam on the HOLD projection ─────────────────────────

_EVIDENCE_HEADERS_ALL = (
    "x-padiem-claw-run-id",
    "x-padiem-orchestration-run-id",
    "x-padiem-selected-route-id",
    "x-padiem-provider-attempts",
    "x-padiem-fallback-used",
)


def test_normal_tier_hold_projects_no_evidence_headers() -> None:
    adapter = _make_adapter(execute_error=_hold_error("tier_hold"))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    for name in _EVIDENCE_HEADERS_ALL:
        assert name not in resp.headers


def test_oneshot_tier_hold_carries_only_valid_claw_run_ref() -> None:
    adapter = _make_adapter(execute_error=_hold_error("tier_hold"))
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    run_ref = resp.headers["x-padiem-claw-run-id"]
    assert re.fullmatch(r"run_[0-9a-f]{24}", run_ref) is not None
    assert "x-padiem-orchestration-run-id" not in resp.headers
    assert "x-padiem-selected-route-id" not in resp.headers
    assert "x-padiem-provider-attempts" not in resp.headers
    assert "x-padiem-fallback-used" not in resp.headers


def test_oneshot_max_tier_hold_carries_only_valid_claw_run_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_executable_route_for_max(monkeypatch)
    adapter = _make_adapter(execute_error=_hold_error("max_tier_hold"))
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(tier="max"),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    run_ref = resp.headers["x-padiem-claw-run-id"]
    assert re.fullmatch(r"run_[0-9a-f]{24}", run_ref) is not None
    assert "x-padiem-orchestration-run-id" not in resp.headers
    assert "x-padiem-selected-route-id" not in resp.headers
    assert "x-padiem-provider-attempts" not in resp.headers
    assert "x-padiem-fallback-used" not in resp.headers


def test_normal_max_tier_hold_projects_no_evidence_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _force_executable_route_for_max(monkeypatch)
    adapter = _make_adapter(execute_error=_hold_error("max_tier_hold"))
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload(tier="max"))
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "tier_unavailable"
    for name in _EVIDENCE_HEADERS_ALL:
        assert name not in resp.headers


def test_non_hold_adapter_error_keeps_existing_502_evidence_seam() -> None:
    adapter = _make_adapter()
    adapter.execute = AsyncMock(
        side_effect=P01AdapterError(
            "p01_execution_failed",
            "safe failure",
            dispatch_class=P01DispatchClass.DISPATCHED,
        )
    )
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "engine_execution_failed"
    assert resp.headers["x-padiem-claw-run-id"].startswith("run_")
    assert "x-padiem-orchestration-run-id" not in resp.headers


def test_successful_sse_run_keeps_existing_evidence_headers() -> None:
    outcome = _make_outcome()
    outcome.p01_run_id = "orch_hold_ok"
    outcome.selected_route_id = "plus.route.v1"
    outcome.provider_attempt_count = 1
    outcome.fallback_used = False
    adapter = _make_adapter(outcome=outcome)
    with _client(adapter) as client:
        resp = client.post(
            GENERAL_ROUTE_PATH,
            json=_payload(),
            headers={"X-Padiem-Claw-Evidence": "one-shot"},
        )
    assert resp.status_code == 200
    assert resp.headers["x-padiem-claw-run-id"].startswith("run_")
    assert resp.headers["x-padiem-orchestration-run-id"] == "orch_hold_ok"
    assert resp.headers["x-padiem-selected-route-id"] == "plus.route.v1"
    assert resp.headers["x-padiem-provider-attempts"] == "1"
    assert resp.headers["x-padiem-fallback-used"] == "false"


# ── quota contract: a HOLDed run is refunded, never consumed ────────────────


def test_hold_refunds_reservation_and_does_not_dispatch_engine() -> None:
    adapter = _make_adapter(execute_error=_hold_error("tier_hold"))
    with _client(adapter) as client:
        b14_spy = MagicMock()
        client.app.state.b14_client = b14_spy
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 503
    adapter.execute.assert_awaited_once()  # adapter was reached (it refused)
    # No direct-B14 fallback of any kind.
    assert b14_spy.stream_text_auto.call_count == 0
    assert b14_spy.complete.call_count == 0


# ── non-HOLD engine failures keep the existing 502 projection ────────────────


def test_non_hold_engine_failure_keeps_generic_502_projection() -> None:
    adapter = _make_adapter(
        execute_error=P01AdapterError(
            "p01_execution_failed",
            "safe failure",
            dispatch_class=P01DispatchClass.DISPATCHED,
        )
    )
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"]["code"] == "engine_execution_failed"


def test_successful_run_still_streams_terminal_sse() -> None:
    adapter = _make_adapter()
    with _client(adapter) as client:
        resp = client.post(GENERAL_ROUTE_PATH, json=_payload())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in resp.text
    assert "event: done" in resp.text


# ── source-level pin: the HOLD projection lives in the route, not the UI ────


def test_route_declares_model_hold_normalization() -> None:
    assert "_MODEL_HOLD_ERROR_CODES" in GENERAL_ROUTE_SOURCE
    assert '"tier_hold"' in GENERAL_ROUTE_SOURCE
    assert '"max_tier_hold"' in GENERAL_ROUTE_SOURCE
    assert "_MODEL_HOLD_USER_MESSAGE" in GENERAL_ROUTE_SOURCE
