"""#8035 ③ (#7718 흡수) — 회차 점수 입력·사용 일지 계약.

다섯 가지:

  1. 권한 — 관리자만 열린다(일반 회원 403, 게스트 401). 입력·수정·숨김도 같다.
  2. 감사 — 열람·입력·수정·숨김이 각각 ops_audit_log 한 줄을 남긴다.
  3. 동작 — 같은 고객·회차 중복은 409, 점수 범위 밖은 400, 숨긴 줄은 목록·집계에서
     빠지고 다시 고칠 수 없다(행은 남는다).
  4. 집계 — 기간별 평균·회차 수·고객별 흐름이 입력한 값과 정확히 같다.
  5. 노출 — 게스트가 /admin 을 열면 운영센터 /api/* 호출이 0건이다.
"""
import asyncio
import json
import secrets
import threading
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.ops_audit_store import OpsAuditStore
from app.ops_member_store import D1OpsMemberStore
from app.ops_round_score_routes import (
    admin_round_score_create,
    admin_round_score_hide,
    admin_round_score_update,
    admin_round_scores,
)
from app.ops_round_score_store import D1OpsRoundScoreStore
from app.usage_log_routes import admin_usage_log
from _support.ops_audit_helpers import AdminAuthority, OWNER, OTHER, database

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

BASE = 'https://chat.example.test'
# 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=secrets.token_urlsafe(32))
STATIC = Path(__file__).resolve().parents[1] / 'static'
PERSONA = 'AI 정호'
DAY = '2026-11-19'


def _stores():
    db, feedback = database(full=True)
    adapter = SqliteD1(db)
    return (db, feedback, D1OpsMemberStore(adapter), OpsAuditStore(adapter),
            D1OpsRoundScoreStore(adapter))


def _req(stores, *, method='GET', user=OTHER, path='/api/admin/round-scores',
         score_id='', query='', body=None):
    db, feedback, members, audit, scores = stores
    state = SimpleNamespace(settings=SETTINGS, history_store=object(),
                            feedback_store=feedback, ops_member_store=members,
                            ops_audit_store=audit, ops_round_score_store=scores,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json'), (b'origin', BASE.encode())]
    if user:
        from sid_session_helper import sid_session_token
        token = sid_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = json.dumps(body if body is not None else {}, ensure_ascii=False).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state),
                    'path_params': {'score_id': score_id}}, receive)


def payload(response):
    return json.loads(response.body)


def entry(**overrides):
    data = {'persona_name': PERSONA, 'round_no': 1, 'round_on': DAY,
            'source': 'ai', 'return_score': 4, 'pretty_score': 5, 'memo': '좋음'}
    data.update(overrides)
    return data


async def _create(stores, **overrides):
    response = await admin_round_score_create(
        _req(stores, method='POST', body=entry(**overrides)))
    assert response.status_code == 200, payload(response)
    return payload(response)['score']


def _audit_rows(rows, action, target_id=None):
    return [row for row in rows if row['action'] == action
            and (target_id is None or row['target_id'] == target_id)]


# ---- 1. permission ---------------------------------------------------------

def test_every_round_score_endpoint_answers_only_to_the_administrator():
    async def scenario():
        stores = _stores()
        try:
            row = await _create(stores)
            calls = [
                (admin_round_scores, 'GET', ''),
                (admin_round_score_create, 'POST', ''),
                (admin_round_score_update, 'PATCH', row['id']),
                (admin_round_score_hide, 'DELETE', row['id']),
            ]
            for handler, method, score_id in calls:
                body = entry(return_score=3) if method in {'POST', 'PATCH'} else None
                member = await handler(_req(stores, method=method, user=OWNER,
                                            score_id=score_id, body=body))
                assert member.status_code == 403, (method, payload(member))
                assert payload(member)['error']['code'] == 'global_model_admin_forbidden'
                guest = await handler(_req(stores, method=method, user=None,
                                           score_id=score_id, body=body))
                assert guest.status_code == 401, (method, payload(guest))
                assert payload(guest)['error']['code'] == 'authentication_required'
            # 거부된 호출은 아무것도 바꾸지 않았고 감사 줄도 남기지 않았다.
            scores = stores[4]
            unchanged = await scores.get(row['id'])
            assert unchanged['return_score'] == 4
            assert unchanged['hidden'] is False
            rows = await stores[3].list_recent(limit=50)
            assert len(_audit_rows(rows, 'round_score_create')) == 1
            assert _audit_rows(rows, 'round_score_update') == []
            assert _audit_rows(rows, 'round_score_hide') == []
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_the_usage_log_summary_stays_administrator_only():
    async def scenario():
        stores = _stores()
        try:
            for user, status in ((OWNER, 403), (None, 401)):
                answer = await admin_usage_log(_req(stores, user=user,
                                                    path='/api/admin/usage-log'))
                assert answer.status_code == status
        finally:
            stores[0].close()
    asyncio.run(scenario())


# ---- 2. audit --------------------------------------------------------------

def test_view_create_update_and_hide_each_leave_one_audit_row():
    async def scenario():
        stores = _stores()
        try:
            created = await _create(stores)
            score_id = created['id']
            listed = await admin_round_scores(_req(stores, query='days=30'))
            assert listed.status_code == 200
            patched = await admin_round_score_update(
                _req(stores, method='PATCH', score_id=score_id,
                     body={'return_score': 2, 'memo': '다시 봄'}))
            assert patched.status_code == 200
            hidden = await admin_round_score_hide(
                _req(stores, method='DELETE', score_id=score_id))
            assert hidden.status_code == 200
            rows = await stores[3].list_recent(limit=50)
            for action in ('round_score_create', 'round_score_view',
                           'round_score_update', 'round_score_hide'):
                mine = _audit_rows(rows, action)
                assert len(mine) == 1, (action, rows)
                assert mine[0]['actor_user_id'] == OTHER
            assert _audit_rows(rows, 'round_score_create')[0]['target_id'] == score_id
            assert _audit_rows(rows, 'round_score_update')[0]['detail'] == {
                'fields': ['memo', 'return_score']}
            assert _audit_rows(rows, 'round_score_hide')[0]['target_id'] == score_id
            assert _audit_rows(rows, 'round_score_view')[0]['detail'] == {
                'days': 30, 'persona': False}
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_audit_detail_carries_scores_but_no_account_values():
    async def scenario():
        stores = _stores()
        try:
            row = await _create(stores)
            rows = await stores[3].list_recent(limit=20)
            detail = _audit_rows(rows, 'round_score_create', row['id'])[0]['detail']
            assert detail['return'] == 4 and detail['pretty'] == 5
            assert detail['persona'] == PERSONA
            blob = json.dumps(rows, ensure_ascii=False)
            assert OWNER not in blob
            assert 'fixture@example.test' not in blob
            assert SESSION_COOKIE not in blob
        finally:
            stores[0].close()
    asyncio.run(scenario())


# ---- 3. behaviour ----------------------------------------------------------

def test_the_same_customer_round_cannot_be_entered_twice():
    async def scenario():
        stores = _stores()
        try:
            await _create(stores)
            again = await admin_round_score_create(_req(stores, method='POST',
                                                        body=entry()))
            assert again.status_code == 409
            assert payload(again)['error']['code'] == 'ops_round_score_conflict'
            # 회차가 다르면 같은 고객도 새로 들어간다.
            other = await _create(stores, round_no=2)
            assert other['round_no'] == 2
        finally:
            stores[0].close()
    asyncio.run(scenario())


@pytest.mark.parametrize('bad', [
    {'return_score': 0}, {'return_score': 6}, {'pretty_score': 9},
    {'pretty_score': True}, {'round_no': 0}, {'round_on': '2026-13-40'},
    {'round_on': '19/11/2026'}, {'source': 'robot'}, {'persona_name': '  '},
    {'memo': 'x' * 401},
])
def test_values_outside_the_rule_are_refused(bad):
    async def scenario():
        stores = _stores()
        try:
            answer = await admin_round_score_create(
                _req(stores, method='POST', body=entry(**bad)))
            assert answer.status_code == 400, payload(answer)
            assert payload(answer)['error']['code'] == 'ops_round_score_invalid_request'
            rows = await stores[3].list_recent(limit=20)
            assert _audit_rows(rows, 'round_score_create') == []
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_hiding_keeps_the_row_but_drops_it_from_list_and_totals():
    async def scenario():
        stores = _stores()
        try:
            row = await _create(stores)
            kept = await _create(stores, round_no=2, return_score=2, pretty_score=4)
            hidden = await admin_round_score_hide(
                _req(stores, method='DELETE', score_id=row['id']))
            assert payload(hidden)['score']['hidden'] is True
            listed = payload(await admin_round_scores(_req(stores)))
            assert [item['id'] for item in listed['scores']] == [kept['id']]
            assert listed['journal']['rounds'] == 1
            assert listed['journal']['return_avg'] == 2.0
            # 행은 남아 있다(감사 이력과 함께). 다시 고치거나 숨길 수는 없다.
            stored = await stores[4].get(row['id'])
            assert stored['hidden'] is True
            retry = await admin_round_score_update(
                _req(stores, method='PATCH', score_id=row['id'],
                     body={'return_score': 5}))
            assert retry.status_code == 404
            twice = await admin_round_score_hide(
                _req(stores, method='DELETE', score_id=row['id']))
            assert twice.status_code == 404
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_editing_a_round_keeps_one_row_and_changes_the_value():
    async def scenario():
        stores = _stores()
        try:
            row = await _create(stores)
            answer = await admin_round_score_update(
                _req(stores, method='PATCH', score_id=row['id'],
                     body={'return_score': 1, 'pretty_score': 2}))
            changed = payload(answer)['score']
            assert changed['id'] == row['id']
            assert (changed['return_score'], changed['pretty_score']) == (1, 2)
            listed = payload(await admin_round_scores(_req(stores)))
            assert len(listed['scores']) == 1
            assert listed['journal']['return_avg'] == 1.0
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_an_unknown_field_or_missing_row_is_refused():
    async def scenario():
        stores = _stores()
        try:
            row = await _create(stores)
            extra = await admin_round_score_update(
                _req(stores, method='PATCH', score_id=row['id'],
                     body={'hidden': True}))
            assert extra.status_code == 400
            missing = await admin_round_score_update(
                _req(stores, method='PATCH', score_id='opsrs_' + 'f' * 32,
                     body={'return_score': 3}))
            assert missing.status_code == 404
        finally:
            stores[0].close()
    asyncio.run(scenario())


# ---- 4. totals -------------------------------------------------------------

def test_the_journal_totals_and_per_customer_trend_match_the_entries():
    async def scenario():
        stores = _stores()
        try:
            await _create(stores, round_no=1, round_on='2026-11-10',
                          return_score=3, pretty_score=4)
            await _create(stores, round_no=2, round_on='2026-11-12',
                          return_score=5, pretty_score=4)
            await _create(stores, persona_name='실제 고객', source='human',
                          round_no=1, round_on='2026-11-13',
                          return_score=2, pretty_score=3)
            answer = payload(await admin_round_scores(_req(stores, query='days=365')))
            journal = answer['journal']
            assert journal['rounds'] == 3
            assert journal['return_avg'] == round((3 + 5 + 2) / 3, 2)
            assert journal['pretty_avg'] == round((4 + 4 + 3) / 3, 2)
            people = {person['persona']: person for person in journal['personas']}
            assert set(people) == {PERSONA, '실제 고객'}
            mine = people[PERSONA]
            assert mine['rounds'] == 2
            assert mine['latest_score'] == 5
            assert mine['latest_on'] == '2026-11-12'
            assert [item['score'] for item in mine['entries']] == [3, 5]
            assert [item['at'] for item in mine['entries']] == ['2026-11-10', '2026-11-12']
            assert people['실제 고객']['source'] == 'human'
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_the_period_window_keeps_older_rounds_out():
    async def scenario():
        stores = _stores()
        try:
            await _create(stores, round_no=1, round_on='2020-01-01', return_score=1)
            recent = await _create(stores, round_no=2, round_on='2099-01-01',
                                   return_score=5)
            answer = payload(await admin_round_scores(_req(stores, query='days=30')))
            assert answer['journal']['rounds'] == 1
            assert answer['journal']['return_avg'] == 5.0
            assert recent['round_no'] == 2
            wide = payload(await admin_round_scores(_req(stores, query='days=365')))
            assert wide['journal']['days'] == 365
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_a_bad_period_is_refused_and_a_customer_filter_narrows_the_list():
    async def scenario():
        stores = _stores()
        try:
            await _create(stores)
            await _create(stores, persona_name='다른 고객', round_no=1)
            bad = await admin_round_scores(_req(stores, query='days=0'))
            assert bad.status_code == 400
            unknown = await admin_round_scores(_req(stores, query='limit=5'))
            assert unknown.status_code == 400
            mine = payload(await admin_round_scores(
                _req(stores, query='persona=' + quote(PERSONA))))
            assert [item['persona_name'] for item in mine['scores']] == [PERSONA]
        finally:
            stores[0].close()
    asyncio.run(scenario())


def test_the_usage_log_now_carries_the_return_average_and_round_rows():
    async def scenario():
        stores = _stores()
        try:
            empty = payload(await admin_usage_log(
                _req(stores, path='/api/admin/usage-log')))
            by_key = {item['key']: item['value'] for item in empty['metrics']}
            assert by_key['return'] is None
            assert empty['rows'] == []
            await _create(stores, round_no=1, return_score=4, pretty_score=5)
            await _create(stores, round_no=2, round_on='2099-01-01',
                          return_score=2, pretty_score=3)
            filled = payload(await admin_usage_log(
                _req(stores, path='/api/admin/usage-log')))
            values = {item['key']: item['value'] for item in filled['metrics']}
            assert values['return'] == 3.0
            assert len(filled['rows']) == 1
            row = filled['rows'][0]
            assert row['persona'] == PERSONA
            assert row['grade'] == 'AI 고객'
            assert [item['score'] for item in row['entries']] == [5, 3]
        finally:
            stores[0].close()
    asyncio.run(scenario())


# ---- 5. guest exposure -----------------------------------------------------

@pytest.mark.skipif(sync_playwright is None, reason='playwright is not installed')
def test_a_guest_on_admin_triggers_no_ops_center_api_calls():
    """게스트는 게이트만 본다 — 점수·일지 탭을 눌러도 ops API 호출이 0건."""
    import http.server
    import re

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    calls: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = ctx.new_page()
            page.route(re.compile(r'.*/api/admin/session$'),
                       lambda route, req: route.fulfill(
                           status=200, content_type='application/json',
                           body=json.dumps({'ok': True, 'authenticated': True,
                                            'is_admin': False})))
            page.route(re.compile(r'.*/api/.*$'),
                       lambda route, req: route.fulfill(
                           status=200, content_type='application/json', body='{}'))
            page.on('request', lambda req: calls.append(req.url)
                    if ('/api/admin/' in req.url
                        and '/api/admin/session' not in req.url) else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/admin.html',
                      wait_until='domcontentloaded', timeout=30000)
            page.wait_for_selector('#gatePanel:not([hidden])', timeout=15000)
            page.wait_for_timeout(1200)
            # 게이트가 닫혀 있어도 탭 단추를 강제로 눌러 본다(화면 우회 시도).
            page.evaluate("() => { document.getElementById('opsTabScores').click();"
                          " document.getElementById('opsTabJournal').click(); }")
            page.wait_for_timeout(800)
            ctx.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert calls == [], calls[:3]