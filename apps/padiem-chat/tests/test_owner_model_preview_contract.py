"""#3790 B62: read-only model inventory with no product dispatch enablement."""
from pathlib import Path

from starlette.testclient import TestClient

from app.app_factory import create_app

STATIC = Path(__file__).resolve().parents[1] / "static"
EXPECTED = {
    "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "google/gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "google/gemma-4-26b-a4b-it": "Gemma 4 26B",
    "google/gemma-4-31b-it": "Gemma 4 31B",
}


def test_readonly_model_preview_uses_canonical_owner_name_parts_no_authority():
    with TestClient(create_app()) as client:
        response = client.get("/api/models/owner-name-preview")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert payload["scope"] == "owner_confirmed_google_subset"
        assert payload["complete_inventory"] is False
        assert payload["execution_enabled"] is False
        assert set(payload) == {
            "scope", "complete_inventory", "execution_enabled", "model_names"
        }
        assert {r["model_id"]: r["individual_model_name"]
                for r in payload["model_names"]} == EXPECTED
        for row in payload["model_names"]:
            assert row == {
                "model_id": row["model_id"],
                "product_name_prefix": "파디엠플러스",
                "individual_model_name": EXPECTED[row["model_id"]],
                "owner_selected": True,
                "customer_selectable": False,
            }


def test_preview_endpoint_accepts_no_model_selection_or_mutation():
    with TestClient(create_app()) as client:
        for method in ("post", "put", "patch", "delete"):
            response = client.request(
                method.upper(), "/api/models/owner-name-preview",
                json={"model": "google/gemini-3.5-flash-lite"},
            )
            assert response.status_code == 405


def test_preview_dialog_is_accessible_readonly_and_not_in_composer_submission():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    script = (STATIC / "owner-model-preview.js").read_text(encoding="utf-8")
    assert 'id="ownerModelPreviewDialog"' in html
    assert 'aria-labelledby="ownerModelPreviewTitle"' in html
    assert 'aria-haspopup="dialog"' in html
    assert '<script src="./owner-model-preview.js"></script>' in html
    assert 'rel="stylesheet" href="./owner-model-preview.css"' in html
    assert 'owner-model-preview-scope' in html
    assert "customer_selectable === false" in script
    assert 'method: "GET"' in script
    assert 'cache: "no-store"' in script
    assert 'credentials: "same-origin"' in script
    assert "list.replaceChildren(...rows)" in script
    assert "modelIdInput.value" not in script
    assert "messageInput" not in script
    assert ".submit(" not in script
    assert "innerHTML" not in script


def test_model_preview_bilingual_copy():
    s=(STATIC/"locale.js").read_text(encoding="utf-8")
    assert s.count('"owner-model-preview-open":') == 2
    assert s.count('"owner-model-preview-no-activation":') == 2
    assert s.count('"owner-model-preview-hold":') == 2
    assert "전체 선정 목록은 아니며" in s
    assert "not the full approved inventory" in s


def test_model_preview_does_not_promote_a_synthetic_tier_or_dispatch():
    # Other B62 tests intentionally install a TEST-ONLY executable Plus route
    # by an autouse fixture. Neither fixture nor source registration grants
    # this name-preview endpoint any execution or entitlement authority.
    with TestClient(create_app()) as client:
        payload=client.get("/api/models/owner-name-preview").json()
    assert payload["execution_enabled"] is False
    assert all(not item["customer_selectable"]
               for item in payload["model_names"])
