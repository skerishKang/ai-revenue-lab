"""#6828: the public model-name preview is gone; only grades reach the browser.

The removed surface had no owner decision behind it: an unauthenticated GET
answered with model identities, and a browser asset carried the same list. This
spec pins the ABSENCE of every one of those paths, and pins the two things that
were deliberately kept — the composer layout rules,
and the authenticated Claw chooser another lane is converting to grade choices.
"""
from pathlib import Path

from starlette.testclient import TestClient

from app.app_factory import create_app

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = Path(__file__).resolve().parents[1] / "app"
PREVIEW_PATH = "/api/models/owner-name-preview"
REMOVED_ASSET = STATIC / "owner-model-preview.js"
LAYOUT_CSS = STATIC / "attachments.css"


def test_public_model_name_preview_route_is_not_registered():
    with TestClient(create_app()) as client:
        # The removed surface answered GET with identities; GET must now be
        # unmatched, and no verb may hand back the old payload shape.
        assert client.get(PREVIEW_PATH).status_code == 404
        for method in ("post", "put", "patch", "delete"):
            response = client.request(method.upper(), PREVIEW_PATH, json={})
            assert response.status_code in (404, 405), (method, response.status_code)
            assert "model_names" not in response.text


def test_preview_handler_and_registration_are_gone_from_the_source():
    app_source = (APP / "app_factory.py").read_text(encoding="utf-8")
    routes_source = (APP / "owner_model_preview_routes.py").read_text(encoding="utf-8")
    assert PREVIEW_PATH not in app_source
    assert "owner_model_name_preview" not in app_source
    assert "owner_model_name_preview" not in routes_source


def test_removed_browser_asset_is_absent_and_no_longer_referenced():
    assert not REMOVED_ASSET.exists(), REMOVED_ASSET
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "owner-model-preview.js" not in html
    for identifier in (
        "ownerModelPreviewDialog",
        "ownerModelPreviewTitle",
        "ownerModelPreviewScope",
        "ownerModelPreviewStatus",
        "ownerModelPreviewList",
        "ownerModelPreviewClose",
        "ownerModelPreviewOpen",
    ):
        assert identifier not in html, identifier
    for js in STATIC.glob("*.js"):
        assert "owner-model-preview.js" not in js.read_text(encoding="utf-8"), js.name


def test_preview_copy_is_gone_from_every_locale():
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert "owner-model-preview" not in locale
    assert "모델 현황" not in locale
    assert "model status" not in locale


def test_layout_sheet_is_kept_because_composer_reservations_live_there():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = LAYOUT_CSS.read_text(encoding="utf-8")
    assert 'owner-model-preview.css' not in html
    assert not (STATIC / "owner-model-preview.css").exists()
    assert "width: 116px" in css
    assert ".send-button { flex: 0 0 44px;" in css


def test_authenticated_claw_chooser_is_untouched_by_the_removal():
    # Another lane converts this picker to grade choices; until then it must
    # stay authenticated, so removing the public preview cannot widen it.
    with TestClient(create_app()) as client:
        response = client.get("/api/claw/verified-model-choices")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "authentication_required"


def test_grade_pill_remains_the_only_model_choice_surface_in_the_composer():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    mode = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert 'class="model-pill composer-tier-trigger" type="button"' in html
    assert 'id="ownerModelPreviewOpen"' not in html
    assert html.count('class="model-pill composer-tier-trigger"') == 1
    assert 'const modePill = document.querySelector(".model-pill")' in mode
    assert '[".model-pill span:last-child", "mode"]' not in locale
    assert '[".model-pill", "aria-label", "tier"]' in locale


def test_grade_pill_stays_in_the_mobile_composer_tools_row():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="ownerModelPreviewOpen"' not in html
    tools_start = html.index('class="composer-tools"')
    tools_end = html.index('id="sendButton"', tools_start)
    pill = html.index('class="model-pill composer-tier-trigger"')
    assert tools_start < pill < tools_end
    assert 'id="messageInput"' in html
