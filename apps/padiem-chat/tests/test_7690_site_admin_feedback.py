"""#7690 stage 2 route units: site admins read only their own site's feedback."""
import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE
from sid_session_helper import sid_session_token
from app.d1_sqlite import SqliteD1
from app.platform_admin_routes import platform_admin_session
from app.site_feedback_admin_identity import D1SiteFeedbackAdminAuthorizer
from app.site_feedback_routes import admin_site_feedback, admin_site_feedback_status
from app.site_feedback_store import D1SiteFeedbackStore
from test_7680_feedback_store import database
from test_7690_site_feedback_routes import ADMIN, SETTINGS, USER

CENTRAL = ADMIN
SITE_ADMIN = 'usr_' + 'c' * 32
NO_SITE = 'usr_' + 'd' *32
FB = 'sf_' + 'a' * 32
FB2 = 'sf_' + 'b' * 32
FB3 = 'sf_' + 'e' * 32
TWO_SITES = frozenset({'miraen-home', 'miraen-media'})


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == CENTRAL


class RaisingAuthority:
    async def sites_for(self, *, user_id):
        raise RuntimeError('fixture-unavailable')


def seed(db):
    for fid, site, created in ((FB, 'miraen-home', '2026-11-15T00:00:01Z'),
                               (FB2, 'miraen-home', '2026-11-15T00:00:02Z'),
                               (FB3, 'miraen-media', '2026-11-15T00:00:03Z')):
        db.execute('INSERT INTO site_feedback '
                   '(id,site,body,screen_json,status,ops_memo,created_day,created_at,updated_at) '
                   "VALUES (?,?,?,NULL,'new',NULL,?,?,?)", (fid, site, 'site-fixture-body',
                                                            created[:10], created, created))


def assignments(db, *pairs):
    for user_id, site in pairs:
        db.execute('INSERT INTO site_feedback_admins (user_id,site,created_at) VALUES (?,?,?)',
                   (user_id, site, '2026-11-14T00:00:00Z'))


def request(store, authorizer, *, method='GET', user=None, body=None, feedback_id='',
            query='', session_path='/api/admin/session'):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), site_feedback_store=store,
                            platform_admin_role_store=None, b66_member_admin_store=None,
                            central_model_admin_authorizer=AdminAuthority(),
                            site_feedback_admin_authorizer=authorizer)
    headers = [(b'content-type', b'application/json')]
    if user:
        token = sid_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'path': session_path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': feedback_id},
                    'client': ('203.0.113.9', 12345)}, receive)


def payload(response):
    return json.loads(response.body)


def test_site_admin_scope_list_and_status(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            monkeypatch.setattr('app.site_feedback_routes.SITE_KEYS', TWO_SITES)
            seed(db)
            assignments(db, (SITE_ADMIN, 'miraen-home'))
            store = D1SiteFeedbackStore(SqliteD1(db))
            authorizer = D1SiteFeedbackAdminAuthorizer(SqliteD1(db))
            own = await admin_site_feedback(request(store, authorizer, user=SITE_ADMIN))
            assert own.status_code == 200
            body = payload(own)
            assert [row['id'] for row in body['feedback']] == [FB2, FB]
            assert all(row['site'] == 'miraen-home' for row in body['feedback'])
            assert body['sites'] == ['miraen-home']
            for query in ('site=all', 'site='):
                same = await admin_site_feedback(
                    request(store, authorizer, user=SITE_ADMIN, query=query))
                assert same.status_code == 200
                assert [row['id'] for row in payload(same)['feedback']] == [FB2, FB]
            filtered = await admin_site_feedback(
                request(store, authorizer, user=SITE_ADMIN, query='site=miraen-home'))
            assert [row['id'] for row in payload(filtered)['feedback']] == [FB2, FB]
            other = await admin_site_feedback(
                request(store, authorizer, user=SITE_ADMIN, query='site=miraen-media'))
            assert other.status_code == 404
            foreign = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=SITE_ADMIN,
                feedback_id=FB3, body={'status': 'fixed'}))
            assert foreign.status_code == 404
            assert db.execute('SELECT status FROM site_feedback WHERE id=?', (FB3,)).fetchone()[0] == 'new'
            changed = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=SITE_ADMIN,
                feedback_id=FB, body={'status': 'fixed'}))
            assert changed.status_code == 200 and payload(changed)['feedback']['status'] == 'fixed'
            memo = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=SITE_ADMIN,
                feedback_id=FB2, body={'ops_memo': 'own-site-memo'}))
            assert memo.status_code == 200 and payload(memo)['feedback']['ops_memo'] == 'own-site-memo'
            unknown = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=SITE_ADMIN,
                feedback_id='sf_' + '0' * 32, body={'status': 'fixed'}))
            assert unknown.status_code == 404
            denied_list = await admin_site_feedback(request(store, authorizer, user=NO_SITE))
            assert denied_list.status_code == 403
            denied_patch = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=NO_SITE,
                feedback_id=FB, body={'status': 'fixed'}))
            assert denied_patch.status_code == 403
            assert (await admin_site_feedback(request(store, authorizer))).status_code == 401
            central_all = await admin_site_feedback(request(store, authorizer, user=CENTRAL))
            assert central_all.status_code == 200
            central_body = payload(central_all)
            assert len(central_body['feedback']) == 3
            assert central_body['sites'] == ['miraen-home', 'miraen-media']
            central_site = await admin_site_feedback(
                request(store, authorizer, user=CENTRAL, query='site=miraen-media'))
            assert [row['id'] for row in payload(central_site)['feedback']] == [FB3]
            central_patch = await admin_site_feedback_status(request(
                store, authorizer, method='PATCH', user=CENTRAL,
                feedback_id=FB3, body={'status': 'reviewing'}))
            assert central_patch.status_code == 200
        finally:
            db.close()
    asyncio.run(scenario())


def test_authorizer_assign_unassign_and_guards(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            monkeypatch.setattr('app.site_feedback_admin_identity.SITE_KEYS', TWO_SITES)
            authorizer = D1SiteFeedbackAdminAuthorizer(SqliteD1(db))
            assert await authorizer.sites_for(user_id=USER) == frozenset()
            assert await authorizer.assign(user_id=USER, site='miraen-home') == 'assigned'
            assert await authorizer.assign(user_id=USER, site='miraen-home') == 'already'
            assert await authorizer.sites_for(user_id=USER) == frozenset({'miraen-home'})
            assert await authorizer.is_site_admin(user_id=USER, site='miraen-home') is True
            assert await authorizer.assign(user_id=USER, site='miraen-media') == 'assigned'
            assert await authorizer.sites_for(user_id=USER) == frozenset(TWO_SITES)
            assert await authorizer.assign(user_id='usr_' + '9' * 32, site='miraen-home') == 'missing'
            for bad in (('bad', 'miraen-home'), (USER, 'other-site'), (None, 'miraen-home')):
                try:
                    await authorizer.assign(user_id=bad[0], site=bad[1])
                    assert False, 'expected ValueError'
                except ValueError:
                    pass
            assert await authorizer.unassign(user_id=USER, site='miraen-media') == 'removed'
            assert await authorizer.unassign(user_id=USER, site='miraen-media') == 'not-assigned'
            assert await authorizer.sites_for(user_id=USER) == frozenset({'miraen-home'})
            assert await authorizer.sites_for(user_id='not-a-uid') == frozenset()
            assert await authorizer.is_site_admin(user_id=USER, site='other-site') is False
        finally:
            db.close()
    asyncio.run(scenario())


def test_store_list_entries_multi_site():
    async def scenario():
        db, _ = database(full=True)
        try:
            seed(db)
            store = D1SiteFeedbackStore(SqliteD1(db))
            own = await store.list_entries(sites=frozenset({'miraen-home'}))
            assert [row.id for row in own[0]] == [FB2, FB]
            empty = await store.list_entries(sites=frozenset())
            assert empty == ([], None)
            one = await store.list_entries(site='miraen-media')
            assert [row.id for row in one[0]] == [FB3]
            assert [row.id for row in (await store.list_entries(
                site='miraen-media', sites=frozenset({'miraen-home'})))[0]] == [FB3]
        finally:
            db.close()
    asyncio.run(scenario())


def test_session_reports_site_feedback_capability():
    async def scenario():
        db, _ = database(full=True)
        try:
            assignments(db, (SITE_ADMIN, 'miraen-home'))
            authorizer = D1SiteFeedbackAdminAuthorizer(SqliteD1(db))
            store = D1SiteFeedbackStore(SqliteD1(db))
            site_admin = payload(await platform_admin_session(
                request(store, authorizer, user=SITE_ADMIN)))
            assert site_admin['authenticated'] is True and site_admin['role'] is None
            assert site_admin['capabilities']['chat_admin'] is False
            assert site_admin['capabilities']['site_feedback_admin'] is True
            assert site_admin['site_feedback_sites'] == ['miraen-home']
            central = payload(await platform_admin_session(
                request(store, authorizer, user=CENTRAL)))
            assert central['capabilities']['chat_admin'] is True
            assert central['capabilities']['site_feedback_admin'] is False
            assert central['site_feedback_sites'] == []
            guest = payload(await platform_admin_session(request(store, authorizer)))
            assert guest['authenticated'] is False
            assert guest['capabilities']['site_feedback_admin'] is False
            broken = payload(await platform_admin_session(
                request(store, RaisingAuthority(), user=SITE_ADMIN)))
            # An unreadable site table means "not a site admin"; the rest of
            # the administrator hub session must keep working.
            assert broken["ok"] is True and broken["authenticated"] is True
            assert broken["capabilities"]["site_feedback_admin"] is False
            assert broken["site_feedback_sites"] == []
        finally:
            db.close()
    asyncio.run(scenario())
