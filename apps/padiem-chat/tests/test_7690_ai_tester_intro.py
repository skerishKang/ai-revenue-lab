"""#7690 stage 1 — AI honorary member intro: store, admin response, ops tool."""
import asyncio
import json

from app.ai_tester_intro_store import AiTesterIntroStore, clean_intro
from app.feedback_routes import admin_feedback
from _support.feedback_route_fixtures import AdminAuthority, request
from _support.feedback_store import BODY, OWNER, OTHER, database
from tools.feedback_ops import run_intro_set

INTRO = {'age_band': '30대', 'job': '사무', 'device': '노트북'}


def test_intro_store_is_owner_scoped_and_bounded():
    async def scenario():
        db, store = database()
        try:
            intros = store.intro_store()
            assert await intros.get(OWNER) is None
            assert await intros.get('not-an-account') is None
            saved = await intros.save(OWNER, **INTRO)
            assert saved == INTRO
            assert await intros.get(OWNER) == INTRO
            assert await intros.get(OTHER) is None
            for bad in (' ', 'x' * 81, 3):
                try:
                    clean_intro(bad)
                except ValueError:
                    continue
                raise AssertionError('invalid intro accepted')
        finally:
            db.close()
    asyncio.run(scenario())


def test_admin_inbox_shows_intro_only_for_ai_honorary_member():
    async def scenario():
        db, store = database()
        try:
            db.execute('UPDATE users SET ai_tester=1 WHERE id=?', (OWNER,))
            await store.intro_store().save(OWNER, **INTRO)
            ai_row = await store.submit(OWNER, BODY)
            human_row = await store.submit(OTHER, 'people feedback that must stay private')
            response = await admin_feedback(request(store, user=OTHER))
            assert response.status_code == 200
            rows = json.loads(response.body)['feedback']
            by_id = {row['id']: row for row in rows}
            assert by_id[ai_row.id]['sender_intro'] == INTRO
            assert 'sender_intro' not in by_id[human_row.id]
            assert (await admin_feedback(request(store, user=OWNER))).status_code == 403
        finally:
            db.close()
    asyncio.run(scenario())


def test_admin_inbox_without_intro_has_no_block():
    async def scenario():
        db, store = database()
        try:
            db.execute('UPDATE users SET ai_tester=1 WHERE id=?', (OWNER,))
            row = await store.submit(OWNER, BODY)
            rows = json.loads((await admin_feedback(request(store, user=OTHER))).body)['feedback']
            assert 'sender_intro' not in {r['id']: r for r in rows}[row.id]
        finally:
            db.close()
    asyncio.run(scenario())


def test_ops_tool_preview_and_apply_never_print_the_account():
    async def scenario():
        db, store = database()
        try:
            preview = await run_intro_set(store.intro_store(), OWNER,
                                          age_band=INTRO['age_band'], apply=False)
            assert preview['error'] is None and OWNER not in json.dumps(preview)
            assert await store.intro_store().get(OWNER) is None
            applied = await run_intro_set(store.intro_store(), OWNER,
                                          age_band=INTRO['age_band'], job=INTRO['job'],
                                          device=INTRO['device'], apply=True)
            assert applied['error'] is None and OWNER not in json.dumps(applied)
            assert await store.intro_store().get(OWNER) == INTRO
        finally:
            db.close()
    asyncio.run(scenario())
