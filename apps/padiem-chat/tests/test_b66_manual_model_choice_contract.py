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


class _Recording:
    """Captures what the server resolved, then stops before any dispatch."""

    def __init__(self):
        self.seen = []

    async def interpret(self, **kwargs):
        self.seen.append(kwargs)
        raise RuntimeError("stop-after-capture")


def test_grade_key_alone_is_a_complete_choice():
    recording = _Recording()
    client = _client(_Store(), recording)
    client.post("/api/b66/quote/interpret", json={
        "saved_skill_id": SAVED_ID, "message": "synthetic quote", "tier": "free",
    })
    # The grade key reached the dispatcher and the server named the model for
    # it; the browser never sent an identity of its own.
    assert len(recording.seen) == 1
    resolved = recording.seen[0]
    assert resolved["model_id"] and resolved["product_tier"] == "free"


def test_transition_model_id_is_accepted_only_when_it_matches_the_grade():
    recording = _Recording()
    _client(_Store(), recording).post("/api/b66/quote/interpret", json={
        "saved_skill_id": SAVED_ID, "message": "synthetic quote", "tier": "free",
    })
    assert recording.seen
    grade_model = recording.seen[0]["model_id"]

    accepted = _Recording()
    _client(_Store(), accepted).post("/api/b66/quote/interpret", json={
        "saved_skill_id": SAVED_ID, "message": "synthetic quote",
        "tier": "free", "model_id": grade_model,
    })
    assert len(accepted.seen) == 1 and accepted.seen[0]["model_id"] == grade_model

    refused = _client(_Store(), _Recording())
    mismatch = refused.post("/api/b66/quote/interpret", json={
        "saved_skill_id": SAVED_ID, "message": "synthetic quote",
        "tier": "free", "model_id": "test-fixture/second-ready-model",
    })
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == "invalid_model_id"


def test_quote_model_options_require_authentication_and_carry_no_model_identity():
    denied = _client(_Store(), _Interpreter(), signed_in=False)
    assert denied.get("/api/b66/quote/models").status_code == 401
    authenticated = _client(_Store(), _Interpreter())
    class TrustedOptions:
        async def list_selectable_models(self):
            return [{"model_id": MODEL, "name": "registered"}]
    authenticated.app.state.b66_quote_model_resolver = TrustedOptions()
    response = authenticated.get("/api/b66/quote/models")
    assert response.status_code == 200
    # #6828: the customer response is grade keys only. The registered catalog
    # stays server-side and still decides whether a grade is offerable, but no
    # model identity crosses to the browser and nothing is preselected for the
    # customer here.
    assert response.json() == {"ok": True, "tiers": [], "default_tier": None}
    assert "no-store" in response.headers["cache-control"].lower()
    # A host-configured model default can no longer smuggle an identity back
    # into the customer response.
    authenticated.app.state.b66_quote_default_model_id = MODEL
    after = authenticated.get("/api/b66/quote/models").json()
    assert "default_model_id" not in after and "models" not in after


def test_dual_b66_ui_sends_the_grade_key_and_no_model_identity():
    root = Path(__file__).resolve().parents[3]
    sources = [
        root / "reference/business-66-padiem-quote-v1/padiem-account.js",
        root / "apps/padiem-chat/static/b66-quote-runtime.js",
    ]
    for src in sources:
        content = src.read_text(encoding="utf-8")
        assert "ModelSelect" in content
        # #6828: the browser chooses a grade. It never stores a model identity
        # and never sends one, so there is nothing for a browser-side bug to
        # leak or for a crafted request to disagree with the chosen grade.
        assert "model_id" not in content
        assert "tier: selectedTier" in content
        assert 'select.value = ""' in content or '? configured : ""' in content
    html = (root / "reference/business-66-padiem-quote-v1/index.html").read_text(encoding="utf-8")
    assert 'id="padiemQuoteModelSelect"' in html
    worker = (root / "reference/business-66-padiem-quote-v1/_worker.js").read_text(encoding="utf-8")
    assert "/api/padiem/b66/quote/models" in worker



def test_b66_customer_dropdown_shows_grades_with_grade_models_not_provider_names():
    from app.b66_quote_routes import b66_quote_models
    from app.b66_member_admin import _TIERS
    assert _TIERS == frozenset(("FREE", "PLUS", "PRO", "MAX"))
    client = _client(_Store(), _Interpreter())
    # No member store: mock runtime resolves the max grade, so every
    # available grade row is listed.

    class GeminiOnly:
        async def list_selectable_models(self):
            return [{"model_id": "google/gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite"}]
    client.app.state.b66_quote_model_resolver = GeminiOnly()
    only_free = client.get("/api/b66/quote/models")
    assert only_free.status_code == 200
    assert [t["tier"] for t in only_free.json()["tiers"]] == ["free"]
    assert [t["name"] for t in only_free.json()["tiers"]] == ["시지아이 Free"]
    # The grade row no longer names what runs behind it; the catalog above is
    # still what decides that only this grade is offerable.
    assert all(set(t) == {"tier", "name", "reasoning_levels"}
               for t in only_free.json()["tiers"])

    class GoogleGradeModels:
        async def list_selectable_models(self):
            return [
                {"model_id": "google/gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite"},
                {"model_id": "google/gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite"},
            ]
    client.app.state.b66_quote_model_resolver = GoogleGradeModels()
    response = client.get("/api/b66/quote/models")
    assert response.status_code == 200
    data = response.json()
    assert [t["tier"] for t in data["tiers"]] == ["free", "plus", "pro", "max"]
    assert [t["name"] for t in data["tiers"]] == [
        "시지아이 Free", "시지아이 Plus", "시지아이 Pro", "시지아이 Max"]
    assert all("model_id" not in t for t in data["tiers"])
    assert set(data) == {"ok", "tiers", "default_tier"}
    assert data["default_tier"] == "free"
    root = Path(__file__).resolve().parents[3]
    for path in (root / "apps/padiem-chat/static/b66-quote-runtime.js",
                 root / "reference/business-66-padiem-quote-v1/padiem-account.js"):
        source = path.read_text(encoding="utf-8")
        assert "response.data.tiers" in source or "result.data.tiers" in source
        assert "selectedTier" in source
        assert "tier: selectedTier" in source


class _NoAdmin:
    async def is_google_admin(self, user_id):
        return False

    async def runtime_access(self, user_id):
        return {"status": "approved", "tier": "FREE"}


class _VerifiedAdmin:
    async def is_google_admin(self, user_id):
        return True

    async def runtime_access(self, user_id):
        return {"status": "approved", "tier": "MAX"}


def test_b66_admin_option_needs_central_verification_and_uses_the_shared_admin_route():
    from app.b66_grade_models import B66_ADMIN_GRADE
    ordinary = _client(_Store(), _Interpreter())
    ordinary.app.state.b66_member_admin_store = _NoAdmin()
    ordinary.app.state.b66_quote_model_resolver = _GoogleGradeModels()
    assert all(t["tier"] != B66_ADMIN_GRADE for t in ordinary.get("/api/b66/quote/models").json()["tiers"])
    denied = ordinary.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "synthetic",
              "tier": B66_ADMIN_GRADE, "model_id": "google/gemini-3.5-flash-lite"},
    )
    assert denied.status_code == 403

    admin = _client(_Store(), _Interpreter())
    admin.app.state.b66_member_admin_store = _VerifiedAdmin()
    admin.app.state.b66_quote_model_resolver = _GoogleGradeModels()
    rows = admin.get("/api/b66/quote/models").json()["tiers"]
    admin_row = next(t for t in rows if t["tier"] == B66_ADMIN_GRADE)
    assert admin_row["name"] == "Padiem 관리자"
    assert "model_id" not in admin_row

    # B66 and Chat share the same server-verified admin primary. The proof
    # stays in this file, but on the side where the identity legitimately
    # lives: the dispatcher the server resolved for this grade, never the
    # browser response.
    from app.model_policy import ADMIN_B14_MODEL_ID

    seen: list[dict] = []

    class _Recording:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            raise RuntimeError("stop-after-capture")

    dispatching = _client(_Store(), _Recording())
    dispatching.app.state.b66_member_admin_store = _VerifiedAdmin()
    dispatching.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": "synthetic",
              "tier": B66_ADMIN_GRADE},
    )
    assert seen and seen[0]["model_id"] == ADMIN_B14_MODEL_ID


class _GoogleGradeModels:
    async def list_selectable_models(self):
        return [
            {"model_id": "google/gemini-3.1-flash-lite", "name": "Gemini 3.1 Flash Lite"},
            {"model_id": "google/gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite"},
        ]


def test_b66_grade_map_tracks_the_active_product_routes():
    from app.b66_grade_models import B66_GRADE_MODEL_IDS
    from padiem_control_plane.product_tier_routes import (
        ProductTierLabel,
        active_route_for,
    )
    for tier, label in (
        ("free", ProductTierLabel.FREE),
        ("plus", ProductTierLabel.PLUS),
        ("pro", ProductTierLabel.PRO),
        ("max", ProductTierLabel.MAX),
    ):
        route = active_route_for(label)
        assert route is not None and route.model_id
        assert B66_GRADE_MODEL_IDS[tier] == route.model_id


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
