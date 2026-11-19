"""#8035 ② 운영센터 회원 탭과 관리자 감사 기록.

Four contracts:

  1. permission — the members endpoints answer only to the administrator:
     normal member 403, guest 401;
  2. audit — a feedback status change through the admin route, an ops-tool
     mutation, and a member-detail opening each leave one who·when·what row
     in ops_audit_log (migration 128);
  3. exposure — the members payload carries the email for the administrator
     and no member data ever reaches a normal member or guest response;
  4. browser — a guest on /admin triggers zero ops-center /api/* calls.
"""
import asyncio
import importlib.util
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE
from app.config import Settings
from app.feedback_routes import (admin_feedback, admin_feedback_reply,
                                 admin_feedback_status)
from app.ops_audit_store import OpsAuditStore
from app.ops_member_routes import (admin_member_detail, admin_members,
                                   admin_ops_audit)
from app.ops_member_store import D1OpsMemberStore
from app.ops_member_store import MemberMissing as _MemberMissing  # noqa: F401
from app.same_origin_guard import SameOriginGuardMiddleware
from _support.ops_audit_helpers import AdminAuthority, BODY, OWNER, OTHER, database, payload
from app.d1_sqlite import SqliteD1
from sid_session_helper import sid_session_token

ROOT = Path(__file__).resolve().parents[2]
BASE = 'https://chat.example.test'
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret='fixture-ops-members-session-signing-only')

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
ADMIN_HTML = STATIC / "admin.html"


def _stores_with_adapter():
    from app.d1_sqlite import SqliteD1
    db, feedback = database(full=True)
    adapter = SqliteD1(db)
    return db, feedback, D1OpsMemberStore(adapter), OpsAuditStore(adapter)


def _req(db, *, feedback=None, members=None, audit=None, method='GET',
         user=OWNER, path='/api/admin/members', member_id='', feedback_id='',
         query='', body=None):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(),
                            feedback_store=feedback,
                            ops_member_store=members, ops_audit_store=audit,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json')]
    if user:
        token = sid_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    headers.append((b'origin', BASE.encode()))
    data = json.dumps(body if body is not None else {}, ensure_ascii=False).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}
    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state),
                    'path_params': {'member_id': member_id,
                                    'feedback_id': feedback_id}}, receive)


def request(db, stores, *, method='GET', user=OWNER, path='/api/admin/members',
            member_id='', query='', feedback_id='', body=None):
    return _req(db, feedback=stores["feedback"], members=stores["members"],
                audit=stores["audit"], method=method, user=user, path=path,
                member_id=member_id, feedback_id=feedback_id, query=query,
                body=body)


def payload(response):
    return json.loads(response.body)


# ---- 1. permission ---------------------------------------------------------

def test_members_endpoints_answer_only_to_the_administrator():
    async def scenario():
        db, feedback, members, audit = _stores_with_adapter()
        stores = {"feedback": feedback, "members": members, "audit": audit}
        try:
            forbidden = await admin_members(request(db, stores, user=OWNER))
            assert forbidden.status_code == 403
            assert payload(forbidden)["error"]["code"] == "global_model_admin_forbidden"
            guest = await admin_members(request(db, stores, user=None))
            assert guest.status_code == 401
            assert payload(guest)["error"]["code"] == "authentication_required"
            detail_forbidden = await admin_member_detail(
                request(db, stores, user=OWNER, member_id=OWNER))
            assert detail_forbidden.status_code == 403
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 2. the members list and detail ---------------------------------------

def test_members_list_carries_the_administrator_view():
    async def scenario():
        db, feedback, members, audit = _stores_with_adapter()
        stores = {"feedback": feedback, "members": members, "audit": audit}
        try:
            row = await feedback.submit(OWNER, BODY)
            assert row.id
            listing = payload(await admin_members(request(db, stores, user=OTHER)))
            assert listing["ok"] is True
            rows = {m["id"]: m for m in listing["members"]}
            me = rows[OWNER]
            assert me["email"] == "fixture@example.test"  # 관리자는 이메일을 본다
            assert me["tier"] == "FREE"
            assert me["ai_tester"] is False
            assert me["feedback_count"] == 1
            assert "created_at" in me and "last_activity" in me
            # 검색: 이메일 한 조각으로 찾는다.
            searched = payload(await admin_members(
                request(db, stores, user=OTHER, query='query=usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')))
            assert [m["id"] for m in searched["members"]] == [OWNER]
        finally:
            db.close()
    asyncio.run(scenario())


def test_member_detail_counts_and_the_view_is_audited():
    async def scenario():
        db, feedback, members, audit = _stores_with_adapter()
        stores = {"feedback": feedback, "members": members, "audit": audit}
        try:
            row = await feedback.submit(OWNER, BODY)
            before = payload(await admin_ops_audit(request(db, stores, user=OTHER)))
            detail = await admin_member_detail(
                request(db, stores, user=OTHER, member_id=OWNER))
            assert detail.status_code == 200
            member = payload(detail)["member"]
            assert member["feedback_count"] == 1
            assert member["conversation_count"] == 0
            assert member["pc_link_count"] == 0
            assert member["email"] == "fixture@example.test"
            assert [f["body"] for f in member["feedback"]] == [BODY]
            after = payload(await admin_ops_audit(request(db, stores, user=OTHER)))
            views = [row for row in after["audit"]
                     if row["action"] == "member_detail_view"]
            assert len(views) == len(before["audit"]) + 1
            assert views[0]["actor_user_id"] == OTHER
            assert views[0]["target_id"] == OWNER
        finally:
            db.close()
    asyncio.run(scenario())


def test_unknown_member_answers_404():
    async def scenario():
        db, feedback, members, audit = _stores_with_adapter()
        stores = {"feedback": feedback, "members": members, "audit": audit}
        try:
            missing = await admin_member_detail(
                request(db, stores, user=OTHER,
                        member_id='usr_' + 'c' * 32))
            assert missing.status_code == 404
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 3. the audit trail ----------------------------------------------------

def test_feedback_status_change_leaves_one_audit_row():
    async def scenario():
        db, feedback, members, audit = _stores_with_adapter()
        stores = {"feedback": feedback, "members": members, "audit": audit}
        try:
            row = await feedback.submit(OWNER, BODY)
            feedback_id = row.id
            changed = await admin_feedback_status(
                request(db, stores, method='PATCH', user=OTHER,
                        feedback_id=feedback_id,
                        path='/api/admin/feedback/' + feedback_id,
                        body={'status': 'fixed'}))
            assert changed.status_code == 200
            rows = await audit.list_recent(limit=20)
            mine = [row for row in rows
                    if row["action"] == "feedback_status"
                    and row["target_id"] == feedback_id]
            assert len(mine) == 1
            assert mine[0]["actor_user_id"] == OTHER
            assert mine[0]["detail"] == {"to": "fixed"}
        finally:
            db.close()
    asyncio.run(scenario())


def test_operations_tool_leaves_the_same_audit_rows():
    """기존 의견 도구도 같은 기록을 남긴다 — actor 는 도구 고정 식별자."""
    tool_spec = importlib.util.spec_from_file_location(
        "feedback_ops_tool",
        Path(__file__).resolve().parents[1] / "tools" / "feedback_ops.py")
    tool = importlib.util.module_from_spec(tool_spec)
    tool_spec.loader.exec_module(tool)
    from app.d1_sqlite import SqliteD1

    async def scenario():
        db, feedback = database(full=True)
        audit = OpsAuditStore(SqliteD1(db))
        try:
            row = await feedback.submit(OWNER, BODY)
            feedback_id = row.id
            result = await tool.run_feedback(
                feedback, feedback_id, status='reviewing', apply=True,
                audit=audit)
            assert result["error"] is None
            rows = await audit.list_recent(limit=20)
            mine = [row for row in rows
                    if row["action"] == "feedback_status"
                    and row["target_id"] == feedback_id]
            assert len(mine) == 1
            assert mine[0]["actor_user_id"] == "ops-tool"
            assert mine[0]["detail"] == {"to": "reviewing"}
        finally:
            db.close()
    asyncio.run(scenario())


# ---- 4. browser: guests make zero ops calls --------------------------------

ADMIN_ITEM = {
    "id": "fb_0000000000000000000000000000aa02", "body": "본문", "screen": None,
    "status": "new", "created_at": "2026-11-19T03:00:00.000Z",
    "updated_at": "2026-11-19T03:00:00.000Z", "fixed_version": 0,
    "unread_fixed": False, "unread_ops_replies": 0, "replies": [], "news": None,
    "sender_user_id": OWNER, "sender_email": "fixture@example.test",
    "sender_label": "••••aaaa", "is_ai_tester": False,
}
ADMIN_SESSION = {"ok": True, "authenticated": True, "role": "ADMIN",
                 "capabilities": {"admin_hub": True}}
GUEST_SESSION = {"ok": True, "authenticated": False, "role": None,
                 "capabilities": {}}


class _AdminServer:
    def __init__(self):
        import http.server
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
    page.route(re.compile(r".*/api/.*$"),
               lambda route, req: route.fulfill(status=200,
                                                content_type="application/json",
                                                body="{}"))
    page.route(re.compile(r".*/api/admin/session$"),
               lambda route, req: route.fulfill(status=200,
                                                content_type="application/json",
                                                body=json.dumps(session_body)))
    page.route(re.compile(r".*/api/admin/feedback(\?.*)?$"),
               lambda route, req: route.fulfill(status=200,
                                                content_type="application/json",
                                                body=json.dumps(
                                                    {"ok": True,
                                                     "feedback": [ADMIN_ITEM],
                                                     "next_cursor": None})))
    page.route(re.compile(r".*/api/admin/members(\?.*)?$"),
               lambda route, req: route.fulfill(status=200,
                                                content_type="application/json",
                                                body=json.dumps({"ok": True,
                                                                 "members": [],
                                                                 "next_cursor": None})))
    page.route(re.compile(r".*/api/admin/ops-audit(\?.*)?$"),
               lambda route, req: route.fulfill(status=200,
                                                content_type="application/json",
                                                body=json.dumps({"ok": True,
                                                                 "audit": []})))


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_opened_detail_hides_the_member_list():
    """상세가 열리면 목록은 화면에서 사라진다(hidden 디스플레이 override 금지)."""
    import http.server
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *args):
            pass
    MEMBER_ID = "usr_" + "a" * 32
    SESSION = {"ok": True, "authenticated": True, "role": "ADMIN",
               "capabilities": {"admin_hub": True}}
    MEMBERS = [{"id": MEMBER_ID, "display_name": "QA 테스터",
                "email": "qa@example.test", "created_at":
                "2026-10-02T09:12:00.000Z", "ai_tester": True, "tier": "PRO",
                "feedback_count": 3,
                "last_activity": "2026-11-19T04:10:00.000Z"}]
    DETAIL = {"id": MEMBER_ID, "display_name": "QA 테스터",
              "email": "qa@example.test",
              "created_at": "2026-10-02T09:12:00.000Z", "ai_tester": True,
              "tier": "PRO", "feedback_count": 3, "conversation_count": 12,
              "pc_link_count": 1, "last_activity": "2026-11-19T04:10:00.000Z",
              "feedback": []}
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{web.server_address[1]}/admin.html"
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.route(re.compile(r".*/api/.*$"),
                       lambda r, q: r.fulfill(status=200,
                                              content_type="application/json",
                                              body="{}"))
            page.route(re.compile(r".*/api/admin/session$"),
                       lambda r, q: r.fulfill(status=200,
                                              content_type="application/json",
                                              body=json.dumps(SESSION)))
            page.route(re.compile(r".*/api/admin/members(\?.*)?$"),
                       lambda r, q: r.fulfill(status=200,
                                              content_type="application/json",
                                              body=json.dumps({"ok": True,
                                                               "members": MEMBERS,
                                                               "next_cursor": None})))
            page.route(re.compile(r".*/api/admin/members/.+$"),
                       lambda r, q: r.fulfill(status=200,
                                              content_type="application/json",
                                              body=json.dumps({"ok": True,
                                                               "member": DETAIL})))
            page.goto(base + "?theme=light", wait_until="domcontentloaded",
                      timeout=30000)
            page.click("#opsTabMembers")
            page.wait_for_selector("#opsMembersList li", timeout=15000)
            page.locator(".ops-member-open").first.click()
            page.wait_for_selector("#opsMemberDetail:not([hidden])",
                                   timeout=15000)
            display_none = page.evaluate(
                "() => getComputedStyle(document.getElementById('opsMembersList'))"
                ".display === 'none'")
            browser.close()
    finally:
        web.shutdown()
    assert display_none, "the opened detail must hide the member list"


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_administrator_sees_the_members_tab_and_guest_makes_zero_calls():
    server = _AdminServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            # 관리자: 회원 탭이 열리고 회원 API 를 부른다.
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            _stub_api(page, ADMIN_SESSION)
            admin_member_calls: list[str] = []
            page.on("request", lambda req: admin_member_calls.append(req.url) if
                    "/api/admin/members" in req.url else None)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#opsCenterPanel", timeout=15000)
            page.click("#opsTabMembers")
            page.wait_for_selector("#opsMembersList li", timeout=15000)
            ctx.close()
            # 게스트: 게이트만 — ops API 호출 0건.
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            _stub_api(page, GUEST_SESSION)
            guest_ops_calls: list[str] = []
            page.on("request", lambda req: guest_ops_calls.append(req.url) if
                    ("/api/admin/" in req.url
                     and "/api/admin/session" not in req.url) else None)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("#gatePanel:not([hidden])", timeout=15000)
            page.wait_for_timeout(1200)
            ctx.close()
            browser.close()
    finally:
        server.shutdown()
    assert admin_member_calls, "관리자 회원 탭은 members API 를 부른다"
    assert guest_ops_calls == [], guest_ops_calls[:3]


def test_each_admin_action_leaves_exactly_one_audit_row():
    """① 회원 상세 열람·답글·상태 변경이 각각 정확히 1줄씩 남는다."""
    async def scenario():
        db, feedback = database(full=True)
        stores = {"feedback": feedback,
                  "members": D1OpsMemberStore(SqliteD1(db)),
                  "audit": OpsAuditStore(SqliteD1(db))}
        audit = stores["audit"]
        try:
            row = await feedback.submit(OWNER, BODY)
            feedback_id = row.id
            detail = await admin_member_detail(
                request(db, stores, user=OTHER, member_id=OWNER))
            assert detail.status_code == 200
            changed = await admin_feedback_status(
                request(db, stores, method='PATCH', user=OTHER,
                        feedback_id=feedback_id,
                        path='/api/admin/feedback/' + feedback_id,
                        body={'status': 'fixed'}))
            assert changed.status_code == 200
            replied = await admin_feedback_reply(
                request(db, stores, method='POST', user=OTHER,
                        feedback_id=feedback_id,
                        path='/api/admin/feedback/' + feedback_id + '/replies',
                        body={'body': '운영 답변입니다.'}))
            assert replied.status_code == 201
            rows = await audit.list_recent(limit=50)
            counted: dict = {}
            for row in rows:
                if (row["target_id"] == feedback_id
                        or (row["action"] == "member_detail_view"
                            and row["target_id"] == OWNER)):
                    counted[row["action"]] = counted.get(row["action"], 0) + 1
            assert counted == {"member_detail_view": 1, "feedback_status": 1,
                               "feedback_reply": 1}, counted
        finally:
            db.close()
    asyncio.run(scenario())


def test_audit_records_carry_no_secrets_cookies_or_tokens():
    """② 감사 기록에 비밀값·쿠키·토큰이 안 들어가는지 — 세션 토큰 값·쿠키
    이름·의견 본문·답글 본문이 감사 행 어디에도 남지 않는다."""
    async def scenario():
        db, feedback = database(full=True)
        stores = {"feedback": feedback,
                  "members": D1OpsMemberStore(SqliteD1(db)),
                  "audit": OpsAuditStore(SqliteD1(db))}
        audit = stores["audit"]
        try:
            row = await feedback.submit(OWNER, BODY)
            feedback_id = row.id
            admin_token = sid_session_token(SETTINGS, OTHER)
            detail = await admin_member_detail(
                request(db, stores, user=OTHER, member_id=OWNER))
            assert detail.status_code == 200
            changed = await admin_feedback_status(
                request(db, stores, method='PATCH', user=OTHER,
                        feedback_id=feedback_id,
                        path='/api/admin/feedback/' + feedback_id,
                        body={'status': 'fixed'}))
            assert changed.status_code == 200
            reply_body = '운영 답변 본문은 감사 기록에 남으면 안 되는 문장.'
            replied = await admin_feedback_reply(
                request(db, stores, method='POST', user=OTHER,
                        feedback_id=feedback_id,
                        path='/api/admin/feedback/' + feedback_id + '/replies',
                        body={'body': reply_body}))
            assert replied.status_code == 201
            dump = json.dumps(await audit.list_recent(limit=50),
                              ensure_ascii=False)
            assert admin_token not in dump
            assert SESSION_COOKIE not in dump and "cookie" not in dump.lower()
            assert "authorization" not in dump.lower() and "token" not in dump.lower()
            assert BODY not in dump and reply_body not in dump
            assert reply_body[:6] not in dump
        finally:
            db.close()
    asyncio.run(scenario())
