"""#7839 — 북AI 사이트 의견 창구: 공개 접수·거절·한도·알림·받은함 라벨·화면 넘침."""
from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.ops_alert_store import D1OpsAlertStore
from app.site_feedback_routes import admin_site_feedback, site_feedback
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database

ROOT = Path(__file__).resolve().parents[1]
BOOKAI = ROOT.parent / "bookai" / "public"
SECRET = secrets.token_urlsafe(32)
SETTINGS = Settings(auth_mode="password", public_base_url="https://chat.example.test",
                    session_secret=SECRET, site_feedback_daily_limit=2)
ORIGIN = "https://bookai.padiem.net"
ADMIN = "usr_" + "b" * 32


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == ADMIN


def request(store, *, body=None, origin=ORIGIN, ip="203.0.113.9", alert_store=None,
            user=None, method="POST"):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(),
                            site_feedback_store=store, ops_alert_store=alert_store,
                            ops_alert_notifier=None, ops_alert_tasks=set(),
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b"content-type", b"application/json"), (b"origin", origin.encode()),
               (b"cf-connecting-ip", ip.encode()), (b"user-agent", b"fixture")]
    if user:
        token = create_session_token(SETTINGS, user, canonical_session_id="session_test_a")
        headers.append((b"cookie", (SESSION_COOKIE + "=" + token).encode()))

    async def receive():
        return {"type": "http.request",
                "body": json.dumps(body or {}, ensure_ascii=True).encode(),
                "more_body": False}

    return Request({"type": "http", "method": method, "path": "/api/site-feedback",
                    "query_string": b"", "headers": headers,
                    "app": SimpleNamespace(state=state), "path_params": {},
                    "client": (ip, 12345)}, receive)


def payload(response):
    return json.loads(response.body)


def test_bookai_public_submit_allow_deny_limit_and_one_alert(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            alerts = D1OpsAlertStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr("app.site_feedback_routes._now_ms", lambda: now_ms)
            monkeypatch.setattr("app.site_feedback_routes._now_iso",
                                lambda: "2026-11-22T00:00:00Z")
            body = {"site": "bookai", "body": "북AI 의견입니다",
                    "screen": {"url": ORIGIN + "/", "width": 390, "height": 844},
                    "rendered_at": now_ms - 2000, "honeypot": ""}
            created = await site_feedback(request(store, body=body, alert_store=alerts))
            assert created.status_code == 201
            assert payload(created)["feedback"]["site"] == "bookai"
            assert created.headers["access-control-allow-origin"] == ORIGIN
            denied = await site_feedback(request(store, body=body, origin="https://evil.test",
                                                 alert_store=alerts))
            assert denied.status_code == 400
            assert "access-control-allow-origin" not in denied.headers
            again = await site_feedback(request(store, body=body, alert_store=alerts))
            assert again.status_code == 201
            limited = await site_feedback(request(store, body=body, alert_store=alerts))
            assert limited.status_code == 429 and "retry-after" in limited.headers
            inbox = await admin_site_feedback(request(store, user=ADMIN, method="GET"))
            assert inbox.status_code == 200
            entries = payload(inbox)["feedback"]
            assert len(entries) == 2 and all(e["site"] == "bookai" for e in entries)
            listed = await alerts.pending(limit=20)
            site_alerts = [e for e in listed if e["kind"] == "site_feedback"]
            assert len(site_alerts) == 2 and all(e["label"] == "bookai" for e in site_alerts)
        finally:
            db.close()

    asyncio.run(scenario())


def test_admin_ops_labels_bookai():
    source = (ROOT / "static/admin-ops.js").read_text(encoding="utf-8")
    assert 'bookai: "북AI"' in source
    assert '["bookai", "북AI"]' in source
    assert 'siteName("bookai")' not in source  # 라벨은 표에만 둔다


def test_bookai_ui_button_and_form_fit(monkeypatch):
    from playwright.sync_api import sync_playwright
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(BOOKAI), **kw)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_port}/index.html"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in (390, 1440):
                context = browser.new_context(viewport={"width": width, "height": 844})
                def route(route_request):
                    if "127.0.0.1" in route_request.request.url:
                        route_request.continue_()
                    else:
                        route_request.abort()
                context.route("**/*", route)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(600)
                box = page.locator("#bookaiFeedbackOpen").bounding_box()
                assert box is not None
                assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1
                page.click("#bookaiFeedbackOpen")
                assert page.locator("#bookaiFeedbackDialog").is_visible()
                form_box = page.locator("#bookaiFeedbackDialog").bounding_box()
                assert form_box is not None and form_box["x"] >= 0
                assert form_box["x"] + form_box["width"] <= width + 1
                assert page.locator("#bookaiFeedbackBody").is_visible()
                context.close()
            browser.close()
    finally:
        httpd.shutdown()
