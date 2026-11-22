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
                changes = []
                refreshes = []
                rollout = {"initialized": True, "revision": 7, "stage": "internal", "percent": 25,
                           "stable": {"version": "0.3.0-rc1"}, "target": {"version": "0.3.0-rc2", "sha256": "b" * 64},
                           "groups": {name: {"total": 1, "updated": int(name == "internal"),
                                             "failed": 0, "rollback": 0}
                                      for name in ("internal", "percentage", "remaining")}}

                def route(intercept):
                    path = urlsplit(intercept.request.url).path
                    if path == "/api/admin/session":
                        data = {"ok": True, "authenticated": admin,
                                "role": "ADMIN" if admin else None,
                                "capabilities": {"admin_hub": True, "chat_admin": True} if admin else {}}
                    elif path == "/api/admin/ops-pc-versions/rollout":
                        changes.append(intercept.request.post_data_json)
                        rollout["revision"] += 1
                        rollout["stage"] = "paused"
                        data = {"ok": True}
                    elif path == "/api/admin/ops-pc-versions/refresh-updaters":
                        refreshes.append(intercept.request.post_data_json)
                        data = {"ok": True, "source_sha256": "c" * 64, "devices": [
                            {"device_id": "node//pc-example", "action": "refresh", "reason": "source_changed"}]}
                    elif path == "/api/admin/ops-pc-versions":
                        calls.append(path)
                        data = {"ok": True, "rollout": rollout, "devices": [
                            {"device_id": "node//pc-example", "helper_version": "0.3.0-rc1",
                             "helper_build": "a" * 12, "mesh_agent_version": "2026-02-16T00:43:44.000Z",
                             "last_healthy_at": "2026-11-21T01:02:03Z", "update_result": "success",
                             "updater_registration": {"action": "reinstall_required", "reason": "system_denied"}},
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
                        "…xample", "0.3.0-rc1 (aaaaaaaaaaaa) · 업데이트 완료",
                        "2026-02-16T00:43:44.000Z", "2026. 11. 21. 01:02", "재설치 필요 · SYSTEM 권한 없음"]
                    assert rows.last.locator("td").all_inner_texts()[0] == "…nknown"
                    assert page.locator("#opsPcVersionsHeading").inner_text() == "PC 버전 현황"
                    assert "도우미 버전 / 빌드" in page.locator("table[aria-labelledby='opsPcVersionsHeading'] thead").inner_text()
                    page.click("#opsPcVersionsReload")
                    page.wait_for_function("() => !document.getElementById('opsPcVersionsReload').disabled")
                    assert len(calls) == 2
                    assert page.locator("#opsPcRolloutBody tr").count() == 3
                    assert page.locator("#opsPcRolloutBody tr").first.locator("td").all_inner_texts()[1:] == ["1", "1", "0", "0"]
                    page.locator("#opsPcRolloutPercent").fill("30")
                    page.click("#opsPcRolloutPause")
                    page.wait_for_function("() => document.getElementById('opsPcRolloutPause').disabled && !document.getElementById('opsPcRolloutPercent').disabled")
                    assert changes == [{"action": "pause", "percent": 30, "revision": 7, "target_sha256": "b" * 64}]
                    assert page.locator("#opsPcRefreshApply").is_disabled()
                    page.click("#opsPcRefreshPreview")
                    page.wait_for_function("() => !document.getElementById('opsPcRefreshApply').disabled")
                    assert refreshes == [{"dry_run": True}]
                    page.click("#opsPcRefreshApply")
                    page.wait_for_function("() => !document.getElementById('opsPcRefreshPreview').disabled")
                    assert refreshes[-1] == {"dry_run": False, "source_sha256": "c" * 64}
                else:
                    page.wait_for_selector("#gatePanel:not([hidden])")
                    page.wait_for_load_state("networkidle")
                    assert not calls and not changes and not refreshes and not page.locator("#opsPcVersionsBody").is_visible()
                page.close()
        finally:
            browser.close()


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_refresh_failure_surfaces_server_reason_and_base_version():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            rollout = {"initialized": False, "revision": 1, "stage": "internal", "percent": 25,
                       "stable": {"version": "-"}, "target": {"version": "0.3.0-rc2", "sha256": "b" * 64},
                       "groups": {name: {"total": 0, "updated": 0, "failed": 0, "rollback": 0}
                                  for name in ("internal", "percentage", "remaining")}}

            def route(intercept):
                path = urlsplit(intercept.request.url).path
                if path == "/api/admin/session":
                    data = {"ok": True, "authenticated": True, "role": "ADMIN",
                            "capabilities": {"admin_hub": True, "chat_admin": True}}
                    status = 200
                elif path == "/api/admin/ops-pc-versions":
                    data = {"ok": True, "devices": [], "rollout": rollout}
                    status = 200
                elif path == "/api/admin/ops-pc-versions/refresh-updaters":
                    data = {"error": "canonical_session_required"}
                    status = 401
                elif path.startswith("/api/"):
                    data = {"ok": True, "members": [], "feedback": [], "audit": []}
                    status = 200
                else:
                    file = STATIC / path.lstrip("/")
                    intercept.fulfill(path=str(file)) if file.is_file() else intercept.fulfill(status=404, body="")
                    return
                intercept.fulfill(status=status, content_type="application/json", body=json.dumps(data))

            page.route(ORIGIN + "/**", route)
            page.goto(ORIGIN + "/admin.html", wait_until="domcontentloaded")
            page.wait_for_function("() => !document.getElementById('opsPcVersionsReload').disabled")
            page.click("#opsPcRefreshPreview")
            page.wait_for_function(
                "() => document.getElementById('opsPcRefreshStatus').textContent.includes('canonical_session_required')")
            text = page.locator("#opsPcRefreshStatus").inner_text()
            assert "기준 버전 미등록" in text
            page.close()
        finally:
            browser.close()
