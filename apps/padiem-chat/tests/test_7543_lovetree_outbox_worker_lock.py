"""#7543 — 러브트리 답글 재전송 회차는 같은 DB를 쓰는 워커 중 한 곳만 돌린다.

기존 동작(1분 주기, 재시도 간격, 보내는 본문·응답)은 바꾸지 않고 담당 워커만
S04 체크포인트와 같은 파일 잠금으로 고른다. 비밀값·운영 주소는 쓰지 않는다.
"""
from __future__ import annotations

import secrets
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.lifespan_hooks import LifespanHooks
from app.local_bootstrap import ProcessFileLock
from app.lovetree_ops_outbox import D1LovetreeOpsOutbox, dispatch_under_lock, install_retry_loop
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database

_SESSION_SECRET = secrets.token_urlsafe(32)
_SECRET = secrets.token_urlsafe(32)
SETTINGS = Settings(
    auth_mode="password", public_base_url="https://chat.example.test",
    session_secret=_SESSION_SECRET,
    site_feedback_secret_lovetree=_SECRET,
    site_feedback_reply_secret_lovetree=_SECRET,
    site_feedback_reply_url_lovetree="https://lovetree.test/api/ops-feedback/ingest",
)


class FakeClient:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.posts = []

    async def post(self, url, *, content, headers):
        self.posts.append({"url": url, "content": content, "headers": headers})
        return SimpleNamespace(status_code=self.statuses.pop(0) if self.statuses else 200)

    async def aclose(self):
        pass


def stores():
    db, _ = database(full=True)
    try:
        return db, D1SiteFeedbackStore(SqliteD1(db)), D1LovetreeOpsOutbox(SqliteD1(db))
    except Exception:
        db.close()
        raise


@pytest.mark.asyncio
async def test_two_app_instances_sharing_one_db_dispatch_from_one_only(tmp_path):
    db, store, outbox = stores()
    lock_path = tmp_path / "lovetree-outbox.lock"
    lock_a = ProcessFileLock(lock_path)
    lock_b = ProcessFileLock(lock_path)
    state_a = SimpleNamespace(settings=SETTINGS, lovetree_ops_outbox=outbox,
                              lovetree_ops_process_lock=lock_a)
    state_b = SimpleNamespace(settings=SETTINGS, lovetree_ops_outbox=outbox,
                              lovetree_ops_process_lock=lock_b)
    try:
        await outbox.enqueue_reply(
            feedback_id="fb_7543_worker_lock", external_feedback_id="101",
            body="두 프로세스 확인용 답글")

        client_a, client_b = FakeClient(200), FakeClient(200)
        assert lock_a.acquire(wait=False)
        try:
            skipped = await dispatch_under_lock(state_b, client=client_b)
            assert skipped is None
            assert client_b.posts == []
        finally:
            lock_a.release()

        sent = await dispatch_under_lock(state_b, client=client_b)
        assert sent["sent"] == 1
        assert len(client_b.posts) == 1
        assert not lock_b.held

        again = await dispatch_under_lock(state_a, client=client_a)
        assert again["checked"] == 0 and again["sent"] == 0
        assert client_a.posts == []
    finally:
        db.close()


@pytest.mark.asyncio
async def test_install_retry_loop_wires_the_shared_lock_without_a_new_timer(tmp_path):
    hooks = LifespanHooks()
    app = SimpleNamespace(state=SimpleNamespace(), router=SimpleNamespace(lifespan_context=hooks))
    lock = ProcessFileLock(tmp_path / "lovetree-outbox.lock")
    install_retry_loop(app, process_lock=lock)
    assert len(hooks.on_startup) == 1 and len(hooks.on_shutdown) == 1

    await hooks.on_startup[0]()
    try:
        assert app.state.lovetree_ops_process_lock is lock
    finally:
        await hooks.on_shutdown[0]()
        assert not lock.held


def test_single_worker_without_a_lock_keeps_the_old_dispatch_path():
    db, _store, outbox = stores()
    try:
        state = SimpleNamespace(settings=SETTINGS, lovetree_ops_outbox=outbox)
        client = FakeClient(200)
        result = __import__("asyncio").run(dispatch_under_lock(state, client=client))
        assert result == {"sent": 0, "retried": 0, "failed": 0, "checked": 0}
        assert client.posts == []
    finally:
        db.close()
