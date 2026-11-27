"""#3790: dynamic Claw model selection uses B14's already registered/ready authority."""
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from _support.claw_general_modules import server_facts as claw_general_server_facts
from _support.verified_model_choices import (
    choice_guard_facts,
    index_ids_and_scripts,
    js_view,
    server_facts,
)

from app import auth_routes
from app.owner_model_preview_routes import claw_verified_model_choices


class Catalog:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        return self.rows


def client_with(monkeypatch, authenticated=True, catalog=None):
    monkeypatch.setattr(auth_routes, "auth_ready", lambda r: authenticated)
    monkeypatch.setattr(auth_routes, "current_user_id", lambda r: "usr_fixture" if authenticated else None)
    app = Starlette(routes=[Route("/choices", claw_verified_model_choices)])
    if catalog is not None:
        app.state.b14_model_choice_resolver = catalog
    return TestClient(app)


def test_guest_cannot_read_models_or_contact_authority(monkeypatch):
    catalog = Catalog([{"model_id": "google/gemini-3.5-flash-lite", "name": "Gemini"}])
    with client_with(monkeypatch, authenticated=False, catalog=catalog) as client:
        result = client.get("/choices")
    assert result.status_code == 401
    assert result.headers["cache-control"] == "no-store"
    assert "model_choices" not in result.json()
    assert catalog.calls == 0


def test_free_member_receives_grade_readiness_without_identity(monkeypatch):
    from padiem_control_plane.product_tier_routes_private import (
        free_fallback_model_id,
        free_primary_model_id,
        paid_primary_model_id,
    )
    rows = [
        {"model_id": free_primary_model_id(), "name": "Free primary"},
        {"model_id": free_fallback_model_id(), "name": "Free fallback"},
        {"model_id": paid_primary_model_id(), "name": "Paid primary"},
    ]
    catalog = Catalog(rows)
    with client_with(monkeypatch, catalog=catalog) as client:
        first = client.get("/choices?tier=free")
        catalog.rows.append({"model_id": "other/paid", "name": "paid"})
        second = client.get("/choices?tier=free")
        refused = client.get("/choices?tier=plus")
    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert second.json()["scope"] == "b14_tier_ready"
    assert second.json()["automatic_default"] is True
    assert second.json()["tier"] == "free"
    assert second.json()["available"] is True
    assert "model_choices" not in second.json()
    assert "model_id" not in second.json()
    assert "individual_model_name" not in second.json()
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "tier_not_available"
    # #6460 4-1 second round: the read-only roster is shared for a short window,
    # so a second screen read does not pay another B14 round trip. The appended
    # row is therefore not seen until that window ends (or the switch is off).
    assert catalog.calls == 1
    monkeypatch.setenv("PADIEM_CHAT_MODEL_ROSTER_CACHE_SECONDS", "0")
    with client_with(monkeypatch, catalog=catalog) as client:
        fresh = client.get("/choices?tier=free")
    assert fresh.status_code == 200
    assert catalog.calls == 2, "switching the window off restores a live read"


def test_pro_member_gets_tier_ceiling_but_no_browser_escalation(monkeypatch):
    class VerifiedStore:
        async def runtime_access(self, user_id):
            assert user_id == "usr_fixture"
            return {"status": "approved", "tier": "pro"}
    rows = [{"model_id": "google/gemini-3.5-flash-lite", "name": "Gemini 3.5"}]
    with client_with(monkeypatch, catalog=Catalog(rows)) as client:
        client.app.state.b66_member_admin_store = VerifiedStore()
        allowed = client.get("/choices?tier=plus")
        denied = client.get("/choices?tier=max")
    assert allowed.status_code == 200
    assert allowed.json()["tier"] == "plus"
    assert allowed.json()["available"] is True
    assert "model_choices" not in allowed.json()
    assert "model_id" not in allowed.json()
    assert denied.status_code == 403



def test_missing_or_invalid_catalog_fails_closed(monkeypatch):
    with client_with(monkeypatch) as client:
        absent = client.get("/choices")
    assert absent.status_code == 503
    assert absent.json()["error"]["code"] == "model_catalog_unavailable"
    for data in (
        [{"model_id": "bad id", "name": "wrong"}],
        [{"model_id": "provider/one", "name": "one"}, {"model_id": "provider/one", "name": "two"}],
        [{"model_id": "provider/one", "name": ""}],
    ):
        with client_with(monkeypatch, catalog=Catalog(data)) as client:
            r = client.get("/choices")
        assert r.status_code == 503
        assert "model_choices" not in r.json()


def test_grade_only_choice_replaces_claw_model_selector():
    page = index_ids_and_scripts()
    assert "clawVerifiedModelSelect" not in page["ids"]
    assert "clawModelIdInput" not in page["ids"]
    assert "clawVerifiedModelHint" in page["ids"]
    assert "./claw-verified-model-choice.js" in page["scripts"]
    app = js_view("app.js")
    assert not any(
        target == "payload.model_id" and "contextSnapshot.selectedModelId" in value
        for target, value in app["assignments_full"].items()
    )
    chooser = js_view("claw-verified-model-choice.js")
    assert ("data.scope", "b14_tier_ready") in chooser["state_comparisons"]
    guard = choice_guard_facts("claw-verified-model-choice.js")
    assert guard["tier_matches_query"] is True
    assert guard["available_is_boolean"] is True
    assert any(
        "hasOwnProperty" in callee and '"model_choices"' in args
        for callee, args in chooser["call_args"]
    )
    assert "model_id" not in chooser["identifiers"] | chooser["string_literals"]


def test_login_refresh_and_logout_keep_status_without_stale_model_choice():
    js = js_view("claw-verified-model-choice.js")
    session = js_view("auth-session.js")
    #7216 R5 step 4: this contract moved into chat-auth-module.js.
    module = js_view("chat-auth-module.js")
    assert any(
        "PadiemAuthSession.update" in callee
        and args == "deps.authState, deps.authViewEpoch"
        for callee, args in module["call_args"]
    )
    assert any(
        callee == "CustomEvent" and args.startswith('"padiem:auth-state"')
        for callee, args in session["call_args"]
    )
    assert ("window", "padiem:auth-state") in js["event_listeners"]
    assert "manual.value" not in js["assignments_full"]


def test_admin_model_choices_require_server_verified_admin(monkeypatch):
    from app.model_policy import ADMIN_B14_MODEL_ID

    class AdminStore:
        def __init__(self, approved):
            self.approved = approved

        async def is_google_admin(self, user_id):
            assert user_id == "usr_fixture"
            return self.approved

    from padiem_control_plane.product_tier_routes_private import (
        free_primary_model_id,
        paid_primary_model_id,
    )
    assert ADMIN_B14_MODEL_ID == paid_primary_model_id()
    catalog = Catalog([
        {"model_id": ADMIN_B14_MODEL_ID, "name": "Admin model"},
        {"model_id": free_primary_model_id(), "name": "Free model"},
    ])
    with client_with(monkeypatch, catalog=catalog) as client:
        client.app.state.b66_member_admin_store = AdminStore(False)
        denied = client.get("/choices?tier=admin")
        assert denied.status_code == 403
        assert catalog.calls == 0

        client.app.state.b66_member_admin_store = AdminStore(True)
        approved = client.get("/choices?tier=admin")
    assert approved.status_code == 200
    assert approved.json()["tier"] == "admin"
    assert approved.json()["available"] is True
    assert "model_choices" not in approved.json()
    assert "model_id" not in approved.json()
    assert approved.json()["route_revision"] == 0


def test_claw_admin_exact_model_is_server_owned():
    routes = claw_general_server_facts()
    # #5223: the administrator lane and its denial are resolved by the ONE
    # shared grade authority, so the lane's own copy of the admin comparison
    # and the admin denial moved to that authority.  The ownership properties
    # are unchanged: the lane is still selected on the server, the admin
    # denial is still the operator admin authority, and the browser still
    # cannot pick the administrator model.
    assert ("admin_lane", "grade.admin_lane") in routes["assignments"]
    assert ("claw_execution_tier_denial", "request, user_id, grade") in routes["calls"]
    assert "declared_model_id != claw_route.model_id" in routes["comparisons"]
    assert ("claw_route", "SimpleNamespace(...)") in routes["assignments"]
    assert ("claw_route", "resolve_claw_tier_model(...)") in routes["assignments"]
    assert "admin_lane" in routes["if_conditions"]
    assert "not claw_route.ok or not claw_route.model_id" in routes["if_conditions"]

    # The shared authority is the one that still refuses a forged admin.
    shared = server_facts("member_grade_access")
    assert "grade.admin_lane" in shared["if_conditions"]
    assert ("selected_admin_denial", "request, user_id") in shared["calls"]
