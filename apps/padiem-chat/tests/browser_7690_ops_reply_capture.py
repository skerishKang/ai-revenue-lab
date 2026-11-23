"""#7690 역방향 — 운영센터 답글 칸 캡처 (테마 5종 × 너비 3종).

고객에게 보일 답글 입력·안내 문구·보내기 실패 다시 보내기 버튼이 다섯
테마에서 깨지지 않는지 눈으로 확인한다. API는 가짜 응답으로 대신한다.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

ADMIN_SESSION = {"ok": True, "authenticated": True, "role": "ADMIN",
                 "capabilities": {"admin_hub": True, "chat_admin": True}}
LOVETREE_ITEM = {
    "id": "sf_" + "a" * 32, "site": "lovetree", "body": "이용 후기 내용입니다",
    "screen": None, "status": "new", "created_at": "2026-11-22T10:00:00Z",
    "updated_at": "2026-11-22T10:00:00Z", "ops_memo": "내부 메모입니다",
    "external_feedback_id": "101", "external_title": "제목입니다",
    "external_category": "bug", "external_account_subject_id": "subj-1",
    "external_is_ai_customer": True, "external_append": None,
    "external_append_created_at": None, "external_created_at": "2026-11-22T10:00:00Z",
    "external_status": "received", "external_status_created_at": "2026-11-22T10:00:00Z",
    "sender_label": "익명",
    "outbox": [
        {"event_key": "ops_outcome_0000000000000000000", "kind": "reply",
         "reply_id": "rpb_reply_000000000000000000", "reply_body": "이미 보낸 답글입니다",
         "reply_created_at": "2026-11-22T11:00:00Z", "status": None,
         "state": "sent", "attempts": 1},
        {"event_key": "ops_state_00000000000000000000", "kind": "status",
         "reply_id": None, "reply_body": None,
         "reply_created_at": None, "status": "received",
         "state": "failed", "attempts": 1},
    ],
}


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


def _stub_api(page):
    page.route(re.compile(r".*/api/.*$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json", body="{}"))
    page.route(re.compile(r".*/api/admin/session$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps(ADMIN_SESSION)))
    page.route(re.compile(r".*/api/admin/feedback(\?.*)?$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "feedback": [],
                                    "next_cursor": None})))
    page.route(re.compile(r".*/api/admin/site-feedback(\?.*)?$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "feedback": [LOVETREE_ITEM],
                                    "next_cursor": None, "sites": ["lovetree"]})))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width,height", [(390, 844), (768, 1024), (1440, 900)])
def test_ops_reply_field_visible_at_theme_and_width(theme, width, height, tmp_path):
    server = _AdminServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": width, "height": height},
                                          locale="ko-KR", reduced_motion="reduce")
            page = context.new_page()
            _stub_api(page)
            page.goto(server.base + f"?theme={theme}#ops-inbox", wait_until="domcontentloaded")
            assert page.locator("html").get_attribute("data-theme") == theme
            reply_box = page.locator("#opsInboxList .ops-row [aria-label=\"고객에게 보일 답글 입력\"]")
            reply_box.wait_for(state="visible", timeout=15000)
            page.locator(".ops-row p", has_text="운영 메모와 다릅니다").first.wait_for(state="visible", timeout=5000)
            page.locator(".ops-row button", has_text="다시 보내기").first.wait_for(state="visible")
            assert page.locator(".ops-row p", has_text="보내기 실패").count() >= 1
            box = reply_box.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, box
            print(f"{theme} {width}: {box}")
            page.screenshot(path=tmp_path / f"ops-reply-{theme}-{width}.png",
                            animations="disabled", full_page=True)
            browser.close()
    finally:
        server.shutdown()
