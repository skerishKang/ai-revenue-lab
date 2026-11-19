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
PUBLISH_PATH = Path(__file__).resolve().parents[1] / "tools" / "chat_news_publish.py"
PUBLISH_SPEC = importlib.util.spec_from_file_location("chat_news_publish_7847", PUBLISH_PATH)
PUBLISH = importlib.util.module_from_spec(PUBLISH_SPEC)
PUBLISH_SPEC.loader.exec_module(PUBLISH)
FB = "fb_" + "a" * 32
FB2 = "fb_" + "d" * 32


def news_database():
    db, store = database()
    return db, store, D1NewsStore(SqliteD1(db))


def request(path='/api/chat/news', *, store, user=OWNER, query=''):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), news_store=store)
    headers = [(b'content-type', b'application/json')]
    if user:
        token = create_session_token(SETTINGS, user, canonical_session_id="session_test_a")
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
        # #7847 — version is the only column added since step 2; empty for old rows.
        assert news_columns == {'number', 'kind', 'title', 'detail', 'source', 'published_at', 'version'}
        defaults = {row[1]: row[4] for row in db.execute("PRAGMA table_info(product_news)")}
        assert defaults['version'] == "''"
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

def test_store_and_route_carry_the_deployment_version():
    """#7847 — 버전은 공개 값 하나이고, 모양이 틀리면 저장 자체를 거절한다."""
    async def scenario():
        db, _, store = news_database()
        try:
            first = await store.create('improved', 'versioned title', 'versioned detail',
                                      'ai_tester', '2026.11.16')
            assert first.version == '2026.11.16'
            assert first.public()['version'] == '2026.11.16'
            legacy = await store.create('fixed', 'legacy title', 'legacy detail', 'none')
            assert legacy.version == '' and legacy.public()['version'] == ''
            db.execute("INSERT INTO product_news (kind,title,detail,source,published_at) "
                       "VALUES ('fixed','old row','old detail','none','2026-11-01T00:00:00.000Z')")
            rows = await store.list_recent()
            # 기존 행은 마이그레이션 기본값('')으로 읽히고 목록에서 사라지지 않는다.
            assert sorted(row.version for row in rows) == ['', '', '2026.11.16']
            assert rows[-1].title == 'old row'  # 오래된 행이 마지막이다
            for bad in ('2026-11-16', '20261116', '2026.11.16.1', ' 2026.11.16', 'v2026.11.16'):
                with pytest.raises(ValueError):
                    await store.create('fixed', 'bad version', 'detail', 'none', bad)
            body = payload(await news(request(store=store)))
            assert sorted(item['version'] for item in body['news']) == ['', '', '2026.11.16']
            assert set(body['news'][0]) == {'number', 'kind', 'title', 'detail', 'source',
                                            'published_at', 'version'}
        finally:
            db.close()
    asyncio.run(scenario())


class FakeVersionedNewsStore:
    def __init__(self):
        self.created, self.links = [], []

    async def create(self, kind, title, detail, source, version=''):
        self.created.append((kind, title, detail, source, version))
        return SimpleNamespace(number=len(self.created))

    async def link_feedback(self, feedback_id, number):
        self.links.append((feedback_id, number))
        return True


def test_publish_tool_preview_writes_nothing_and_apply_creates_once():
    news, feedback = FakeVersionedNewsStore(), FakeFeedbackStore()
    preview = asyncio.run(PUBLISH.run_publish(
        news, feedback, version='2026.11.16', kind='improved', title='새 소식 제목',
        detail='새 소식 설명', source='ai_tester', feedback=(FB,)))
    assert news.created == [] and news.links == []
    assert preview['error'] is None
    assert preview['lines'][:6] == ['version=2026.11.16', 'kind=improved', 'source=ai_tester',
                                    'title_chars=7/120', 'detail_chars=7/1000', 'feedback=1']
    applied = asyncio.run(PUBLISH.run_publish(
        news, feedback, version='2026.11.16', kind='fixed', title='새 소식 제목',
        detail='새 소식 설명', source='user', feedback=(FB, FB2), apply=True))
    assert news.created == [('fixed', '새 소식 제목', '새 소식 설명', 'user', '2026.11.16')]
    assert news.links == [(FB, 1), (FB2, 1)]
    assert applied['lines'][0] == 'news=1' and applied['lines'][-1] == 'ok=true'
    # 같은 id를 두 번 적어도 연결은 한 번이다.
    again = FakeVersionedNewsStore()
    asyncio.run(PUBLISH.run_publish(again, feedback, version='2026.11.16', kind='fixed',
                                    title='t제목', detail='d설명', source='none',
                                    feedback=(FB, FB), apply=True))
    assert again.links == [(FB, 1)]
    for kwargs in ({'version': '2026-11-16'}, {'kind': 'new'}, {'source': 'team'},
                   {'title': ''}, {'detail': 'x' * 1001}, {'feedback': ('bad',)},
                   {'feedback': ('fb_' + 'a' * 33,)}):
        request = dict(version='2026.11.16', kind='fixed', title='제목', detail='설명',
                       source='none', feedback=())
        request.update(kwargs)
        with pytest.raises(PUBLISH.ToolError):
            asyncio.run(PUBLISH.run_publish(None, None, **request))


def test_publish_tool_refuses_internal_text_before_any_write():
    """공개 글에는 이슈 번호·영문 고유명사·메일·전화가 들어가지 않는다."""
    cases = (('#7847 를 고쳤습니다', 'NEWS_TITLE_ISSUE_REF'),
             ('# 7847 참고', 'NEWS_TITLE_ISSUE_REF'),
             ('OpenAI 로 바꿨습니다', 'NEWS_TITLE_FOREIGN_WORD'),
             ('cloudflare 배포', 'NEWS_TITLE_FOREIGN_WORD'),
             ('문의 qa@example.test', 'NEWS_TITLE_EMAIL'),
             ('문의 010-1234-5678', 'NEWS_TITLE_PHONE'))
    for detail, code in cases:
        request = dict(version='2026.11.16', kind='fixed', title=detail, detail='설명',
                       source='none', feedback=())
        with pytest.raises(PUBLISH.ToolError) as caught:
            asyncio.run(PUBLISH.run_publish(None, None, **request))
        assert caught.value.code == code, detail
    # 설명 쪽도 같은 규칙을 받는다.
    with pytest.raises(PUBLISH.ToolError) as caught:
        asyncio.run(PUBLISH.run_publish(None, None, version='2026.11.16', kind='fixed',
                                        title='제목', detail='#7847 본문', source='none'))
    assert caught.value.code == 'NEWS_DETAIL_ISSUE_REF'
    # PDF·Excel 같은 일반 낱말은 막지 않는다.
    news = FakeVersionedNewsStore()
    asyncio.run(PUBLISH.run_publish(news, None, version='2026.11.16', kind='improved',
                                    title='PDF 를 Excel 로 저장', detail='Chat 에서 바로 합니다.',
                                    source='none', apply=True))
    assert news.created == [('improved', 'PDF 를 Excel 로 저장', 'Chat 에서 바로 합니다.',
                             'none', '2026.11.16')]


def test_publish_tool_reports_a_missing_feedback_without_creating_the_item():
    class Missing:
        async def get_record(self, feedback_id, **kwargs):
            return None
    news = FakeVersionedNewsStore()
    result = asyncio.run(PUBLISH.run_publish(
        news, Missing(), version='2026.11.16', kind='fixed', title='제목', detail='설명',
        source='none', feedback=(FB,), apply=True))
    assert result['error'] == 'FEEDBACK_NOT_FOUND' and news.created == []

    class RefusingLinks(FakeVersionedNewsStore):
        async def link_feedback(self, feedback_id, number):
            return False
    refusing = RefusingLinks()
    refused = asyncio.run(PUBLISH.run_publish(
        refusing, FakeFeedbackStore(), version='2026.11.16', kind='fixed', title='제목',
        detail='설명', source='none', feedback=(FB,), apply=True))
    assert refused['error'] == 'FEEDBACK_LINK_FAILED'
    # 아이템 번호는 이미 알려 준다 — 남은 연결은 기존 도구로 마무리한다.
    assert refused['lines'][0] == 'news=1'


def test_publish_tool_main_uses_the_com2_conventions_only_for_apply(monkeypatch, capsys):
    calls = []
    for name, value in (('_assert_root', lambda: calls.append('root')),
                        ('_load_env_file', lambda path: calls.append('env')),
                        ('_use_deployed_tree', lambda: calls.append('tree')),
                        ('_become_service_user', lambda: calls.append('user'))):
        monkeypatch.setattr(PUBLISH, name, value)
    monkeypatch.setattr(PUBLISH, '_load_state',
                        lambda: SimpleNamespace(news_store=FakeVersionedNewsStore(),
                                                feedback_store=FakeFeedbackStore()))
    preview = PUBLISH.main(['--version', '2026.11.16', '--kind', 'improved',
                            '--title', '제목', '--detail', '설명', '--source', 'none'])
    out = capsys.readouterr().out
    assert preview == 0 and calls == []
    # 미리보기는 공개 문구를 그대로 보여 주고, 길이를 함께 알려 준다.
    assert 'title=제목' in out and 'detail=설명' in out and 'title_chars=2/120' in out
    assert 'ok=true' in out
    applied = PUBLISH.main(['--version', '2026.11.16', '--kind', 'fixed', '--title', '제목',
                            '--detail', '설명', '--source', 'user', '--feedback', FB, '--apply'])
    out = capsys.readouterr().out
    assert applied == 0 and calls == ['root', 'env', 'tree', 'user']
    assert 'news=1' in out and 'feedback=1' in out and 'ok=true' in out
    refused = PUBLISH.main(['--version', '2026.11.16', '--kind', 'fixed', '--title', '#7847 제목',
                            '--detail', '설명', '--source', 'none'])
    out = capsys.readouterr().out
    assert refused == 1 and 'STOP NEWS_TITLE_ISSUE_REF' in out
    assert '7847 제목' not in out


def test_allowed_latin_covers_our_name_and_plain_format_names():
    """#7847 — 고객이 화면에서 이미 읽는 이름과 형식만 통과하고, 모델·제공사 이름은 계속 막힌다."""
    news = FakeVersionedNewsStore()
    for text in ('PADIEM 계정', 'Google 로그인', 'ZIP 파일', 'OCR 결과',
                 'padiem 계정', 'GOOGLE 로그인', 'zip 파일', 'ocr 결과',
                 'Gmail 주소', 'CSV 표', 'JSON 응답', 'HTML 문서',
                 'Word 문서', 'PowerPoint 발표'):
        asyncio.run(PUBLISH.run_publish(news, None, version='2026.11.16', kind='improved',
                                        title=text, detail='설명', source='none'))
    # 공개 저장소라 예시는 가짜 낱말을 쓴다: 이름만 다를 뿐 같은 규칙이 막는다.
    for text in ('Foomodel 추천', 'Barvendor 연동', 'foomodel 사용'):
        request = dict(version='2026.11.16', kind='fixed', title=text, detail='설명',
                       source='none', feedback=())
        with pytest.raises(PUBLISH.ToolError) as caught:
            asyncio.run(PUBLISH.run_publish(None, None, **request))
        assert caught.value.code == 'NEWS_TITLE_FOREIGN_WORD', text
