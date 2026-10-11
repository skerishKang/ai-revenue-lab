"""#3790: authenticated bounded explicit customer-verified model choices."""
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from app import auth_routes
from app.owner_model_preview_routes import claw_verified_model_choices


def test_guest_cannot_get_verified_models(monkeypatch):
    monkeypatch.setattr(auth_routes,"auth_ready",lambda r:False)
    monkeypatch.setattr(auth_routes,"current_user_id",lambda r:None)
    with TestClient(Starlette(routes=[Route("/choices",claw_verified_model_choices)])) as client:
        r=client.get("/choices")
    assert r.status_code==401 and r.headers["cache-control"]=="no-store"
    assert "model_choices" not in r.json()


def test_auth_has_exact_one_proven_choice(monkeypatch):
    monkeypatch.setattr(auth_routes,"auth_ready",lambda r:True)
    monkeypatch.setattr(auth_routes,"current_user_id",lambda r:"usr_fixture")
    with TestClient(Starlette(routes=[Route("/choices",claw_verified_model_choices)])) as client:
        r=client.get("/choices")
    assert r.status_code==200 and r.headers["cache-control"]=="no-store"
    data=r.json(); rows=data["model_choices"]
    assert data["complete_inventory"] is False and data["automatic_default"] is False
    assert len(rows)==len({x["model_id"] for x in rows})==4
    assert all(x["owner_selected"] and x["product_name_prefix"]=="파디엠플러스" for x in rows)
    assert {x["model_id"] for x in rows if x["customer_selectable"]}=={"google/gemini-3.5-flash-lite"}


def test_no_default_and_advanced_exact_id_retained():
    root=Path(__file__).resolve().parents[1]/"static"
    html=(root/"index.html").read_text(encoding="utf-8")
    app=(root/"app.js").read_text(encoding="utf-8")
    chooser=(root/"claw-verified-model-choice.js").read_text(encoding="utf-8")
    assert 'id="clawVerifiedModelSelect"' in html
    assert 'id="clawModelIdInput" type="text" value=""' in html
    assert 'claw-model-advanced' in html
    assert 'claw-verified-model-choice.js' in html
    assert 'if (clawGeneralRequest && !contextSnapshot.selectedModelId)' in app
    assert 'payload.model_id = contextSnapshot.selectedModelId' in app
    assert 'opt.disabled=!row.customer_selectable' in chooser
