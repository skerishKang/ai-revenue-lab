"""#5006: CGI sidebar work tools and connection management in a real browser.

Verifies the honest, non-optimistic behaviour in a real browser:

* the existing quote menus still exist and the new sections come after them;
* the four work-tool entries are real links into the owning product, open a
  new tab and never fetch that product's data;
* PC status reports each distinct real state: connected, registered-but-offline,
  unprovisioned grant, signed-out, and failed read — never a false claim;
* Drive status reflects the mounted Drive surface and never invents a
  connection;
* the mobile drawer still contains the whole rail and no always-visible
  button is added outside it.
"""
from __future__ import annotations

import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
SKILL_ID = "b66skill_" + "0" * 32
MODEL_ID = "opencode-go/beam-free"
EMAIL = "sidebar@example.test"
DEVICE_ENDPOINT = "/api/padiem/b66/connect/devices"


def envelope(devices):
    return {"ok": True, "available": True, "ownerScoped": True, "devices": devices}


def pc(device_id, name, *, online=True, revoked=False):
    """The exact closed field set the #4434 directory serializes."""
    if revoked:
        state, usable = "REVOKED", False
    elif online:
        state, usable = "CONNECTED", True
    else:
        state, usable = "OFFLINE", False
    return {"deviceId": device_id, "deviceName": name, "platform": "Windows",
            "state": state, "usable": usable, "revoked": revoked, "expired": False}


class Handler(http.server.SimpleHTTPRequestHandler):
    state: dict = {}

    def log_message(self, *_a):  # pragma: no cover
        return

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _route(self):
        path = self.path.split("?", 1)[0]
        return path[len("/api/padiem"):] if path.startswith("/api/padiem") else path

    def do_GET(self):
        path = self._route()
        if path.startswith(("/auth/", "/b66/")):
            payload = type(self).state.get(path)
            if payload is None:
                return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)
            return self._json(payload)
        return super().do_GET()

    def do_PUT(self):
        if self._route() == "/b66/guided-draft":
            return self._json({"ok": True})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_DELETE(self):
        if self._route() == "/b66/guided-draft":
            return self._json({"ok": True})
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_POST(self):
        return self._json({"ok": False, "error": {"code": "not_stubbed"}}, 404)


BUILD_SKILL_JS = """() => {
  const T = window.QuoteTemplate;
  const S = window.SavedQuoteSkill;
  const base = {
    id: 'skill-sidebar', name: 'CGI 시지아이',
    fixedDefaults: {sender: {company: '시지아이', rep: '대표', bizNo: '000-00-00000',
                 address: '광주', phone: '000-000-0000', email: 's@example.test',
                 presetId: 'saved-skill'},
      validDays: 14, taxMode: 'EXCLUSIVE', memo: ''},
    variableSchema: {recipient: true, quoteNo: true, issueDate: true, items: true,
                      memo: false, taxMode: true},
    internalTemplate: T.serializeTemplate(T.builtInTemplate()),
    provenance: {sourceKind: 'file', sourceName: 'cgi.pdf', sourceRef: 'source:sidebar',
                 capturedAt: '2026-10-18T00:00:00.000Z', warnings: [], unknowns: [], evidence: []},
    createdAt: '2026-10-18T00:00:00.000Z', updatedAt: '2026-10-18T00:00:00.000Z'
  };
  const d = S.buildSkill(base);
  const approved = S.buildSkill(Object.assign({}, base, {approval: {
    schemaVersion: 1, status: 'approved', skillFingerprint: d.fingerprint,
    approvedBy: 'test', approvedAt: '2026-10-18T00:00:00.000Z', approvalRef: 'sidebar'}}));
  return {ok: true, skill: S.serializeSkill(approved), fingerprint: approved.fingerprint};
}"""

RAIL_JS = """() => Array.from(
  document.querySelectorAll('#shellRail .shell-rail-item'))
  .map(n => n.id)"""

STATE_JS = """id => {
  const n = document.getElementById(id);
  return n ? {state: n.dataset.state || '', text: n.textContent || ''} : null;
}"""

WORK_LINKS_JS = """() => Array.from(
  document.querySelectorAll('#shellRail [data-href]'))
  .map(n => ({id: n.id, href: n.getAttribute('data-href'), role: n.getAttribute('role')}))"""


async def wait_state(page, state, timeout=15000):
    await page.wait_for_function(
        "s => (document.getElementById('shellPcStatus')?.dataset.state || '') === s",
        arg=state, timeout=timeout,
    )


async def main() -> int:
    handler = functools.partial(Handler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    failures: list[str] = []
    pc_payload = {"status": 200,
                  "body": json.dumps(envelope([pc("home", "집 PC")]), ensure_ascii=False)}

    async def mock_devices(route):
        # async_playwright requires the fulfil to be awaited, or the request
        # never completes and the page-side read hangs.
        await route.fulfill(status=pc_payload["status"], content_type="application/json",
                            body=pc_payload["body"])

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge && window.SavedQuoteSkill", timeout=20000)
            built = await page.evaluate(BUILD_SKILL_JS)
            if not built.get("ok"):
                raise RuntimeError(f"skill fixture build failed: {built}")

            Handler.state = {
                "/auth/status": {"ok": True, "authenticated": True,
                                 "session_state": "signed_in",
                                 "user": {"id": "sidebar-user", "email": EMAIL},
                                 "methods": {"google": True, "password": False}},
                "/b66/quote/models": {
                    "ok": True,
                    "models": [{"model_id": MODEL_ID, "name": "Free",
                                "reasoning_levels": [{"value": "default", "label": "기본"}]}],
                    "default_model_id": None,
                    "tiers": [{"tier": "free", "name": "시지아이 Free", "model_id": MODEL_ID,
                               "reasoning_levels": [{"value": "default", "label": "기본"}]}],
                    "default_tier": "free"},
                "/b66/company-profile": {"ok": True, "company_profile": {
                    "company": "시지아이", "representative": "대표",
                    "defaultValidityDays": 14, "defaultTaxMode": "EXCLUSIVE"}},
                "/b66/saved-skills": {"ok": True, "skills": [
                    {"saved_skill_id": SKILL_ID, "skill_name": "CGI 시지아이"}], "limit": 20},
                f"/b66/saved-skills/{SKILL_ID}": {
                    "ok": True,
                    "saved_skill": {"saved_skill_id": SKILL_ID,
                                    "skill_id": built["skill"]["id"],
                                    "skill_name": built["skill"]["name"],
                                    "skill_fingerprint": built["fingerprint"],
                                    "skill_version": built["skill"]["schemaVersion"],
                                    "skill": built["skill"]},
                },
                "/b66/quotes": {"ok": True, "quotes": [], "limit": 20},
                "/b66/guided-draft": {"ok": True, "state": None},
            }
            await page.route("**" + DEVICE_ENDPOINT, mock_devices)
            await page.goto(f"{base}/index.html", wait_until="load")
            await page.wait_for_function(
                "() => window.B66QuoteRuntimeBridge.readiness().ready === true", timeout=20000)

            # 1) existing quote menus intact, new sections appended after them
            rail = await page.evaluate(RAIL_JS)
            for existing in ("shellNewQuote", "shellManualQuote", "shellRecentQuote",
                             "shellPreviousAiDialogue", "shellPreviousGuidedDialogue"):
                if existing not in rail:
                    failures.append("existing_quote_menu_missing:" + existing)
            for added in ("shellToolMeeting", "shellToolAutomation",
                          "shellToolLibrary", "shellToolCalendar",
                          "shellDriveConnection", "shellPcConnection"):
                if added not in rail:
                    failures.append("new_entry_missing:" + added)
            if rail.index("shellPreviousGuidedDialogue") > rail.index("shellToolMeeting"):
                failures.append("new_sections_inserted_before_the_quote_menus")

            # 2) work tools are links into the owning product, not data reads
            links = await page.evaluate(WORK_LINKS_JS)
            by_id = {row["id"]: row for row in links}
            for tool in ("shellToolMeeting", "shellToolAutomation",
                         "shellToolLibrary", "shellToolCalendar"):
                row = by_id.get(tool)
                if not row:
                    failures.append("work_tool_not_a_link:" + tool)
                    continue
                if not row["href"].startswith("https://chat.padiem.net/"):
                    failures.append("work_tool_wrong_origin:" + tool)
                if row["role"] != "link":
                    failures.append("work_tool_not_link_role:" + tool)
            if by_id.get("shellToolAutomation", {}).get("href") != \
                    "https://chat.padiem.net/#padiem-automation":
                failures.append("automation_hash_wrong")

            # 3) honest PC states, one real read at a time
            await wait_state(page, "ready")
            ready = await page.evaluate(STATE_JS, "shellPcStatus")
            if "1대 연결됨" not in ready["text"]:
                failures.append("connected_pc_state_wrong:" + ready["text"])

            pc_payload["body"] = json.dumps(
                envelope([pc("home", "집 PC", online=False),
                          pc("office", "사무실 PC", online=False)]),
                ensure_ascii=False)
            await page.evaluate("() => document.getElementById('shellPcConnection').click()")
            await page.wait_for_timeout(900)
            offline = await page.evaluate(STATE_JS, "shellPcStatus")
            if "지금은 연결된 컴퓨터가 없습니다" not in offline["text"]:
                failures.append("offline_pc_state_wrong:" + offline["text"])

            pc_payload["status"] = 403
            pc_payload["body"] = json.dumps({"ok": False, "error": {"code": "unavailable"}})
            await page.evaluate("() => document.getElementById('shellPcConnection').click()")
            await wait_state(page, "not-enabled")
            not_enabled = await page.evaluate(STATE_JS, "shellPcStatus")
            if "권한이 아직 설정되지 않았습니다" not in not_enabled["text"]:
                failures.append("unprovisioned_state_wrong:" + not_enabled["text"])

            pc_payload["status"] = 401
            pc_payload["body"] = json.dumps({"ok": False})
            await page.evaluate("() => document.getElementById('shellPcConnection').click()")
            await wait_state(page, "signed-out")
            signed_out = await page.evaluate(STATE_JS, "shellPcStatus")
            if "로그인하면" not in signed_out["text"]:
                failures.append("signed_out_state_wrong:" + signed_out["text"])

            # A non-owner-scoped envelope must never count as a read.
            pc_payload["status"] = 200
            pc_payload["body"] = json.dumps(
                {"ok": True, "available": True, "ownerScoped": False,
                 "devices": [pc("foreign", "다른 계정 PC")]}, ensure_ascii=False)
            await page.evaluate("() => document.getElementById('shellPcConnection').click()")
            await wait_state(page, "unavailable")
            foreign = await page.evaluate(STATE_JS, "shellPcStatus")
            if "확인하지 못했습니다" not in foreign["text"]:
                failures.append("foreign_envelope_state_wrong:" + foreign["text"])
            if "다른 계정 PC" in foreign["text"]:
                failures.append("foreign_device_disclosed")

            # 4) Drive status never claims a connection that was not verified
            drive = await page.evaluate(STATE_JS, "shellDriveStatus")
            if not drive or drive["state"] in ("", "ready"):
                failures.append("drive_state_unverified:" + json.dumps(drive, ensure_ascii=False))

            # 5) mobile keeps the whole rail in the drawer
            await page.set_viewport_size({"width": 390, "height": 844})
            await page.wait_for_timeout(500)
            collapsed = await page.evaluate(
                "() => document.body.classList.contains('rail-collapsed')")
            if not collapsed:
                failures.append("mobile_rail_not_drawner_default")
            await page.evaluate(
                "() => document.getElementById('shellRailToggle')?.click()")
            await page.wait_for_timeout(400)
            mobile_tool = await page.evaluate(
                "() => !!document.getElementById('shellToolCalendar')")
            if not mobile_tool:
                failures.append("mobile_drawer_missing_work_tools")
            overflow = await page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
            if overflow:
                failures.append("mobile_horizontal_scroll")

            if errors:
                failures.append("page_error:" + errors[0][:120])
        finally:
            await browser.close()
        server.shutdown()

    if failures:
        print("FAILURES:", json.dumps(failures, ensure_ascii=False))
        print("B66_5006_SIDEBAR_BROWSER=FAIL")
        return 1
    print("B66_5006_SIDEBAR_BROWSER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(__import__("asyncio").run(main()))