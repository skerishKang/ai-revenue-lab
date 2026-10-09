"""#3739: explicit B14 model selection is one per Claw P01 execution.

Network-free contracts. B14 catalog/provider resolution remains B14's authority.
No tier default, automatic fallback, provider call or Production mutation.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from kagent.p01_adapter import (
    P01AdapterError,
    P01DispatchClass,
    P01RequestFactory,
    _agent_profile,
    validate_explicit_b14_model_id,
)
from kagent.p01_run_flow import create_claw_run
from padiem_control_plane.product_tier_routes import ProductTierLabel
from padiem_control_plane import product_tier_routes

# Capture the authoritative resolver before the Chat suite autouse fixture
# replaces it with a synthetic route for unrelated tests.
ORIGINAL_ACTIVE_ROUTE_FOR = product_tier_routes.active_route_for

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
FRONT = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
GENERAL = (ROOT / "app" / "claw_general_routes.py").read_text(encoding="utf-8")
MODELS = ("agnes-ai/agnes-3.0-flash", "poolside/laguna-s-2.1")


@pytest.fixture(autouse=True)
def _preserve_real_plus_hold_for_explicit_selection(monkeypatch):
    """Undo the Chat suite's synthetic Plus route for this policy-specific file."""
    from padiem_control_plane import product_tier_routes
    import kagent.p01_adapter as adapter_module
    import app.claw_general_routes as general_module

    monkeypatch.setattr(adapter_module, "active_route_for", ORIGINAL_ACTIVE_ROUTE_FOR)
    monkeypatch.setattr(general_module, "active_route_for", ORIGINAL_ACTIVE_ROUTE_FOR)


def test_explicit_model_ids_are_used_exactly_once_and_do_not_pick_defaults():
    for model in MODELS:
        profile = _agent_profile(selected_model_id=model)
        assert profile.model_policy == {"model": model, "max_retries": 0}
        assert profile.max_steps == 1
        assert profile.allowed_tools == ()
    with pytest.raises(P01AdapterError) as error:
        _agent_profile()
    assert error.value.code == "tier_hold"


def test_factory_threads_one_exact_model_to_engine_request():
    for model in MODELS:
        run = create_claw_run("padiem-chat", "모델을 확인해 주세요")
        bundle = P01RequestFactory().build(run, selected_model_id=model)
        assert bundle.execution_request.agent.model_policy["model"] == model
        assert bundle.execution_request.agent.model_policy["max_retries"] == 0
        assert bundle.orchestration_request.execution_request.agent.model_policy["model"] == model


@pytest.mark.parametrize("value", ["", " ", "../bad", "b14/auto", "padiem-profile/plus-hold", "x;echo", None, 0, True, "x" * 130])
def test_bad_or_implicit_ids_fail_closed(value):
    with pytest.raises(P01AdapterError) as error:
        validate_explicit_b14_model_id(value)
    assert error.value.code == "invalid_selected_model"
    assert error.value.dispatch_class == P01DispatchClass.NOT_DISPATCHED


def test_explicit_model_cannot_unlock_pro_or_max():
    for tier in (ProductTierLabel.PRO, ProductTierLabel.MAX):
        with pytest.raises(P01AdapterError) as error:
            _agent_profile(tier, selected_model_id=MODELS[0])
        assert error.value.code == "explicit_model_tier_unsupported"


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


def test_claw_api_threads_explicit_id_without_default_fallback():
    for model in MODELS:
        adapter = _adapter()
        with _client(adapter) as client:
            response = client.post("/api/claw/general", json=_payload(model_id=model))
        assert response.status_code == 200
        adapter.execute.assert_awaited_once()
        kwargs = adapter.execute.await_args.kwargs
        assert kwargs["selected_model_id"] == model
        assert kwargs["subject_id"] is None


def test_claw_api_missing_model_keeps_plus_hold_before_dispatch():
    adapter = _adapter()
    with _client(adapter) as client:
        response = client.post("/api/claw/general", json=_payload())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "tier_unavailable"
    adapter.execute.assert_not_called()


@pytest.mark.parametrize("value", ["b14/auto", "padiem-profile/plus-hold", "../bad", 123])
def test_claw_api_invalid_model_fails_before_quota_or_dispatch(value):
    adapter = _adapter()
    with _client(adapter) as client:
        response = client.post("/api/claw/general", json=_payload(model_id=value))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_selected_model"
    adapter.execute.assert_not_called()


def test_claw_api_rejects_pro_hold_bypass():
    adapter = _adapter()
    with _client(adapter) as client:
        response = client.post("/api/claw/general", json=_payload(tier="pro", model_id=MODELS[0]))
    assert response.status_code == 422
    adapter.execute.assert_not_called()


def test_claw_browser_keeps_explicit_id_in_submit_snapshot_only():
    assert 'id="clawModelIdInput"' in INDEX
    assert "clawGeneralRequestActive()" in FRONT
    assert "contextSnapshot.selectedModelId" in FRONT
    assert "clawModelIdInput.value.trim()" in FRONT
    assert "payload.model_id = contextSnapshot.selectedModelId" in FRONT
    assert "if (clawGeneralRequest && contextSnapshot.selectedModelId)" in FRONT
    assert 'data.get("model_id")' in GENERAL
    assert "selected_model_id" in GENERAL
    # A Claw request with an attachment must not silently switch to direct B14.
    assert "if (clawGeneralRequest && attachments)" in FRONT
    assert "throw new Error" in FRONT
