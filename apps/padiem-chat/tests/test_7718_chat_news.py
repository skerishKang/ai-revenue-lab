"""#7718 2단계: 새 소식 store, 로그인 화면 route, 도구의 항목 만들기/잇기, 마이그레이션."""
import asyncio
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.d1_sqlite import SqliteD1
from app.local_cpython import apply_migrations
from app.news_routes import news, news_unread
from app.news_store import D1NewsStore
from test_7680_feedback_routes import BASE, SETTINGS
from test_7680_feedback_store import BODY, OTHER, OWNER, database

TOOL_PATH = Path(__file__).resolve().parents[1] / "tools" / "feedback_ops.py"
SPEC = importlib.util.spec_from_file_location("feedback_ops_7718_news", TOOL_PATH)
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)
FB = "fb_" + "a" * 32


def news_database():
    db, store = database()
    return db, store, D1NewsStore(SqliteD1(db))


def request(path='/api/chat/news', *, store, user=OWNER, query=''):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), news_store=store)
    headers = [(b'content-type', b'application/json')]
    if user:
        token = create_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    return Request({'type': 'http', 'method': 'GET', 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {}}, receive)


def payload(response):
    return json.loads(response.body)


def test_migration_119_adds_news_table_link_and_seen_column():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    try:
        apply_migrations(db)
        news_columns = {row[1] for row in db.execute("PRAGMA table_info(product_news)")}
        assert news_columns == {'number', 'kind', 'title', 'detail', 'source', 'published_at'}
        feedback_columns = {row[1] for row in db.execute("PRAGMA table_info(product_feedback)")}
        assert 'news_number' in feedback_columns
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        assert 'news_read_at' in user_columns
    finally:
        db.close()


def test_create_list_get_and_validation():
    async def scenario():
        db, _, news = news_database()
        try:
            first = await news.create('improved', 'title one', 'detail one', 'none')
            second = await news.create('fixed', 'title two', 'detail two', 'ai_tester')
            assert (first.number, second.number) == (1, 2)
            rows = await news.list_recent()
            assert [row.number for row in rows] == [2, 1]
            assert rows[0].public()['source'] == 'ai_tester'
            assert rows[0].public()['kind'] == 'fixed'
            assert (await news.get(2)).title == 'title two'
            assert await news.get(99) is None
            for kind, title, detail, source in (
                    ('new', 't', 'd', 'none'), ('fixed', 't', 'd', 'team'),
                    ('fixed', '', 'd', 'none'), ('fixed', 'x' * 121, 'd', 'none'),
                    ('fixed', 't', '', 'none'), ('fixed', 't', 'x' * 1001, 'none'),
                    ('fixed', 't\x01', 'd', 'none'), ('fixed', 't', '\ud800', 'none')):
                with pytest.raises(ValueError):
                    await news.create(kind, title, detail, source)
            with pytest.raises(ValueError):
                await news.list_recent(0)
            with pytest.raises(ValueError):
                await news.get(0)
            assert 'title one' not in repr(first) and 'detail one' not in repr(first)
        finally:
            db.close()
    asyncio.run(scenario())


def test_unread_count_uses_the_owner_own_seen_marker():
    async def scenario():
        db, _, news = news_database()
        try:
            for published in ('2026-11-14T09:00:00.000Z', '2026-11-14T10:00:00.000Z'):
                db.execute("INSERT INTO product_news (kind,title,detail,source,published_at) "
                           "VALUES ('fixed','t','d','none',?)", (published,))
            assert await news.unread_count(OWNER) == 2
            await news.mark_seen(OWNER, now='2026-11-14T09:30:00.000Z')
            assert await news.unread_count(OWNER) == 1
            assert await news.unread_count(OTHER) == 2
            await news.mark_seen(OWNER, now='2026-11-14T11:00:00.000Z')
            assert await news.unread_count(OWNER) == 0
            with pytest.raises(ValueError):
                await news.unread_count('')
            with pytest.raises(ValueError):
                await news.mark_seen('')
        finally:
            db.close()
    asyncio.run(scenario())


def test_link_feedback_exposes_the_item_without_user_values():
    async def scenario():
        db, store, news = news_database()
        try:
            row = await store.submit(OWNER, BODY)
            item = await news.create('fixed', 'title link', 'detail link', 'user')
            assert await news.link_feedback(row.id, item.number) is True
            record = await store.get_record(row.id)
            assert record.news_number == item.number
            assert record.public()['news'] == {'number': item.number, 'kind': 'fixed',
                                               'title': 'title link'}
            mine = (await store.list_entries(user_id=OWNER))[0][0]
            assert mine.public()['news']['number'] == item.number
            assert 'title link' not in repr(record)
            assert await news.link_feedback(row.id, 99) is False
            assert await news.link_feedback("fb_" + "c" * 32, item.number) is False
            with pytest.raises(ValueError):
                await news.link_feedback('bad', 1)
            with pytest.raises(ValueError):
                await news.link_feedback(row.id, 0)
            unlinked = await store.submit(OTHER, 'second fixture')
            assert (await store.get_record(unlinked.id)).public()['news'] is None
            assert OWNER not in json.dumps(item.public())
        finally:
            db.close()
    asyncio.run(scenario())


def test_routes_require_login_mark_seen_only_on_the_list_and_close_params():
    async def scenario():
        db, _, news_store = news_database()
        try:
            await news_store.create('improved', 'route title', 'route detail', 'none')
            guest = await news(request(store=news_store, user=None))
            assert guest.status_code == 401
            assert 'no-store' in guest.headers['cache-control']
            state_only = await news_unread(request('/api/chat/news/unread', store=news_store))
            assert payload(state_only)['unread_count'] == 1
            still = await news_unread(request('/api/chat/news/unread', store=news_store))
            assert payload(still)['unread_count'] == 1  # the counter never marks
            body = payload(await news(request(store=news_store)))
            assert body['ok'] is True and body['unread_count'] == 1
            assert body['news'][0]['title'] == 'route title'
            assert payload(await news_unread(request('/api/chat/news/unread', store=news_store)))['unread_count'] == 0
            assert (await news(request(store=None))).status_code == 503
            assert (await news_unread(request('/api/chat/news/unread', store=None))).status_code == 503
            assert (await news(request(store=news_store, query='limit=5'))).status_code == 400
            assert (await news_unread(request('/api/chat/news/unread', store=news_store, query='x=1'))).status_code == 400
            assert payload(await news_unread(request('/api/chat/news/unread', store=news_store, user=None)))['ok'] is False
        finally:
            db.close()
    asyncio.run(scenario())


class FakeNewsStore:
    def __init__(self):
        self.created, self.links, self.items = [], [], {}

    async def create(self, kind, title, detail, source):
        self.created.append((kind, title, detail, source))
        number = len(self.created)
        self.items[number] = SimpleNamespace(number=number)
        return SimpleNamespace(number=number)

    async def get(self, number):
        return self.items.get(number)

    async def link_feedback(self, feedback_id, number):
        self.links.append((feedback_id, number))
        return True


class FakeFeedbackStore:
    def __init__(self, record=None):
        self.record = record if record is not None else SimpleNamespace(status='new', news_number=None)
        self.status_writes = []

    async def get_record(self, feedback_id, **kwargs):
        return self.record

    async def set_status(self, feedback_id, status):
        self.status_writes.append((feedback_id, status))
        return self.record


def test_tool_news_create_preview_and_apply_never_echo_values():
    store = FakeNewsStore()
    preview = asyncio.run(TOOL.run_news_create(store, kind='improved', title='private title',
                                               detail='private detail', source='none'))
    assert store.created == []
    assert preview['lines'] == ['news=pending', 'ok=true']
    applied = asyncio.run(TOOL.run_news_create(store, kind='fixed', title='private title',
                                               detail='private detail', source='user', apply=True))
    assert store.created == [('fixed', 'private title', 'private detail', 'user')]
    assert applied['lines'] == ['news=1', 'ok=true']
    assert 'private title' not in preview['lines'] + applied['lines']
    assert 'private detail' not in preview['lines'] + applied['lines']
    for kwargs in ({'kind': 'new', 'title': 't', 'detail': 'd', 'source': 'none'},
                   {'kind': 'fixed', 'title': 't', 'detail': 'd', 'source': 'team'},
                   {'kind': 'fixed', 'title': '', 'detail': 'd', 'source': 'none'},
                   {'kind': 'fixed', 'title': 'x' * 121, 'detail': 'd', 'source': 'none'},
                   {'kind': 'fixed', 'title': 't', 'detail': '', 'source': 'none'}):
        with pytest.raises(TOOL.ToolError):
            asyncio.run(TOOL.run_news_create(store, **kwargs))


def test_tool_news_link_preview_apply_and_bounded_failures():
    news_store, feedback = FakeNewsStore(), FakeFeedbackStore()
    asyncio.run(TOOL.run_news_create(news_store, kind='fixed', title='t', detail='d', source='none', apply=True))
    preview = asyncio.run(TOOL.run_news_link(news_store, feedback, FB, 1))
    assert feedback.status_writes == [] and news_store.links == []
    assert preview['lines'] == [f'feedback={FB}', 'news=none', 'ok=true']
    applied = asyncio.run(TOOL.run_news_link(news_store, feedback, FB, 1, status='fixed', apply=True))
    assert feedback.status_writes == [(FB, 'fixed')]
    assert news_store.links == [(FB, 1)]
    assert applied['lines'] == [f'feedback={FB}', 'news=1', 'ok=true']
    missing_news = asyncio.run(TOOL.run_news_link(news_store, FakeFeedbackStore(), FB, 5, apply=True))
    assert missing_news['error'] == 'NEWS_NOT_FOUND' and news_store.links == [(FB, 1)]

    class RefusingNews(FakeNewsStore):
        async def link_feedback(self, feedback_id, number):
            return False
    refusing = RefusingNews()
    asyncio.run(TOOL.run_news_create(refusing, kind='fixed', title='t', detail='d', source='none', apply=True))
    refused = asyncio.run(TOOL.run_news_link(refusing, FakeFeedbackStore(), FB, 1, apply=True))
    assert refused['error'] == 'FEEDBACK_NOT_FOUND'
    for args in ((FB, 0), ('bad', 1), (FB, 'x')):
        with pytest.raises(TOOL.ToolError):
            asyncio.run(TOOL.run_news_link(news_store, feedback, *args))
    with pytest.raises(TOOL.ToolError):
        asyncio.run(TOOL.run_news_link(news_store, feedback, FB, 1, status='wrong'))
    with pytest.raises(TOOL.ToolError):
        asyncio.run(TOOL.run_feedback(FakeFeedbackStore(SimpleNamespace(status='new', is_ai_tester=False)), FB))


def test_tool_main_gates_news_flags(monkeypatch, capsys):
    for name, value in (('_assert_root', lambda: None), ('_load_env_file', lambda path: None),
                        ('_use_deployed_tree', lambda: None), ('_become_service_user', lambda: None)):
        monkeypatch.setattr(TOOL, name, value)
    monkeypatch.setattr(TOOL, '_load_state', lambda: SimpleNamespace(news_store=None, feedback_store=None))
    assert TOOL.main(['--news-create', '--news-kind', 'fixed', '--news-title', 't',
                      '--news-detail', 'd', '--news-source', 'none']) == 1
    assert 'STOP NEWS_STORE_UNAVAILABLE' in capsys.readouterr().out
    assert TOOL.main(['--news-link', '1']) == 1
    assert 'STOP FEEDBACK_ID_REQUIRED' in capsys.readouterr().out
    assert TOOL.main(['--news-create', '--feedback-id', FB, '--news-kind', 'fixed',
                      '--news-title', 't', '--news-detail', 'd', '--news-source', 'none']) == 1
    assert 'STOP NOT_APPLICABLE' in capsys.readouterr().out
    assert TOOL.main(['--news-link', '1', '--reply', 'x']) == 1
    assert 'STOP NOT_APPLICABLE' in capsys.readouterr().out

    news_store = FakeNewsStore()
    title = 'marker-title-7718'
    monkeypatch.setattr(TOOL, '_load_state', lambda: SimpleNamespace(news_store=news_store,
                                                                    feedback_store=FakeFeedbackStore()))
    assert TOOL.main(['--news-create', '--news-kind', 'improved', '--news-title', title,
                      '--news-detail', 'marker-detail-7718', '--news-source', 'none', '--apply']) == 0
    out = capsys.readouterr().out
    assert 'news=1' in out and 'ok=true' in out
    assert title not in out and 'marker-detail-7718' not in out
    assert TOOL.main(['--feedback-id', FB, '--news-link', '1', '--status', 'fixed', '--apply']) == 0
    out = capsys.readouterr().out
    assert f'feedback={FB}' in out and 'news=1' in out
