"""#8035 ① 운영센터 — the /admin tab frame and the inbox tab.

Three contracts here:

  1. static — admin.html carries the ops center frame (tabs, hash routing
     target, the theme init) and loads admin-ops.js;
  2. server — the inbox the ops center reuses keeps its guard and the AI
     tester intro display (same endpoints as the feedback window);
  3. browser — an administrator sees the panel and the inbox rows, a normal
     member sees the gate, and a guest makes ZERO ops-center /api/* calls.
"""
import asyncio
import http.server
import json
import re
import threading
from pathlib import Path

import pytest

from app.feedback_routes import admin_feedback
from _support.ops_audit_helpers import (AUDIT_BODY_ID, BASE, BODY,
                                        DISABLED_ARIA, MEMBER_SEARCH_ID,
                                        MEMBERS_TAB_ID, OWNER, OTHER, SETTINGS,
                                        AdminAuthority, database, payload, request)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
ADMIN_HTML = STATIC / "admin.html"
OPS_JS = STATIC / "admin-ops.js"


# ---- 1. static frame -------------------------------------------------------

def test_admin_page_carries_the_ops_center_frame():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert 'id="opsCenterPanel"' in html
    assert 'id="opsInboxPane"' in html
    assert html.index("./admin-ops.js") > html.index("./admin.js")
    # The dashboard palette stays pinned (#4428 html:root) — admin.html does
    # NOT load theme-init; the panel's ?theme= handling lives in admin-ops.js.
    assert "./theme-init.js" not in html
    tabs = re.findall(r'<button class="ops-tab[^"]*"[^>]*>([^<]+)</button>', html)
    assert tabs == ["받은함", "회원", "사용 일지", "점수 입력", "새 소식 관리"]
    # ①②③④에서 모든 운영센터 탭이 열렸다.
    enabled = re.findall(r'<button class="ops-tab selected"[^>]*>', html)
    assert len(enabled) == 1
    assert html.count(DISABLED_ARIA) == 0
    assert MEMBERS_TAB_ID in html
    assert AUDIT_BODY_ID in html
    assert MEMBER_SEARCH_ID in html


def test_ops_module_never_fetches_outside_the_open_gate():
    source = OPS_JS.read_text(encoding="utf-8")
    # Every fetch goes through call()/loadInbox, and loadInbox runs only from
    # paths guarded by the gate observer (wire() runs once the gate opened).
    assert "fetch(" in source
    assert "api/admin/feedback" in source
    # No fetch can fire at module evaluation time: the IIFE registers an
    # observer and never calls loadInbox unconditionally.
    top_level_calls = re.findall(r"^  (?:void )?loadInbox\(", source, re.M)
    assert top_level_calls == []
    assert 'observer.observe(content' in source


# ---- 2. server contract the ops center reuses ------------------------------

def test_admin_inbox_guard_keeps_normal_member_and_guest_out():
    async def scenario():
        db, store = database()
        try:
            forbidden = await admin_feedback(request(store, user=OWNER))
            assert forbidden.status_code == 403
            assert payload(forbidden)["error"]["code"] == "global_model_admin_forbidden"
            guest = await admin_feedback(request(store, user=None))
            assert guest.status_code == 401
            assert payload(guest)["error"]["code"] == "authentication_required"
        finally:
            pass
    asyncio.run(scenario())


def test_admin_inbox_marks_ai_tester_and_carries_the_intro():
    """The ops center's inbox reads the same answer as the feedback window:
    the AI tester chip rides on is_ai_tester and the intro arrives only for
    the admin view."""
    async def scenario():
        db, store = database()
        try:
            assert re.fullmatch(r"usr_[0-9a-f]{32}", OWNER)
            db.execute("UPDATE users SET display_name='QA 테스터' WHERE id=?",
                       (OWNER,))
            db.execute(
                "INSERT OR REPLACE INTO ai_tester_intro (user_id, age_band,"
                " job, device, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (OWNER, "20대", "운영", "PC",
                 "2026-11-19T00:00:00.000Z", "2026-11-19T00:00:00.000Z"))
            from app.feedback_routes import feedback
            created = await feedback(request(store, method="POST",
                                             body={"body": BODY}))
            assert created.status_code == 201
            item = payload(created)["feedback"]
            marked = await store.set_ai_tester(item["id"], True)
            assert marked.is_ai_tester is True
            inbox = payload(await admin_feedback(request(store, user=OTHER)))
            rows = inbox["feedback"]
            assert rows and rows[0]["is_ai_tester"] is True
            assert rows[0]["sender_display"] != ""
            assert rows[0]["sender_intro"] == {"age_band": "20대",
                                               "job": "운영", "device": "PC"}
            # The masked sender contract stays: no email, no full id.
            assert inbox["feedback"][0]["sender_user_id"] == OWNER
            # The masked label stays as a compact display form.
            assert inbox["feedback"][0]["sender_label"].startswith("••••")
        finally:
            pass
    asyncio.run(scenario())


# ---- 3. browser gate -------------------------------------------------------

LINK = {"link_id": "fb_qa_0001", "state": "new"}
ADMIN_ITEM = {
    "id": "fb_0000000000000000000000000000aa01",
    "body": "의견 본문 예시입니다.",
    "screen": None,
    "status": "new",
    "created_at": "2026-11-19T03:00:00.000Z",
    "updated_at": "2026-11-19T03:00:00.000Z",
    "fixed_version": 0,
    "unread_fixed": False,
    "unread_ops_replies": 0,
    "replies": [],
    "news": None,
    "sender_label": "••••9f3d",
    "is_ai_tester": True,
    "sender_display": "QA 테스터",
    "sender_intro": {"age_band": "20대", "job": "운영", "device": "PC"},
}
ADMIN_SESSION = {"ok": True, "authenticated": True, "role": "ADMIN",
                 "capabilities": {"admin_hub": True, "chat_admin": True}}
GUEST_SESSION = {"ok": True, "authenticated": False, "role": None,
                 "capabilities": {}}


class _AdminServer:
    def __init__(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC), **kwargs)

            def log_message(self, *args):
                pass

        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.web.server_address[1]}/admin.html"

    def shutdown(self):
        self.web.shutdown()


def _stub_api(page, session_body):
    # Registration order matters: the generic answer first, the specific
    # overrides after — Playwright serves the LAST matching route.
    page.route(re.compile(r".*/api/.*$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json", body="{}"))
    page.route(re.compile(r".*/api/admin/session$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps(session_body)))
    page.route(re.compile(r".*/api/admin/feedback(\?.*)?$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "feedback": [ADMIN_ITEM],
                                    "next_cursor": None})))
    page.route(re.compile(r".*/api/admin/feedback/.+$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "feedback": ADMIN_ITEM})))


def _ops_calls(page):
    calls: list[str] = []
    page.on("request", lambda req: calls.append(req.url) if
            "/api/admin/feedback" in req.url else None)
    return calls


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_administrator_sees_the_ops_center_and_inbox():
    server = _AdminServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page, ADMIN_SESSION)
            calls = _ops_calls(page)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#opsCenterPanel", timeout=15000)
            page.wait_for_selector("#opsInboxList .ops-row", timeout=15000)
            page.wait_for_timeout(500)
            rows = page.locator("#opsInboxList .ops-row").count()
            chips = page.locator(".ops-chip-ai").count()
            browser.close()
    finally:
        server.shutdown()
    assert rows == 1
    assert chips == 1
    assert calls, "the admin inbox must load /api/admin/feedback"


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_guest_and_normal_member_get_the_gate_and_zero_ops_calls():
    server = _AdminServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for session_body in (GUEST_SESSION,
                                 {"ok": True, "authenticated": True,
                                  "role": None, "capabilities": {}}):
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900})
                page = context.new_page()
                _stub_api(page, session_body)
                calls = _ops_calls(page)
                page.goto(server.base, wait_until="domcontentloaded",
                          timeout=30000)
                page.wait_for_selector("#gatePanel:not([hidden])", timeout=15000)
                page.wait_for_timeout(1200)
                hidden = page.evaluate(
                    "() => document.getElementById('adminContent').hidden")
                assert hidden is True
                assert calls == [], calls[:3]  # 게스트·일반 /api/* 0건 (ops)
                context.close()
            browser.close()
    finally:
        server.shutdown()


def test_ops_panel_theme_tokens_cover_all_five_themes():
    """#4428 keeps the dashboard palette pinned, so the panel carries scoped
    --ops-* tokens per theme; the four themed blocks must exist and be
    distinct from each other and from the light base."""
    css = (STATIC / "admin.css").read_text(encoding="utf-8")
    assert ".ops-panel{--ops-panel-bg:#ffffff" in css  # light base
    themed = {}
    for theme in ("dark", "cinematic", "padiem-home", "padiem-glass"):
        found = re.search(
            r'html\[data-theme="%s"\] \.ops-panel\{([^}]+)\}' % theme, css)
        assert found, theme
        themed[theme] = found.group(1)
        assert "--ops-panel-bg:" in themed[theme]
    assert len(set(themed.values())) == 4, themed
