"""#7543 — 러브트리 답글 재전송 회차는 같은 DB를 쓰는 워커 중 한 곳만 돌린다.

기존 동작(1분 주기, 재시도 간격, 보내는 본문·응답)은 바꾸지 않고 담당 워커만
S04 체크포인트와 같은 파일 잠금으로 고른다. 비밀값·운영 주소는 쓰지 않는다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.local_bootstrap import ProcessFileLock
from app.lovetree_ops_outbox import dispatch_under_lock, install_retry_loop
from test_7690_lovetree_reply_outbox import SETTINGS, FakeClient, stores


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
    class Router:
        def __init__(self):
            self.on_startup = []
            self.on_shutdown = []

    app = SimpleNamespace(state=SimpleNamespace(), router=Router())
    lock = ProcessFileLock(tmp_path / "lovetree-outbox.lock")
    install_retry_loop(app, process_lock=lock)
    assert len(app.router.on_startup) == 1 and len(app.router.on_shutdown) == 1

    await app.router.on_startup[0]()
    try:
        assert app.state.lovetree_ops_process_lock is lock
    finally:
        await app.router.on_shutdown[0]()
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
