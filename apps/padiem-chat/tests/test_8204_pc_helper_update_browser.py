import json
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
STATIC = Path(__file__).resolve().parents[1] / "static"


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", ["padiem-glass", "light", "dark", "cinematic", "padiem-home"])
def test_update_banner_settings_guest_and_dismiss_per_version(width, theme):
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        calls = []
        state = {"link_id": "link-a", "label": "PC", "online": True, "auto_update": False,
                 "notice": True, "update_required": False, "dismissed": False, "latest_version": "0.4.0"}

        def route(req):
            path = req.request.url.split("test.invalid", 1)[1]
            if path == "/":
                req.fulfill(content_type="text/html", body=f'''<!doctype html><html lang="ko" data-theme="{theme}">
                <head><meta charset="utf-8"><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/padiem-glass.css"><link rel="stylesheet" href="/padiem-themes.css"><link rel="stylesheet" href="/pc-helper-update.css"></head>
                <body><main><div id="pcHelperUpdateBanner" class="pc-helper-update-banner" hidden></div>
                <div id="accountSettingsSection"></div></main>
                <script>window.loggedIn=false;window.PadiemAuthGate={{authenticated:()=>window.loggedIn}}</script>
                <script src="/pc-helper-update-ui.js"></script></body></html>''')
            elif path == "/api/pc/helper-updates":
                calls.append("list")
                req.fulfill(content_type="application/json", body=json.dumps({"devices": [state]}))
            elif path == "/api/pc/helper-updates/link-a":
                action = req.request.post_data_json
                calls.append(action)
                if action["action"] == "dismiss":
                    state["dismissed"] = True
                elif action["action"] == "auto":
                    state["auto_update"] = action["enabled"]
                    state["notice"] = not action["enabled"]
                req.fulfill(content_type="application/json", body='{"ok":true}')
            else:
                req.fulfill(path=str(STATIC / path.lstrip("/")), **({"content_type": "application/javascript; charset=utf-8"} if path.endswith(".js") else {}))

        page.route("http://test.invalid/**", route)
        page.goto("http://test.invalid/")
        panel = page.locator("#pcHelperUpdateBanner")
        assert not panel.is_visible() and not calls
        page.evaluate("window.loggedIn=true;dispatchEvent(new Event('padiem:auth-state'))")
        panel.wait_for(state="visible")
        assert panel.get_by_text("PC 연결 새 버전이 있어요", exact=False).is_visible()
        assert panel.bounding_box()["width"] <= width
        panel.get_by_role("button", name="지금 업데이트").click()
        page.wait_for_function("() => document.querySelector('#pcHelperUpdateBanner button') && !document.querySelector('#pcHelperUpdateBanner button').disabled")
        assert {"action": "update"} in calls
        panel.get_by_role("button", name="닫기").click()
        panel.wait_for(state="hidden")
        assert {"action": "dismiss", "version": "0.4.0"} in calls
        state.update(dismissed=False, latest_version="0.5.0")
        page.evaluate("dispatchEvent(new Event('focus'))")
        panel.wait_for(state="visible")
        page.locator(".pc-helper-update-settings input").check()
        panel.wait_for(state="hidden")
        assert {"action": "auto", "enabled": True} in calls
        state.update(update_required=True, dismissed=True)
        page.evaluate("dispatchEvent(new Event('focus'))")
        panel.wait_for(state="visible")
        assert panel.get_by_text("업데이트 후 사용할 수 있어요", exact=False).is_visible()
        assert panel.get_by_role("button", name="닫기").count() == 0
        page.evaluate("window.loggedIn=false;dispatchEvent(new Event('padiem:auth-state'))")
        assert not panel.is_visible()
        browser.close()
