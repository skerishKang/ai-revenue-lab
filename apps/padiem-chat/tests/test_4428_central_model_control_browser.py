"""Focused Chromium acceptance for the central model manager S0 (fake trusted APIs)."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")

STATIC = Path(__file__).resolve().parents[1] / "static"
CATALOG = {
    "ok": True, "mode": "read_only",
    "write_enabled": False,
    "b14": {
        "scope": "owner_allowed_live_ready",
        "complete_registration_inventory": False,
        "models": [
            {"model_id": "google/gemini-safe", "name": "Gemini QA"},
            {"model_id": "google/gemma-safe", "name": "Gemma QA"},
        ],
    },
    "products": {
        "central": {"status": "not_wired"},
        "chat": {"status": "not_wired"},
        "claw": {"status": "not_wired"},
        "b14-router": {"status": "not_wired"},
        "b66": {
            "status": "connected", "revision": 1, "active": True,
            "tiers": {"FREE": [], "PLUS": [], "PRO": [], "MAX": []},
            "disabled_models": [],
        },
    },
}


def _install_mock(page, *, authorized=True):
    seen = []

    def respond(route):
        path = urlparse(route.request.url).path
        if path == "/admin-models.html":
            return route.fulfill(
                status=200, content_type="text/html",
                body=(STATIC / "admin-models.html").read_text(encoding="utf-8"),
            )
        if path == "/admin-models.js":
            return route.fulfill(
                status=200, content_type="application/javascript",
                body=(STATIC / "admin-models.js").read_text(encoding="utf-8"),
            )
        if path == "/admin-models.css":
            return route.fulfill(
                status=200, content_type="text/css",
                body=(STATIC / "admin-models.css").read_text(encoding="utf-8"),
            )
        if path.startswith("/api/admin/models/"):
            seen.append({"method": route.request.method, "path": path})
            if not authorized:
                return route.fulfill(
                    status=403, content_type="application/json",
                    body=json.dumps({"ok": False, "error": {"code": "global_model_admin_forbidden"}}),
                )
            if path == "/api/admin/models/me":
                data = {"ok": True, "admin": True, "write_enabled": False}
            elif path == "/api/admin/models/snapshot":
                data = CATALOG
            elif path == "/api/admin/models/preview":
                payload = json.loads(route.request.post_data)
                data = {
                    "ok": True, "mode": "preview_only", "applied": False,
                    "persisted": False, "model_id": payload["model_id"],
                    "targets": payload["targets"],
                }
            else:
                raise AssertionError("unexpected model API")
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(data))
        return route.fulfill(status=404)

    page.route("https://chat.test/**", respond)
    return seen


@pytest.mark.parametrize("width", [1440, 390])
def test_model_list_selection_and_multi_product_preview_no_writes(width):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": width, "height": 920})
                seen = _install_mock(page)
                page.goto("https://chat.test/admin-models.html")
                page.get_by_role("heading", name="모델 흐름을 한 곳에서 관리").wait_for()
                page.get_by_text("관리자 조회 허용 · READ ONLY").wait_for()
                assert page.locator("#modelCount").inner_text() == "2"
                assert page.locator("#sourceCount").inner_text() == "1 / 5"
                page.locator(".model-item").first.click()
                assert page.locator("#selectedId").inner_text() == "google/gemini-safe"
                page.get_by_role("checkbox", name="중앙 등급 정책 변경 대상").check()
                page.get_by_role("checkbox", name="Claw 변경 대상").check()
                assert page.locator("#targetCount").inner_text() == "2"
                page.locator("#tierSelect").select_option("PRO")
                page.locator("#actionSelect").select_option("block")
                page.locator("#previewBtn").click()
                page.get_by_text("검증 통과 · 운영 반영 없음").wait_for()
                assert "Claw / PRO" in page.locator("#previewResult").inner_text()
                assert "중앙 등급 정책 / PRO" in page.locator("#previewResult").inner_text()
                assert [x["method"] for x in seen] == ["GET", "GET", "POST"]
                assert {x["path"] for x in seen} <= {
                    "/api/admin/models/me", "/api/admin/models/snapshot",
                    "/api/admin/models/preview",
                }
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            finally:
                browser.close()
    except (FileNotFoundError, OSError) as exc:
        pytest.skip(f"Chromium runtime unavailable: {exc}")


def test_non_global_user_cannot_fetch_catalog_or_preview():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            seen = _install_mock(page, authorized=False)
            page.goto("https://chat.test/admin-models.html")
            page.get_by_text("이 계정에는 중앙 모델 관리자 권한이 없습니다.").wait_for()
            assert page.locator(".model-item").count() == 0
            assert page.locator("#previewBtn").is_disabled()
            assert [x["path"] for x in seen] == ["/api/admin/models/me"]
        finally:
            browser.close()
