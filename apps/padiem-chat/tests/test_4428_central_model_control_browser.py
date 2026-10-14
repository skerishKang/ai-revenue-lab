"""Chromium acceptance: simplified S0 UI, switches, tabs, help and no live writes."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
CATALOG = {
    "ok": True, "mode": "read_only", "write_enabled": False,
    "b14": {
        "scope": "owner_allowed_live_ready", "complete_registration_inventory": False,
        "models": [{"model_id": "google/gemini-safe", "name": "Gemini QA"},
                   {"model_id": "google/gemma-safe", "name": "Gemma QA"}],
    },
    "products": {
        "central": {"status": "not_wired"},
        "chat": {"status": "not_wired"},
        "claw": {"status": "not_wired"},
        "b14-router": {"status": "not_wired"},
        "b66": {"status": "connected", "revision": 1, "active": True,
                "tiers": {"FREE": [], "PLUS": ["google/gemini-safe"], "PRO": [], "MAX": []},
                "disabled_models": ["google/gemma-safe"]},
    },
}


def _mock(page, *, authorized=True, snapshot=None):
    seen = []

    def route_handler(route):
        path = urlparse(route.request.url).path
        if path in ("/admin-models.html", "/admin-models.js", "/admin-models.css"):
            return route.fulfill(
                status=200,
                content_type=("text/html" if path.endswith(".html")
                              else "text/css" if path.endswith(".css") else "application/javascript"),
                body=(STATIC / path.removeprefix("/")).read_text(encoding="utf-8"),
            )
        if path.startswith("/api/admin/models/"):
            seen.append({"method": route.request.method, "path": path})
            if not authorized:
                body = {"ok": False, "error": {"code": "global_model_admin_forbidden"}}
                return route.fulfill(status=403, content_type="application/json", body=json.dumps(body))
            if path == "/api/admin/models/me":
                body = {"ok": True, "admin": True, "write_enabled": False}
            elif path == "/api/admin/models/snapshot":
                body = snapshot if snapshot is not None else CATALOG
            elif path == "/api/admin/models/preview":
                data = json.loads(route.request.post_data)
                body = {"ok": True, "mode": "preview_only", "applied": False,
                        "persisted": False, "dispatch_authorized": False,
                        "model_id": data["model_id"], "targets": data["targets"]}
            else:
                raise AssertionError("unexpected model API " + path)
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        return route.fulfill(status=404)

    page.route("https://chat.test/**", route_handler)
    return seen


@pytest.mark.parametrize("width", [1440, 768, 390])
def test_compact_model_dashboard_preview_and_accessible_controls(width):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 910})
            seen = _mock(page)
            page.goto("https://chat.test/admin-models.html")
            page.get_by_role("heading", name="모델과 사용 위치").wait_for()
            page.get_by_text("미리보기 전용", exact=True).first.wait_for()
            assert page.locator("#modelCount").inner_text() == "2"
            assert page.locator("#sourceCount").inner_text() == "1 / 5 연결"
            assert page.locator(".model-item").count() == 2
            assert not page.locator("#accessNotice").is_visible()
            assert not page.locator("#previewResult").is_visible()
            assert page.get_by_text("B66 견적", exact=True).count() >= 1
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            page.locator(".model-item").first.click()
            assert page.locator("#selectedId").inner_text() == "google/gemini-safe"
            assert page.locator("#modelPlacement .placement-item").count() == 6
            assert "PLUS" in page.locator("#modelPlacement").inner_text()
            page.get_by_role("checkbox", name="중앙 정책 변경 대상").check()
            page.get_by_role("checkbox", name="Claw 변경 대상").check()
            assert page.locator("#targetCount").inner_text() == "2"
            page.locator("#tierSelect").select_option("PRO")
            page.get_by_role("radio", name="차단").check()
            assert page.get_by_role("radio", name="차단").is_checked()
            page.locator("#previewBtn").click()
            page.get_by_text("변경안 검증 완료").wait_for()
            assert "Claw · PRO · 차단" in page.locator("#previewResult").inner_text()
            assert "중앙 정책 · PRO · 차단" in page.locator("#previewResult").inner_text()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")

            page.get_by_role("button", name="모델 관리자 도움말").click()
            assert page.get_by_role("dialog").is_visible()
            page.get_by_role("button", name="도움말 닫기").click()
            assert not page.get_by_role("dialog").is_visible()

            assert [entry["method"] for entry in seen] == ["GET", "GET", "POST"]
            assert set(entry["path"] for entry in seen) <= {
                "/api/admin/models/me", "/api/admin/models/snapshot", "/api/admin/models/preview",
            }
        finally:
            browser.close()


def test_search_target_selection_invalidates_stale_preview():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 850})
            seen = _mock(page)
            page.goto("https://chat.test/admin-models.html")
            page.locator(".model-item").first.click()
            page.get_by_role("checkbox", name="B66 견적 변경 대상").check()
            page.locator("#previewBtn").click()
            page.get_by_text("변경안 검증 완료").wait_for()
            page.get_by_role("radio", name="상속").check()
            assert not page.locator("#previewResult").is_visible()
            page.locator("#modelSearch").fill("gemma")
            assert page.locator(".model-item").count() == 1
            page.locator(".model-item").first.click()
            assert "차단됨" in page.locator("#modelPlacement").inner_text()
            assert len([entry for entry in seen if entry["method"] == "POST"]) == 1
        finally:
            browser.close()


def test_non_global_user_denied_without_private_catalog_or_mutation():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 840})
            seen = _mock(page, authorized=False)
            page.goto("https://chat.test/admin-models.html")
            page.get_by_text("중앙 관리자 권한이 없습니다.").wait_for()
            assert page.locator(".model-item").count() == 0
            assert page.locator("#previewBtn").is_disabled()
            assert [entry["path"] for entry in seen] == ["/api/admin/models/me"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1440, 768, 390])
def test_glass_tone_matches_chat_palette_without_changing_admin_behavior(width):
    """Glass background/charcoal rail/soft translucent surfaces, no overflow."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 850})
            seen = _mock(page)
            page.goto("https://chat.test/admin-models.html")
            page.get_by_role("heading", name="모델과 사용 위치").wait_for()
            values = page.evaluate("""() => {
              const root = getComputedStyle(document.documentElement);
              const side = getComputedStyle(document.querySelector('.side'));
              const panel = getComputedStyle(document.querySelector('.panel'));
              const header = getComputedStyle(document.querySelector('.header'));
              return {
                glassBg: root.getPropertyValue('--bg').trim(),
                mutedAccent: root.getPropertyValue('--brand').trim(),
                side: side.backgroundImage,
                sideColor: side.backgroundColor,
                panel: panel.backgroundImage,
                backdrop: panel.backdropFilter,
                header: header.backgroundColor,
                overflow: document.documentElement.scrollWidth > innerWidth
              };
            }""")
            assert values["glassBg"] == "#aeb6bf"
            assert values["mutedAccent"] == "#2f6f99"
            if width <= 650:
                assert "rgba(43, 53, 63" in values["sideColor"]
            else:
                assert "rgba(43, 51, 60" in values["side"]
            assert "rgba(244, 247, 249" in values["panel"]
            assert "blur(" in values["backdrop"]
            assert "rgba(47, 56, 65" in values["header"]
            assert values["overflow"] is False
            assert [request["method"] for request in seen] == ["GET", "GET"]
            assert not page.locator("#previewResult").is_visible()
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1440, 768, 390])
def test_admin_brand_and_icons_match_chat_glass_without_ui_regressions(width):
    """Brand P-mark, nav, utility controls, and scope cards use consistent line icons."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 850})
            seen = _mock(page)
            page.goto("https://chat.test/admin-models.html")
            page.get_by_role("heading", name="모델과 사용 위치").wait_for()
            page.locator("#modelCount").get_attribute("id")
            assert page.locator(".brand-symbol").inner_text() == "P"
            assert page.locator(".nav-link .nav-icon svg").count() == 2
            assert page.locator(".route-icon svg").count() == 3
            assert page.locator(".target-grid .product-icon").count() == 5
            assert page.locator("#helpBtn svg, #refreshBtn svg").count() == 2
            assert page.locator('.nav-link[aria-current="page"]').count() == 1
            design = page.evaluate("""() => {
              const logo = getComputedStyle(document.querySelector('.brand-symbol'));
              const menu = getComputedStyle(document.querySelector('.nav-link'));
              const selected = getComputedStyle(document.querySelector('.nav-link.selected'));
              const productIcon = getComputedStyle(document.querySelector('.product-icon'));
              return {
                logoBorder: logo.borderTopColor,
                logoShadow: logo.boxShadow,
                selectedBorder: selected.borderTopColor,
                menuBackground: menu.backgroundColor,
                iconStroke: productIcon.strokeWidth,
                overflow: document.documentElement.scrollWidth > innerWidth,
              };
            }""")
            assert design["logoShadow"] != "none"
            assert design["logoBorder"] != "rgba(0, 0, 0, 0)"
            assert design["selectedBorder"] != "rgba(0, 0, 0, 0)"
            assert design["menuBackground"] != "rgba(0, 0, 0, 0)"
            assert design["iconStroke"] == "1.8px"
            assert design["overflow"] is False
            page.get_by_role("button", name="모델 관리자 도움말").click()
            assert page.get_by_role("dialog").is_visible()
            page.get_by_role("button", name="도움말 닫기").click()
            assert [entry["method"] for entry in seen] == ["GET", "GET"]
        finally:
            browser.close()


@pytest.mark.parametrize("width", [1440, 768, 390])
def test_full_b14_inventory_shows_off_but_never_enables_preview(width):
    """Admin may inspect OFF/owner-excluded registrations, not grant or run them."""
    import copy
    payload = copy.deepcopy(CATALOG)
    payload["b14"]["complete_registration_inventory"] = True
    payload["b14"]["registered_count_known"] = True
    payload["b14"]["registered_count"] = 4
    payload["b14"]["registered_models"] = [
        {"model_id": "google/gemini-safe", "name": "Gemini QA",
         "provider_id": "google", "b14_enabled": True, "owner_excluded": False,
         "capabilities": ["chat"]},
        {"model_id": "google/gemma-safe", "name": "Gemma QA",
         "provider_id": "google", "b14_enabled": True, "owner_excluded": False,
         "capabilities": ["chat"]},
        {"model_id": "google/off-model", "name": "off-model",
         "provider_id": "google", "b14_enabled": False, "owner_excluded": False,
         "capabilities": ["chat"]},
        {"model_id": "google/excluded", "name": "excluded",
         "provider_id": "google", "b14_enabled": True, "owner_excluded": True,
         "capabilities": ["chat"]},
    ]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            seen = _mock(page, snapshot=payload)
            page.goto("https://chat.test/admin-models.html")
            page.locator("#catalogStatus").get_by_text("ON 2").wait_for()
            assert page.locator("#modelCount").inner_text() == "4"
            assert page.locator(".model-item").count() == 4
            off = page.locator(".model-item").filter(has_text="google/off-model")
            off.click()
            assert off.locator(".model-state").inner_text() == "OFF"
            assert page.locator("#editorForm").evaluate("(el) => el.disabled") is True
            assert page.locator("#previewBtn").is_disabled()
            assert "OFF" in page.locator("#modelPlacement").inner_text()
            excluded = page.locator(".model-item").filter(has_text="google/excluded")
            excluded.click()
            assert page.locator("#editorForm").evaluate("(el) => el.disabled") is True
            assert page.locator("#previewBtn").is_disabled()
            live = page.locator(".model-item").filter(has_text="google/gemini-safe")
            live.click()
            page.get_by_role("checkbox", name="중앙 정책 변경 대상").check()
            assert page.locator("#previewBtn").is_enabled()
            page.locator("#previewBtn").click()
            page.get_by_text("변경안 검증 완료").wait_for()
            assert [call["method"] for call in seen] == ["GET", "GET", "POST"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()


def test_central_d1_rules_visible_as_stored_only_not_executing():
    import copy
    view = copy.deepcopy(CATALOG)
    view["products"]["central"] = {
        "status": "stored_only", "source": "central_model_policy_d1",
        "revision": 4, "rule_count": 1,
        "rules": [{"product": "chat", "tier": "PRO", "model_id": "google/gemini-safe",
                   "action": "allow"}],
        "runtime_enforced": False, "write_enabled": False,
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 390, "height": 850})
            seen = _mock(page, snapshot=view)
            page.goto("https://chat.test/admin-models.html")
            page.locator("#flowCentral").get_by_text("원장 연결 · 미적용").wait_for()
            page.locator("details.advanced").last.locator("summary").click()
            assert "저장 원장만 연결" in page.locator("#sourceList").inner_text()
            assert "실제 실행 미적용" in page.locator("#sourceList").inner_text()
            assert not page.locator("#previewResult").is_visible()
            assert page.get_by_text("미리보기 전용", exact=True).count() >= 1
            assert [call["method"] for call in seen] == ["GET", "GET"]
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        finally:
            browser.close()
