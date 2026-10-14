"""#3790: dynamic Claw model selection uses B14's already registered/ready authority."""
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
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


def test_model_list_tracks_b14_without_product_specific_retesting(monkeypatch):
    rows = [
        {"model_id": "google/gemini-3.5-flash-lite", "name": "gemini-3.5-flash-lite"},
        {"model_id": "sensenova/sensenova-6.8-flash-lite", "name": "sensenova-6.8-flash-lite"},
    ]
    catalog = Catalog(rows)
    with client_with(monkeypatch, catalog=catalog) as client:
        first = client.get("/choices")
        catalog.rows.append({"model_id": "new-provider/new-model", "name": "new-model"})
        second = client.get("/choices")
    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert second.json()["scope"] == "b14_owner_allowed_live_ready"
    assert second.json()["automatic_default"] is False
    assert [x["model_id"] for x in first.json()["model_choices"]] == [x["model_id"] for x in rows[:2]]
    assert [x["model_id"] for x in second.json()["model_choices"]] == [x["model_id"] for x in rows]
    assert all(x["customer_selectable"] is True for x in second.json()["model_choices"])
    assert catalog.calls == 2


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


def test_no_default_and_advanced_exact_id_retained():
    root = Path(__file__).resolve().parents[1] / "static"
    html = (root / "index.html").read_text(encoding="utf-8")
    app = (root / "app.js").read_text(encoding="utf-8")
    chooser = (root / "claw-verified-model-choice.js").read_text(encoding="utf-8")
    assert 'id="clawVerifiedModelSelect"' in html
    assert 'id="clawModelIdInput" type="text" value=""' in html
    assert 'claw-model-advanced' in html
    assert 'claw-verified-model-choice.js' in html
    assert 'if (clawGeneralRequest && selectedProductTier() === "plus" && !contextSnapshot.selectedModelId)' in app
    assert 'payload.model_id = contextSnapshot.selectedModelId' in app
    assert 'scope==="b14_owner_allowed_live_ready"' in chooser
    assert 'const IDS=' not in chooser and 'const PROVEN=' not in chooser


def test_login_refresh_and_logout_clear_stale_model_choice():
    base = Path(__file__).resolve().parents[1] / "static"
    app = (base / "app.js").read_text(encoding="utf-8")
    js = (base / "claw-verified-model-choice.js").read_text(encoding="utf-8")
    assert 'new CustomEvent("padiem:auth-state"' in app
    assert 'window.addEventListener("padiem:auth-state"' in js
    assert 'manual.value=""; // session revoked' in js
