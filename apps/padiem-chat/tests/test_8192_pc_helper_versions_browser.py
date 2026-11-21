"""Exercise the operations table with the actual static page and no live server."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
ORIGIN = "http://ops-pc-versions.invalid"


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_admin_table_displays_versions_and_guest_does_not_request_it():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for admin in (False, True):
                page = browser.new_page()
                calls = []

                def route(intercept):
                    path = urlsplit(intercept.request.url).path
                    if path == "/api/admin/session":
                        data = {"ok": True, "authenticated": admin,
                                "role": "ADMIN" if admin else None,
                                "capabilities": {"admin_hub": True, "chat_admin": True} if admin else {}}
                    elif path == "/api/admin/ops-pc-versions":
                        calls.append(path)
                        data = {"ok": True, "devices": [
                            {"device_id": "node//pc-example", "helper_version": "0.3.0-rc1",
                             "helper_build": "a" * 12, "mesh_agent_version": "2026-02-16T00:43:44.000Z",
                             "last_healthy_at": "2026-11-21T01:02:03Z"},
                            {"device_id": "node//unknown", "helper_build": None}]}
                    elif path.startswith("/api/"):
                        data = {"ok": True, "members": [], "feedback": [], "audit": []}
                    else:
                        file = STATIC / path.lstrip("/")
                        if file.is_file():
                            intercept.fulfill(path=str(file))
                        else:
                            intercept.fulfill(status=404, body="")
                        return
                    intercept.fulfill(content_type="application/json", body=json.dumps(data))

                page.route(ORIGIN + "/**", route)
                page.goto(ORIGIN + "/admin.html", wait_until="domcontentloaded")
                if admin:
                    page.wait_for_selector("#opsPcVersionsBody tr")
                    rows = page.locator("#opsPcVersionsBody tr")
                    assert rows.count() == 2
                    assert rows.first.locator("td").all_inner_texts() == [
                        "node//pc-example", "0.3.0-rc1 (aaaaaaaaaaaa)",
                        "2026-02-16T00:43:44.000Z", "2026. 11. 21. 01:02"]
                    assert rows.last.locator("td").all_inner_texts()[0] == "node//unknown"
                    page.click("#opsPcVersionsReload")
                    page.wait_for_function("() => !document.getElementById('opsPcVersionsReload').disabled")
                    assert len(calls) == 2
                else:
                    page.wait_for_selector("#gatePanel:not([hidden])")
                    page.wait_for_load_state("networkidle")
                    assert not calls and not page.locator("#opsPcVersionsBody").is_visible()
                page.close()
        finally:
            browser.close()
