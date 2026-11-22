"""#7649 state transitions: a common account the authority deletes without a
preparation number (the concurrent last-link race) answers as received, leaves
exactly one pending shared-login finish, and the retry lane finishes it."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.account_cleanup_pending import (
    KIND_SHARED_ACCOUNT_COMPLETE,
    CleanupPorts,
    drain,
    item_id as cleanup_item_id,
    pending_insert_statements,
)
from app.account_deletion import _finish_auth_account_deletion, _prepare_auth_account_deletion
from _support.account_deletion import (
    BASE,
    DELETER_EMAIL,
    _pending_shared_complete_rows,
    call,
    token_for,
)
from test_bookai_account_deletion_7547 import fixture


def _run_unprepared_withdrawal():
    db, accounts, app, settings, authority, events = fixture(mixed=True)

    async def concurrently_removed(**kwargs):
        # Chat saw more than one live link, so it skipped the preparation and
        # called remove_product_link without a number; the authority deletes
        # the common account anyway (another link died in between).
        assert kwargs["account_deletion_operation_id"] is None
        authority.links.clear()
        return {"removed": False, "common_account_deleted": True, "already_deleted": True}

    authority.remove_product_link = concurrently_removed
    response = call(app, settings, "POST", "/api/account/delete", origin=BASE,
                    token=token_for(settings, accounts["deleter"]),
                    body={"confirm": DELETER_EMAIL})
    return db, app, response


def test_unprepared_common_delete_answers_received_with_exactly_one_record():
    db, app, response = _run_unprepared_withdrawal()
    body = response.json()
    # Received, not refused: the common account is gone and must stay gone.
    assert response.status_code == 200
    assert body["ok"] is True and body["common_account_deleted"] is True
    assert body["cleanup"]["complete"] is False and body["cleanup"]["pending"] >= 1
    assert "다시 시도" in body.get("message", "")
    rows = _pending_shared_complete_rows(db)
    assert len(rows) == 1 and rows[0]["attempts"] == 0
    assert rows[0]["item_id"] == cleanup_item_id(KIND_SHARED_ACCOUNT_COMPLETE, rows[0]["target"])


def test_the_unprepared_record_is_picked_up_and_finished_by_the_retry_lane(tmp_path):
    db, app, response = _run_unprepared_withdrawal()
    assert response.status_code == 200
    rows = _pending_shared_complete_rows(db)
    assert len(rows) == 1
    subject = rows[0]["target"]

    retry_subjects, prepared_numbers = [], []

    async def finish(subject_id: str) -> bool:
        # The request-shaped helpers only read request.app.state.
        request_like = SimpleNamespace(app=app)
        retry_subjects.append(subject_id)
        operation_id = await _prepare_auth_account_deletion(request_like, subject_id)
        prepared_numbers.append(operation_id)
        await _finish_auth_account_deletion(request_like, subject_id, operation_id)
        return True

    async def success_transport(**kwargs):
        if kwargs["path"] == "/internal/account-delete/prepare":
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "prepared": True, "revoked_sessions": 0})
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "deleted": True})

    app.state.account_delete_rpc_transport = success_transport
    result = asyncio.run(drain(
        db, CleanupPorts(shared_account_finish=finish),
        item_ids=[cleanup_item_id(KIND_SHARED_ACCOUNT_COMPLETE, subject)]))
    assert result["done"] == 1 and result["pending"] == 0
    # The retry mints its own fresh preparation number; one finish per row.
    assert retry_subjects == [subject] and len(prepared_numbers) == 1
    assert _pending_shared_complete_rows(db) == []


def test_the_same_account_never_gets_a_second_record():
    db, app, response = _run_unprepared_withdrawal()
    rows = _pending_shared_complete_rows(db)
    assert len(rows) == 1
    target = rows[0]["target"]
    stamp = datetime.now(timezone.utc).isoformat()

    async def rewrite():
        # A repeated pass (or a replayed insert) writes the same item again.
        for statement in pending_insert_statements(
                db, [(KIND_SHARED_ACCOUNT_COMPLETE, target)], now=stamp):
            await statement.run()

    asyncio.run(rewrite())
    again = _pending_shared_complete_rows(db)
    assert len(again) == 1 and again[0]["item_id"] == rows[0]["item_id"]
    assert again[0]["attempts"] == 0 and again[0]["target"] == target
