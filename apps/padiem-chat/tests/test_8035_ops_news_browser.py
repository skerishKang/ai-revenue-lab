"""Exercise the actual news panel and handlers without a live account or server."""
from __future__ import annotations

import sqlite3

import pytest

from _support.ops_audit_helpers import OWNER, database
from _support.ops_news_browser_server import start_news_server

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

NOW = '2026-11-20T00:00:00.000Z'
FB = 'fb_' + 'd' * 32


@pytest.mark.skipif(sync_playwright is None, reason='playwright is not installed')
def test_admin_news_works_and_guest_news_calls_are_zero(tmp_path, monkeypatch):
    path = tmp_path / 'news.sqlite3'
    db, _ = database(path, full=True)
    db.execute('INSERT INTO product_feedback '
               '(id,user_id,body,created_day,created_at,updated_at) VALUES (?,?,?,?,?,?)',
               (FB, OWNER, '검증 의견', NOW[:10], NOW, NOW))
    db.close()
    monkeypatch.setattr('app.ops_audit_store._now', lambda: NOW)
    server, news_calls = start_news_server(path, NOW)
    url = f'http://127.0.0.1:{server.server_port}/admin.html#ops-news'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            guest = browser.new_page()
            guest.goto(url, wait_until='domcontentloaded')
            guest.wait_for_selector('#gatePanel:not([hidden])')
            guest.evaluate("() => document.getElementById('opsTabNews').click()")
            guest.wait_for_load_state('networkidle')
            assert news_calls == []
            guest.close()
            server.admin = True
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_selector('#opsNewsPane:not([hidden])')
            page.fill('#opsNewsVersion', '2026.11.20')
            page.fill('#opsNewsTitle', '새 소식')
            page.fill('#opsNewsDetail', '설명')
            page.select_option('#opsNewsSource', 'ai_tester')
            page.fill('#opsNewsFeedback', FB)
            page.click('#opsNewsSubmit')
            page.wait_for_selector('#opsNewsList .ops-news-row')
            row = page.locator('#opsNewsList .ops-news-row')
            assert '새 소식' in row.inner_text() and FB in row.inner_text()
            row.get_by_text('고치기', exact=True).click()
            page.fill('#opsNewsTitle', '고친 새 소식')
            page.select_option('#opsNewsSource', 'user')
            page.click('#opsNewsSubmit')
            page.wait_for_function("() => document.getElementById('opsNewsList').innerText.includes('고친 새 소식')")
            assert '사용자 의견' in row.inner_text() and FB in row.inner_text()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute('SELECT number,title,source,published_at FROM product_news').fetchall() == [
            (1, '고친 새 소식', 'user', NOW)]
        assert conn.execute('SELECT news_number FROM product_feedback WHERE id=?', (FB,)).fetchone() == (1,)
        audit = conn.execute("SELECT action FROM ops_audit_log WHERE action IN ('news_create','news_update')").fetchall()
        assert sorted(audit) == [('news_create',), ('news_update',)]
    finally:
        conn.close()
