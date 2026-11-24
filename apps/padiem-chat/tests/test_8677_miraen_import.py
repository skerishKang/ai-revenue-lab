"""#8677: operator import of councillor-homepage AI honorary member feedback."""
import asyncio

import pytest

from app.d1_sqlite import SqliteD1
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database


def _item(**over):
    data = dict(external_key="miraen-home:말순:261115:1",
                body="[AI 명예회원 말순]\n첫 화면 설명 글이 사진과 겹칩니다.",
                screen={"width": 820, "height": 1180}, status="fixed",
                created_at="2026-11-15T15:00:00+09:00", memo="고침")
    data.update(over)
    return data


def _run(scenario):
    async def wrapped():
        db, _ = database(full=True)
        try:
            await scenario(D1SiteFeedbackStore(SqliteD1(db)))
        finally:
            db.close()
    asyncio.run(wrapped())


def test_import_creates_ai_row_in_utc_and_rerun_is_noop():
    async def scenario(store):
        first, created = await store.import_miraen(**_item())
        assert created and first.site == "miraen-home" and first.status == "fixed"
        assert first.screen == {"width": 820, "height": 1180}
        assert first.created_at == "2026-11-15T06:00:00.000Z"
        assert first.external_is_ai_customer is True
        await store.set_status(first.id, "reviewing")
        again, created = await store.import_miraen(**_item())
        assert not created and again.id == first.id and again.status == "reviewing"
        rows, _ = await store.list_entries(site="miraen-home")
        assert [row.id for row in rows] == [first.id]
        assert (await store.list_entries(sites=["lovetree"]))[0] == []
    _run(scenario)


def test_import_links_an_existing_public_submission_once():
    async def scenario(store):
        public = await store.submit("miraen-home", "[AI 명예회원 동훈]\n의견 전송", rate_hash="b" * 64)
        key = "miraen-home:동훈:261115_2:1"
        linked, created = await store.import_miraen(
            **_item(external_key=key, created_at="2026-11-15T20:00:00+09:00",
                    body="[AI 명예회원 동훈]\n의견 전송", existing_id=public.id))
        assert not created and linked.id == public.id and linked.external_feedback_id == key
        again, created = await store.import_miraen(
            **_item(external_key=key, created_at="2026-11-15T20:00:00+09:00",
                    body="[AI 명예회원 동훈]\n의견 전송", existing_id=public.id))
        assert not created and again.id == public.id
        assert len((await store.list_entries(site="miraen-home"))[0]) == 1
    _run(scenario)


@pytest.mark.parametrize("over", [
    dict(external_key="lovetree:말순:261115:1"),
    dict(external_key="miraen-home:말순:261116:1"),
    dict(body="말순 의견"),
    dict(status="closed"),
    dict(screen={"width": 820}),
    dict(created_at="2026-11-15T15:00:00"),
])
def test_import_rejects_bad_input(over):
    async def scenario(store):
        with pytest.raises(ValueError):
            await store.import_miraen(**_item(**over))
        assert (await store.list_entries(site="miraen-home"))[0] == []
    _run(scenario)


def test_import_never_attaches_to_another_site_row():
    async def scenario(store):
        other = await store.submit("lovetree", "example", rate_hash="a" * 64)
        with pytest.raises(ValueError):
            await store.import_miraen(**_item(existing_id=other.id))
    _run(scenario)
