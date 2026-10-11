"""#3396: isolated Chromium contexts prove server-backed B66 guided resume.

Loopback only. Synthetic cookie scopes model server-issued authenticated ownership.
This is NOT a production account/independent-login attestation and does not
contact production, create users, call models, or mutate customer data.
"""
from __future__ import annotations

import asyncio
import functools
import http.cookies
import http.server
import json
import threading
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
API = "/api/padiem/b66/guided-draft"
MARKER = "B66-3396-SYNTHETIC-ISOLATED-TEST"
SLOTS: dict[tuple[str, str], dict] = {}
LOCK = threading.Lock()

STATE = {
    "schema": "b66.guided-draft.v1", "mode": "guided",
    "step": "price", "currentItem": 0, "taxUnknown": False, "savedSkillId": "",
    "draft": {
        "recipient": {"company": MARKER, "person": "TEST", "address": "", "email": ""},
        "sender": {"company": "OFFLINE TEST"},
        "items": [{"id": "item-1", "name": "OFFLINE TEST ITEM",
                   "qty": 2, "unitPrice": None, "unit": ""}],
        "tax": {"mode": "EXCLUSIVE"}, "memo": "OFFLINE ONLY",
        "meta": {"quoteNo": MARKER, "issueDate": "2026-10-11"},
    },
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def scope(self):
        cookies = http.cookies.SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        owner = cookies.get("qa_owner")
        workspace = cookies.get("qa_workspace")
        if owner is None or workspace is None:
            return None
        return (owner.value, workspace.value)

    def respond(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if not path.startswith("/api/padiem/"):
            return super().do_GET()
        scope = self.scope()
        if scope is None:
            return self.respond({"ok": False, "error": {"code": "unauthorized"}}, 401)
        if path == "/api/padiem/auth/status":
            return self.respond({"authenticated": True, "session_state": "signed_in",
                                 "user": {"id": scope[0]}, "methods": {"password": True}})
        if path == API:
            with LOCK:
                state = SLOTS.get(scope)
            return self.respond({"ok": True, "state": state})
        if path == "/api/padiem/b66/company-profile":
            return self.respond({"ok": True, "company_profile": None})
        if path == "/api/padiem/b66/saved-skills":
            return self.respond({"ok": True, "skills": [], "limit": 20})
        if path == "/api/padiem/b66/quotes":
            return self.respond({"ok": True, "quotes": []})
        if path == "/api/padiem/b66/quote/models":
            return self.respond({"ok": True, "models": [], "default_model_id": None})
        return self.respond({"ok": False, "error": {"code": "not_stubbed"}}, 404)

    def do_PUT(self):
        if urlsplit(self.path).path != API:
            return self.respond({"ok": False}, 404)
        scope = self.scope()
        if scope is None:
            return self.respond({"ok": False, "error": {"code": "unauthorized"}}, 401)
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 16384:
            return self.respond({"ok": False}, 413)
        try:
            state = json.loads(self.rfile.read(size))
        except (UnicodeError, ValueError):
            return self.respond({"ok": False}, 400)
        if not isinstance(state, dict) or any(
            key in state for key in ("user_id", "workspace_id", "owner", "ownerId")
        ) or state.get("schema") != STATE["schema"]:
            return self.respond({"ok": False}, 400)
        with LOCK:
            SLOTS[scope] = state
        return self.respond({"ok": True})

    def do_DELETE(self):
        if urlsplit(self.path).path != API:
            return self.respond({"ok": False}, 404)
        scope = self.scope()
        if scope is None:
            return self.respond({"ok": False}, 401)
        with LOCK:
            SLOTS.pop(scope, None)
        return self.respond({"ok": True})


async def session(browser, origin: str, owner=None, workspace="w1"):
    ctx = await browser.new_context(viewport={"width": 1200, "height": 800})
    if owner is not None:
        await ctx.add_cookies([
            {"name": "qa_owner", "value": owner, "url": origin},
            {"name": "qa_workspace", "value": workspace, "url": origin},
        ])
    page = await ctx.new_page()
    await page.goto(origin + "/index.html", wait_until="load")
    await page.wait_for_function("() => !!window.B66GuidedDraftServer", timeout=15000)
    return ctx, page


async def request(page, method="GET", body=None):
    return await page.evaluate(
        """async ({method, body}) => {
            const r=await fetch('/api/padiem/b66/guided-draft', {
                method,credentials:'same-origin',
                headers:body?{'Content-Type':'application/json'}:{},
                body:body?JSON.stringify(body):undefined,
                cache:'no-store'
            });
            return {status:r.status, data:await r.json()};
        }""",
        {"method": method, "body": body},
    )


async def main():
    handler = functools.partial(Handler, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    contexts = []
    checks = {}
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for name, owner, workspace in (
                    ("A", "owner-a", "w1"), ("B", "owner-a", "w1"),
                    ("FOREIGN", "owner-b", "w1"),
                    ("OTHER_WORKSPACE", "owner-a", "w2"),
                    ("ANONYMOUS", None, "w1"),
                ):
                    ctx, page = await session(browser, origin, owner, workspace)
                    contexts.append(ctx)
                    checks[name] = page

                assert (await request(checks["A"]))["data"]["state"] is None
                saved = await request(checks["A"], "PUT", STATE)
                assert saved["status"] == 200 and saved["data"]["ok"] is True

                # Same account in a wholly separate browser context has no
                # shared cookies/localStorage, except its independently assigned
                # synthetic owner identity. All content is server-backed.
                for name in ("A", "B"):
                    page = checks[name]
                    data = await request(page)
                    assert data["status"] == 200
                    assert data["data"]["state"]["draft"]["meta"]["quoteNo"] == MARKER
                    await page.locator("#resumeDraftStarter").click()
                    await page.wait_for_function(
                        "() => window.history.state?.b66View === 'guided'"
                    )
                    assert await page.locator("#easyComposer").get_attribute("placeholder") == (
                        "예: 1,500,000 또는 150만원"
                    ), name
                print("GUIDED_TWO_INDEPENDENT_CONTEXTS_SAME_OWNER=PASS")

                for name in ("FOREIGN", "OTHER_WORKSPACE"):
                    data = await request(checks[name])
                    assert data["status"] == 200 and data["data"]["state"] is None
                print("GUIDED_OWNER_AND_WORKSPACE_ISOLATION=PASS")

                anonymous = await request(checks["ANONYMOUS"])
                assert anonymous["status"] == 401
                print("GUIDED_ANONYMOUS_DENIED=PASS")

                spoofed = dict(STATE, user_id="owner-b")
                rejected = await request(checks["A"], "PUT", spoofed)
                assert rejected["status"] == 400
                assert (await request(checks["B"]))["data"]["state"]["step"] == "price"
                print("GUIDED_CLIENT_OWNER_SPOOF_REJECTED=PASS")

                deleted = await request(checks["A"], "DELETE")
                assert deleted["status"] == 200
                for name in ("A", "B", "FOREIGN", "OTHER_WORKSPACE"):
                    assert (await request(checks[name]))["data"]["state"] is None
                print("GUIDED_SYNTHETIC_CLEANUP_AND_PROPAGATION=PASS")
            finally:
                for context in reversed(contexts):
                    await context.close()
                await browser.close()
    finally:
        server.shutdown()
        server.server_close()
        assert not SLOTS, "synthetic state leaked after test"
    print("GUIDED_3396_ISOLATED_BROWSER_E2E=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
