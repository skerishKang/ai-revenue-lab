"""#7605: the withdrawal request bounds its external cleanup — no unbounded wait.

Before the fix the drain after the deletion batch ran every external item
(Google purge, object deletes, file-lane purge) with no time limit at all, so
one slow store held the whole withdrawal response. Now the request waits at
most ``REQUEST_CLEANUP_BUDGET_SECONDS`` for the pass and
``REQUEST_CLEANUP_CALL_TIMEOUT_SECONDS`` for one call; whatever the budget
does not cover stays in the pending rows committed with the batch and the
daily purge run continues it. The deletion batch and the session revocation
are not bounded by this — the account is deleted and the login blocked either
way.

The slow store here is a Google authority whose first purge call never
answers. The cut the tests observe is the production one — ``asyncio.wait_for``
around the drain's call — never a sleep.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from app.local_r2 import LocalDiskR2

from test_account_deletion_261103 import (
    BASE,
    DELETER_EMAIL,
    CanonicalAuthority,
    build_app,
    call,
    seed_db,
    token_for,
)
from test_7557_account_deletion_leftovers import (
    WORKSPACE,
    GoogleAuthority,
    _GoogleRevoke,
    _app,
    _delete,
    _existing,
    _pending,
    _session,
)

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


class SlowFirstPurgeAuthority:
    """A Google authority whose first purge call never answers (a slow store).

    The hang is a future that never resolves, so the cut the test observes is
    exactly the production one. Later calls reach the real authority behind
    it, which is how the next pass finishes what the budget left over.
    """

    def __init__(self, inner: GoogleAuthority):
        self.inner = inner
        self.calls = 0

    async def purge_workspace_credentials(self, payload):
        self.calls += 1
        if self.calls == 1:
            await asyncio.get_running_loop().create_future()
        return await self.inner.purge_workspace_credentials(payload)


# ---------------------------------------------------------------------------
# 1. A slow external call cannot hold the withdrawal response.
# ---------------------------------------------------------------------------


def test_a_slow_external_call_cannot_hold_the_withdrawal_response(tmp_path, monkeypatch):
    _session(monkeypatch)
    db, accounts, app, settings, bucket, google, objects = _app(tmp_path)
    from app import account_deletion
    from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth

    # The budget is spent after the first (hung) call: the per-call cap is
    # longer than the whole-pass budget on purpose, so this one test shows
    # both bounds — the call is cut, and no further item is started.
    monkeypatch.setattr(account_deletion, "REQUEST_CLEANUP_CALL_TIMEOUT_SECONDS", 0.3)
    monkeypatch.setattr(account_deletion, "REQUEST_CLEANUP_BUDGET_SECONDS", 0.2)
    slow = SlowFirstPurgeAuthority(google)
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(slow)
    uid = accounts["deleter"]

    started = time.monotonic()
    response = _delete(app, settings, uid)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < 5.0, elapsed
    body = response.json()
    assert body["ok"] is True
    # 접수와 남은 정리가 구분되어 보인다.
    assert body["cleanup"]["complete"] is False and body["cleanup"]["pending"] >= 1
    assert "자동으로 다시 시도" in body["message"]
    # 계정 삭제와 로그인 차단은 상한과 무관하게 끝났다.
    assert db.conn.execute(
        "SELECT COUNT(*) AS n FROM users WHERE id = ?", (uid,)).fetchone()["n"] == 0
    # 상한을 넘긴 정리는 미완 기록에 남는다: 끊긴 호출만 실패 1회, 나머지는 미시도.
    assert _pending(db) == body["cleanup"]["pending"]
    rows = db.conn.execute(
        "SELECT kind, attempts FROM account_deletion_cleanup_pending").fetchall()
    attempts = {row["kind"]: row["attempts"] for row in rows}
    assert attempts.get("google_workspace") == 1
    assert all(value == 0 for kind, value in attempts.items() if kind != "google_workspace")

    # 이어서 처리된다: 다음 실행(매일 도는 만료 정리와 같은 호출)이 끝낸다.
    from app.account_cleanup_pending import CleanupPorts, drain

    result = asyncio.run(drain(db, CleanupPorts(
        bucket=bucket, google=app.state.google_oauth_workspace_truth,
        file_lane_absent_is_done=True)))
    assert result["pending"] == 0 and result["failed"] == 0
    assert _pending(db) == 0
    assert google.rows(WORKSPACE) == 0
    assert _existing(bucket, objects["mine"]) == []
    assert _existing(bucket, objects["theirs"]) == objects["theirs"]


# ---------------------------------------------------------------------------
# 2. The budget stops starting new items; the unstarted ones stay untouched.
#    (Unit level, with an injected clock — no real waiting anywhere.)
# ---------------------------------------------------------------------------


def test_the_budget_stops_starting_new_items_and_keeps_them_pending(tmp_path):
    from app.account_cleanup_pending import (
        CleanupPorts,
        drain,
        item_id,
        pending_insert_statements,
    )

    db, accounts = seed_db()
    bucket = LocalDiskR2(tmp_path / "objects")
    bucket.put("chat-attachments/deleter/one", b"1")
    bucket.put("chat-attachments/deleter/two", b"2")
    targets = [
        ("r2_prefix", "chat-attachments/deleter/"),
        ("r2_key", "gone/one"),
        ("r2_key", "gone/two"),
    ]
    asyncio.run(db.batch(pending_insert_statements(db, targets, now=NOW.isoformat())))

    # The clock reads inside the budget for the first item only; the second
    # check is already past the deadline, so the pass stops there.
    clock_values = iter([100.0, 200.0])
    result = asyncio.run(drain(
        db, CleanupPorts(bucket=bucket),
        item_ids=[item_id(kind, target) for kind, target in targets],
        limit=3, deadline=150.0, clock=lambda: next(clock_values)))

    assert result["done"] == 1 and result["pending"] == 2
    left = db.conn.execute(
        "SELECT kind, attempts FROM account_deletion_cleanup_pending ORDER BY kind"
    ).fetchall()
    assert [(row["kind"], row["attempts"]) for row in left] == [
        ("r2_key", 0), ("r2_prefix", 0)]
    # 아직 시도하지 않은 항목의 대상은 그대로 남아 있다.
    assert _existing(bucket, ["chat-attachments/deleter/two"]) == [
        "chat-attachments/deleter/two"]

    # The next pass without a budget finishes what this one left.
    result = asyncio.run(drain(db, CleanupPorts(bucket=bucket)))
    assert result["pending"] == 0 and result["done"] == 2
    assert _existing(bucket, ["chat-attachments/deleter/two"]) == []


# ---------------------------------------------------------------------------
# 3. One call cut by the per-call cap is a failed attempt; the pass goes on.
# ---------------------------------------------------------------------------


def test_a_call_timeout_counts_as_one_failed_attempt_and_the_pass_continues(tmp_path):
    from app.account_cleanup_pending import (
        CleanupPorts,
        drain,
        item_id,
        pending_insert_statements,
    )

    class HangingGoogle:
        """The Google purge that never answers (the store the cap exists for)."""

        async def purge_workspace_credentials(self, *, workspace_ref):
            await asyncio.get_running_loop().create_future()

    db, accounts = seed_db()
    targets = [
        ("google_workspace", "workspace.slow"),
        ("r2_key", "obj/one"),
        ("r2_key", "obj/two"),
    ]
    asyncio.run(db.batch(pending_insert_statements(db, targets, now=NOW.isoformat())))
    bucket = LocalDiskR2(tmp_path / "objects")
    bucket.put("obj/one", b"1")
    bucket.put("obj/two", b"2")

    result = asyncio.run(drain(
        db, CleanupPorts(bucket=bucket, google=HangingGoogle()),
        item_ids=[item_id(kind, target) for kind, target in targets],
        limit=3, call_timeout=0.05))

    # The hung call is one failed attempt; the rest of the pass is unaffected.
    assert result["failed"] == 1 and result["done"] == 2 and result["pending"] == 1
    row = db.conn.execute(
        "SELECT attempts FROM account_deletion_cleanup_pending"
        " WHERE kind = 'google_workspace'").fetchone()
    assert row["attempts"] == 1
    assert _existing(bucket, ["obj/one", "obj/two"]) == []
