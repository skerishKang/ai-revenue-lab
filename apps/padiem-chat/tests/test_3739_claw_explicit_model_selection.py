"""#6828: Claw's grade route is server-resolved and never client-selected.

Network-free contracts. B14 catalog/provider resolution remains B14's authority.
No client model identity, provider call or Production mutation.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from kagent.p01_adapter import P01AdapterError, P01DispatchClass, P01RequestFactory, _agent_profile, validate_explicit_b14_model_id
from kagent.p01_run_flow import create_claw_run
from padiem_control_plane.product_tier_routes import ProductTierLabel
from padiem_control_plane import product_tier_routes

# Capture the authoritative resolver before the Chat suite autouse fixture
# replaces it with a synthetic route for unrelated tests.
ORIGINAL_ACTIVE_ROUTE_FOR = product_tier_routes.active_route_for

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
FRONT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
STREAM = (ROOT / "static" / "chat-streaming-module.js").read_text(encoding="utf-8")
SETTINGS = (ROOT / "static" / "chat-settings-module.js").read_text(encoding="utf-8")
GENERAL = (ROOT / "app" / "claw_general_routes.py").read_text(encoding="utf-8")
MODELS = ("agnes-ai/agnes-3.0-flash", "poolside/laguna-s-2.1")


@pytest.fixture(autouse=True)
def _preserve_real_plus_hold_for_explicit_selection(monkeypatch):
    """Undo the Chat suite's synthetic Plus route for this policy-specific file."""
    from padiem_control_plane import product_tier_routes
    import kagent.p01_adapter as adapter_module
    import app.central_model_route_runtime as route_runtime

    monkeypatch.setattr(adapter_module, "effective_active_route_for", ORIGINAL_ACTIVE_ROUTE_FOR)
    monkeypatch.setattr(route_runtime, "effective_active_route_for", ORIGINAL_ACTIVE_ROUTE_FOR)


class _AuthStore:
    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id):
        return None


def _settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="model-explicit-test.apps.googleusercontent.com",
        google_client_secret="synthetic-not-real",
        session_secret="synthetic-secret-for-tests-only-not-real",
        session_max_age_seconds=3600,
    )


@contextmanager
def _client(adapter):
    settings = _settings()
    app = create_app(settings=settings, history_store=_AuthStore(), claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, "usr_" + "9" * 32),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _adapter():
    mock = MagicMock()
    mock.subject_identity_lane = False
    projection = MagicMock()
    projection.status.value = "completed"
    projection.run_id = "run_model_explicit"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = "선택한 모델 응답"
    outcome.p01_run_id = "p01_model_explicit"
    outcome.p01_event_count = 1
    mock.execute = AsyncMock(return_value=outcome)
    return mock


def _payload(**extra):
    payload = {"tier": "plus", "messages": [{"role": "user", "content": "안녕하세요"}]}
    payload.update(extra)
    return payload


def test_claw_api_tier_only_resolves_server_route_and_response_hides_identity(monkeypatch):
    from types import SimpleNamespace
    import app.central_model_route_runtime as runtime

    expected_route = "test-route-opaque"
    monkeypatch.setattr(runtime, "resolve_claw_tier_model", AsyncMock(return_value=SimpleNamespace(
        ok=True, model_id=expected_route, fallback_model_id=None, source="central",
    )))
    adapter = _adapter()
    with _client(adapter) as client:
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 200
    adapter.execute.assert_awaited_once()
    kwargs = adapter.execute.await_args.kwargs
    assert kwargs["central_route_model_id"] == expected_route
    assert kwargs["product_tier"] is ProductTierLabel.PLUS
    assert "selected_model_id" not in kwargs
    assert expected_route not in response.text
    assert "model_id" not in response.text


def test_claw_api_legacy_model_claim_must_match_resolved_grade(monkeypatch):
    from types import SimpleNamespace
    import app.central_model_route_runtime as runtime

    expected_route = "test-route-opaque"
    monkeypatch.setattr(runtime, "resolve_claw_tier_model", AsyncMock(return_value=SimpleNamespace(
        ok=True, model_id=expected_route, fallback_model_id=None, source="central",
    )))
    adapter = _adapter()
    with _client(adapter) as client:
        matching = client.post("/api/claw/general", json=_payload(model_id=expected_route))
        mismatch = client.post("/api/claw/general", json=_payload(model_id="different-opaque-id"))
    assert matching.status_code == 200
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "invalid_model_id"
    adapter.execute.assert_awaited_once()


def test_claw_api_server_route_unavailable_refuses_dispatch(monkeypatch):
    from types import SimpleNamespace
    import app.central_model_route_runtime as runtime

    monkeypatch.setattr(runtime, "resolve_claw_tier_model", AsyncMock(return_value=SimpleNamespace(
        ok=False, model_id=None, fallback_model_id=None, source="static",
    )))
    adapter = _adapter()
    with _client(adapter) as client:
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 503
    adapter.execute.assert_not_called()


def test_claw_browser_sends_grade_without_model_identifier():
    assert 'id="clawModelIdInput"' not in INDEX
    assert 'id="clawVerifiedModelSelect"' not in INDEX
    assert 'return ["free", "plus", "pro", "max", "admin"].includes(tier) ? tier : "free";' in SETTINGS
    assert "clawGeneralRequestActive()" in FRONT
    assert "payload.model_id = contextSnapshot.selectedModelId" not in FRONT
    assert "if (clawGeneralRequest && contextSnapshot.selectedModelId)" not in FRONT
    assert "contextSnapshot.selectedModelId = \"\"" in FRONT
    assert 'data.get("model_id")' in GENERAL
    assert '"invalid_model_id"' in GENERAL
    assert "selected_model_id" not in GENERAL
    # A Claw request with an attachment must not silently switch to direct B14.
    # #2505: the attachment now travels on the Claw lane itself, so the guard is
    # the product check on the completed-attachment path, not a refusal.
    assert "if (attachments) {" in STREAM
    assert "if (clawGeneralRequest && attachments)" not in FRONT
    assert "if (clawGeneralRequest && attachments)" not in STREAM

def test_claw_runtime_fails_closed_when_route_catalog_unavailable():
    from types import SimpleNamespace
    import app.central_model_route_runtime as runtime

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(runtime, "resolve_claw_tier_model", AsyncMock(side_effect=RuntimeError("unavailable")))
        adapter = _adapter()
        with _client(adapter) as client:
            response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 503
    adapter.execute.assert_not_called()
