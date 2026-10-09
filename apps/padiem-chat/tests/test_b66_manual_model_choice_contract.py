"""B66 owner-approved manual exact-model choice, no implicit auto default."""
import asyncio
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.b66_registered_model_boundary import (
    B66ModelRouteError,
    B66QuoteTaskRequirements,
)
from test_b66_b14_free_first_resolver import (
    FakeB14ReadOnlyRegistry, MODEL, PID, records,
)
from test_b66_quote_runtime import _client, _Interpreter, _Store, SAVED_ID


def test_absent_model_id_never_queries_registry_or_dispatches():
    transport = FakeB14ReadOnlyRegistry(*records())
    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(B14FreeFirstQuoteModelResolver(transport).resolve_quote_model(
            B66QuoteTaskRequirements()
        ))
    assert caught.value.code == "selection_unconfigured"
    assert transport.paths == []
    assert transport.provider_execution_calls == 0


def test_user_chosen_exact_model_wins_even_if_other_eligible_models_ready():
    registry, readiness = records()
    twin = "test-fixture/second-ready-model"
    registry["registered_routes"].append({
        "id": twin, "provider_id": PID, "free": False,
        "owner_excluded": False, "capabilities": ["chat"],
        "auto_eligible": False, "explicit_only": True,
    })
    readiness["providers"][0]["models"].append(twin)
    resolver = B14FreeFirstQuoteModelResolver(FakeB14ReadOnlyRegistry(registry, readiness))
    models = asyncio.run(resolver.list_selectable_models())
    assert {m["model_id"] for m in models} == {MODEL, twin}
    assert all("free" not in m and "credential" not in m for m in models)
    chosen = asyncio.run(resolver.resolve_quote_model(
        replace(B66QuoteTaskRequirements(), selected_model_id=twin)
    ))
    assert chosen.model_id == twin
    chosen = asyncio.run(resolver.resolve_quote_model(
        replace(B66QuoteTaskRequirements(), selected_model_id=MODEL)
    ))
    assert chosen.model_id == MODEL


def test_no_model_selected_returns_400_before_interpreter_call():
    fake = _Interpreter()
    client = _client(_Store(), fake)
    response = client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "synthetic quote"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_selection_required"
    assert fake.calls == []


def test_quote_model_options_require_authentication_and_no_store():
    denied = _client(_Store(), _Interpreter(), signed_in=False)
    assert denied.get("/api/b66/quote/models").status_code == 401
    authenticated = _client(_Store(), _Interpreter())
    class TrustedOptions:
        async def list_selectable_models(self):
            return [{"model_id": MODEL, "name": "registered"}]
    authenticated.app.state.b66_quote_model_resolver = TrustedOptions()
    response = authenticated.get("/api/b66/quote/models")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "models": [{"model_id": MODEL, "name": "registered"}],
        "default_model_id": None,
    }
    assert "no-store" in response.headers["cache-control"].lower()
    # A default is OPTIONAL and only a prefilled UI choice, not an automatic
    # backend route. An unregistered default cannot be advertised.
    authenticated.app.state.b66_quote_default_model_id = MODEL
    assert authenticated.get("/api/b66/quote/models").json()["default_model_id"] == MODEL
    authenticated.app.state.b66_quote_default_model_id = "unregistered/owner-suggestion"
    assert authenticated.get("/api/b66/quote/models").json()["default_model_id"] is None


def test_dual_b66_ui_sends_exact_user_choice_and_no_implicit_default():
    root = Path(__file__).resolve().parents[3]
    sources = [
        root / "reference/business-66-padiem-quote-v1/padiem-account.js",
        root / "apps/padiem-chat/static/b66-quote-runtime.js",
    ]
    for src in sources:
        content = src.read_text(encoding="utf-8")
        assert "ModelSelect" in content
        assert "model_id: modelId" in content
        assert 'select.value = ""' in content or '? configured : ""' in content
    html = (root / "reference/business-66-padiem-quote-v1/index.html").read_text(encoding="utf-8")
    assert 'id="padiemQuoteModelSelect"' in html
    worker = (root / "reference/business-66-padiem-quote-v1/_worker.js").read_text(encoding="utf-8")
    assert "/api/padiem/b66/quote/models" in worker


def test_b66_manual_selection_errors_have_readable_korean_messages():
    """Prevent Windows console encoding from shipping literal question marks."""
    from test_b66_quote_runtime import _client, _Interpreter, _Store, SAVED_ID
    response = _client(_Store(), _Interpreter()).post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "synthetic"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["message"] == "사용할 AI 모델을 선택해 주세요."
    denied = _client(_Store(), _Interpreter(), signed_in=False)
    response = denied.get("/api/b66/quote/models")
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "로그인이 필요합니다."
    source = (
        Path(__file__).resolve().parents[1] / "app" / "b66_quote_routes.py"
    ).read_text(encoding="utf-8")
    assert '"????' not in source
    assert '"AI ??' not in source
