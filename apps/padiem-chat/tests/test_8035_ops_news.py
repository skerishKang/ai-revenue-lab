"""#8035 ④ — admin news is the CLI's publishing path, with audit and feedback links."""
import asyncio
import json

import pytest

from app.d1_sqlite import SqliteD1
from app.news_store import D1NewsStore
from app.ops_audit_store import OpsAuditStore
from app.ops_news_routes import admin_news_create, admin_news_list, admin_news_update
from app.news_publish import write_news
from _support.ops_audit_helpers import OTHER, OWNER, database, payload, request

NOW = '2026-11-20T00:00:00.000Z'
FB = 'fb_' + 'a' * 32
FB2 = 'fb_' + 'b' * 32
MISSING = 'fb_' + 'c' * 32


@pytest.fixture
def stores(monkeypatch):
    db, feedback = database(full=True)
    for fid in (FB, FB2):
        db.execute('INSERT INTO product_feedback '
                   '(id,user_id,body,created_day,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                   (fid, OWNER, '의견', NOW[:10], NOW, NOW))
    adapter = SqliteD1(db)
    monkeypatch.setattr('app.ops_audit_store._now', lambda: NOW)
    yield db, feedback, D1NewsStore(adapter, now=lambda: NOW), OpsAuditStore(adapter)
    db.close()


def _req(stores, *, method='GET', user=OTHER, number=None, body=None):
    _, feedback, news, audit = stores
    path = '/api/admin/news' + ('/' + str(number) if number is not None else '')
    req = request(feedback, method=method, user=user, body=body, path=path)
    req.app.state.news_store = news
    req.app.state.ops_audit_store = audit
    req.scope['path_params'] = {'number': number}
    return req


def _entry(**changes):
    return {'version': '2026.11.20', 'kind': 'fixed', 'title': '제목',
            'detail': '설명입니다', 'source': 'ai_tester', 'feedback': [FB], **changes}


async def _create(stores, **changes):
    answer = await admin_news_create(_req(stores, method='POST', body=_entry(**changes)))
    assert answer.status_code == 201, payload(answer)
    return payload(answer)['news']


def test_create_edit_list_and_audit_are_same_published_record(stores):
    async def scenario():
        db, feedback, news, audit = stores
        row = await _create(stores)
        assert row['number'] == 1 and row['published_at'] == NOW
        assert row['feedback_ids'] == [FB]
        assert (await feedback.get_record(FB)).news_number == row['number']
        changed = await admin_news_update(_req(
            stores, method='PATCH', number=row['number'],
            body=_entry(title='수정한 제목', source='user', kind='improved', feedback=[FB, FB2])))
        assert changed.status_code == 200
        item = payload(changed)['news']
        assert item == {**row, 'title': '수정한 제목', 'source': 'user', 'kind': 'improved',
                        'feedback_ids': [FB, FB2]}
        assert (await news.get(1)).public() == {k: v for k, v in item.items() if k != 'feedback_ids'}
        assert db.execute('SELECT count(*) FROM product_news').fetchone()[0] == 1
        result = await admin_news_list(_req(stores))
        assert payload(result)['news'] == [item]
        trail = await audit.list_recent()
        assert sorted(r['action'] for r in trail) == ['news_create', 'news_update', 'news_view']
        assert all(r['actor_user_id'] == OTHER and r['created_at'] == NOW for r in trail)
        writes = [r for r in trail if r['action'] != 'news_view']
        assert all(r['target_id'] == '1' and r['detail']['linked_count'] == 1 for r in writes)
    asyncio.run(scenario())


def test_guests_and_members_cannot_list_or_write(stores):
    async def scenario():
        for user, expected in ((None, 401), (OWNER, 403)):
            for handler, method, number in ((admin_news_list, 'GET', None),
                                            (admin_news_create, 'POST', None),
                                            (admin_news_update, 'PATCH', 1)):
                result = await handler(_req(stores, method=method, user=user,
                                            number=number, body=_entry()))
                assert result.status_code == expected
        assert await stores[2].list_recent() == []
        assert await stores[3].list_recent() == []
    asyncio.run(scenario())


@pytest.mark.parametrize('changes,code', [
    ({'source': 'other'}, 'NEWS_SOURCE_INVALID'),
    ({'source': []}, 'NEWS_SOURCE_INVALID'),
    ({'kind': {}}, 'NEWS_KIND_INVALID'),
    ({'version': '2026-11-20'}, 'NEWS_VERSION_INVALID'),
    ({'title': '#123 제목'}, 'NEWS_TITLE_ISSUE_REF'),
    ({'detail': 'qa@example.test'}, 'NEWS_DETAIL_EMAIL'),
    ({'feedback': 'bad'}, 'FEEDBACK_ID_INVALID'),
    ({'feedback': [None]}, 'FEEDBACK_ID_INVALID'),
    ({'feedback': ['bad']}, 'FEEDBACK_ID_INVALID'),
    ({'feedback': [f'fb_{i:032x}' for i in range(21)]}, 'FEEDBACK_TOO_MANY'),
])
def test_invalid_input_is_refused_before_any_write(stores, changes, code):
    async def scenario():
        answer = await admin_news_create(_req(stores, method='POST', body=_entry(**changes)))
        assert answer.status_code == 400
        assert payload(answer)['error']['code'] == code
        assert await stores[2].list_recent() == []
        assert await stores[3].list_recent() == []
    asyncio.run(scenario())


def test_missing_and_already_linked_opinions_do_not_modify_existing_news(stores):
    async def scenario():
        missing = await admin_news_create(
            _req(stores, method='POST', body=_entry(feedback=[MISSING])))
        assert missing.status_code == 404
        first = await _create(stores)
        conflict = await admin_news_create(_req(stores, method='POST', body=_entry()))
        assert conflict.status_code == 409
        patch = await admin_news_update(_req(stores, method='PATCH', number=first['number'],
                                             body=_entry(title='바뀐 제목', feedback=[MISSING])))
        assert patch.status_code == 404
        absent = await admin_news_update(_req(stores, method='PATCH', number=99, body=_entry()))
        assert absent.status_code == 404
        assert (await stores[2].get(1)).title == first['title']
        assert len(await stores[3].list_recent()) == 1
    asyncio.run(scenario())


def test_shared_service_and_route_agree_on_validation_and_persistence(stores):
    async def scenario():
        _, feedback, news, audit = stores
        cli = await write_news(news, feedback, **_entry(source='none', feedback=[FB2]),
                               audit=audit, actor='ops-tool')
        assert cli.error is None and cli.record.number == 1
        via_ui = await admin_news_list(_req(stores))
        assert payload(via_ui)['news'][0]['feedback_ids'] == [FB2]
        assert (await feedback.get_record(FB2)).news_number == 1
        assert any(row['actor_user_id'] == 'ops-tool' for row in await audit.list_recent())
    asyncio.run(scenario())


def test_partial_link_failure_still_audits_saved_record(stores, monkeypatch):
    async def refuse(*args):
        return False

    async def scenario():
        monkeypatch.setattr(stores[2], 'link_feedback', refuse)
        answer = await admin_news_create(_req(stores, method='POST', body=_entry()))
        assert answer.status_code == 503
        assert payload(answer)['news']['number'] == 1
        assert payload(answer)['error']['code'] == 'FEEDBACK_LINK_FAILED'
        rows = await stores[3].list_recent()
        assert len(rows) == 1 and rows[0]['detail']['partial'] is True
        assert (await stores[2].get(1)).title == '제목'
    asyncio.run(scenario())
