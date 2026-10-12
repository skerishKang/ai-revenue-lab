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


def _mock(page, *, authorized=True):
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
                body = CATALOG
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
