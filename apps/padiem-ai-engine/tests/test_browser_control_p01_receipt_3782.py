"""#3782: Engine D1 browser.control approved receipt — source-only.

Synthetic Core pause/decision test fixtures do NOT mint a real P01 decision.
The receipt writer/reader is not configured in any product Worker route.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from app.browser_control_p01_receipt import (
    ENGINE_BROWSER_CONTROL_P01_RECEIPT_PRODUCER_WIRED,
    ENGINE_BROWSER_CONTROL_P01_RECEIPT_READER_WIRED,
    CloudflareD1BrowserControlP01ReceiptStore,
    EngineApprovedBrowserControlP01Receipt,
)
from app.continuation_d1 import _pause_json
from padiem_ai_core.agent_approval import (
    AgentApprovalError,
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)

NOW = datetime(2026, 10, 8, 11, 0, tzinfo=timezone.utc)
APP_ID = "padiem.browser.test"
CONT_REF = "cont_3782canonical"
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class _Statement:
    def __init__(self, db: sqlite3.Connection, sql: str):
        self._db = db
        self._sql = sql
        self._params: tuple[Any, ...] = ()

    def bind(self, *args):
        self._params = args
        return self

    async def first(self):
        cursor = self._db.execute(self._sql, self._params)
        row = cursor.fetchone()
        return dict(row) if row else None

    async def run(self):
        cursor = self._db.execute(self._sql, self._params)
        self._db.commit()
        return {"meta": {"changes": cursor.rowcount}}


class _D1:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript((MIGRATIONS / "0002_engine_continuations.sql").read_text(encoding="utf-8"))
        self.db.executescript((MIGRATIONS / "0009_browser_control_p01_receipts.sql").read_text(encoding="utf-8"))

    def prepare(self, sql):
        return _Statement(self.db, sql)

    async def batch(self, statements):
        """Test-only SQLite D1 batch: one transaction, rollback on any error."""
        try:
            self.db.execute("BEGIN")
            outcomes = []
            for statement in statements:
                result = self.db.execute(statement._sql, statement._params)
                outcomes.append({"meta": {"changes": result.rowcount}})
            self.db.commit()
            return outcomes
        except Exception:
            self.db.rollback()
            raise


@pytest.fixture
def db():
    instance = _D1()
    try:
        yield instance
    finally:
        instance.db.close()


def pause(**changes):
    p = ApprovalPause(
        pause_id="pause.browser.3782", run_id="run.browser.3782",
        agent_runtime_id="agent.browser.3782", tool_id="browser.control",
        invocation_sha256="a" * 64, requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1, created_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=2), approval_scope=("browser.control",),
    )
    return replace(p, **changes) if changes else p


def decision(p=None, **changes):
    p = p or pause()
    d = VerifiedApprovalDecision(
        decision_id="decision.browser.3782", pause_id=p.pause_id,
        outcome=ApprovalOutcome.APPROVED, authority_ref="p01.real.authority.test",
        evidence_ref="evidence.browser.3782", decided_at=NOW - timedelta(seconds=5),
    )
    return replace(d, **changes) if changes else d


def seed(db, p=None, *, state="consumed", app_id=APP_ID, continuation_ref=CONT_REF):
    p = p or pause()
    db.db.execute(
        "INSERT INTO padiem_engine_continuations "
        "(app_id,continuation_ref,pause_json,execution_identity_json,state,"
        "claim_token,cancel_reason,cancel_event_fingerprint,created_at,updated_at,expires_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (app_id, continuation_ref, _pause_json(p), "{}",
         state, None, None, None,
         (NOW - timedelta(minutes=1)).isoformat(),
         NOW.isoformat(), p.expires_at.isoformat()),
    )
    db.db.commit()


def approved(p=None, d=None, *, app_id=APP_ID, continuation_ref=CONT_REF):
    p = p or pause()
    return EngineApprovedBrowserControlP01Receipt.from_verified_engine_decision(
        app_id=app_id, continuation_ref=continuation_ref,
        pause=p, decision=d or decision(p), now=NOW,
    )


def run(awaitable):
    return asyncio.run(awaitable)


def test_consumed_canonical_engine_receipt_is_durable_and_revocable(db):
    p = pause()
    seed(db, p)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    receipt = approved(p)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    run(store.store_completed(receipt, now=NOW))
    restarted = CloudflareD1BrowserControlP01ReceiptStore(db)
    assert run(restarted.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == receipt
    assert run(restarted.revoke(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is True
    assert run(restarted.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    assert run(restarted.revoke(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is False


@pytest.mark.parametrize("state", ["active", "claimed", "cancelled", "expired", "cancelling"])
def test_no_receipt_for_unconsumed_engine_continuation(db, state):
    seed(db, state=state)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="no matching consumed"):
        run(store.store_completed(approved(), now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


@pytest.mark.parametrize("change", [
    {"tool_id": "process.execute"},
    {"approval_scope": ("process.execute",)},
    {"approval_scope": ("browser.control", "process.execute")},
    {"run_id": "run.other"},
])
def test_wrong_tool_scope_or_run_cannot_store(db, change):
    canonical = pause()
    seed(db, canonical)
    submitted = pause(**change)
    if change.get("tool_id") or change.get("approval_scope"):
        with pytest.raises(ValueError, match="not approved"):
            approved(submitted)
    else:
        with pytest.raises(ValueError, match="no matching consumed"):
            run(CloudflareD1BrowserControlP01ReceiptStore(db).store_completed(
                approved(submitted), now=NOW,
            ))


@pytest.mark.parametrize("decision_change", [
    {"outcome": ApprovalOutcome.DENIED},
    {"pause_id": "pause.other"},
    {"decided_at": NOW + timedelta(seconds=1)},
    {"decided_at": NOW - timedelta(days=1)},
])
def test_denied_mismatched_or_invalid_decision_not_receipted(decision_change):
    with pytest.raises((ValueError, AgentApprovalError)):
        approved(d=decision(**decision_change))


def test_pause_not_expired_at_issue_or_cannot_be_receipted():
    p = pause(expires_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError):
        approved(p)


def test_duplicate_or_replayed_approved_decision_never_changes_row(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    original = approved()
    run(store.store_completed(original, now=NOW))
    with pytest.raises(ValueError, match="duplicate"):
        run(store.store_completed(original, now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == original


def test_other_owner_app_or_missing_continuation_never_receipted(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    for receipt in (approved(app_id="another.app"), approved(continuation_ref="cont_missing")):
        with pytest.raises(ValueError, match="no matching consumed"):
            run(store.store_completed(receipt, now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_expired_and_cancelled_receipts_never_visible(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    assert run(store.resolve_active(
        app_id=APP_ID, continuation_ref=CONT_REF, now=NOW + timedelta(minutes=3),
    )) is None
    db.db.execute(
        "UPDATE padiem_engine_continuations SET state='cancelled' "
        "WHERE app_id=? AND continuation_ref=?", (APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_receipt_invalidated_when_canonical_pause_rebound(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    db.db.execute(
        "UPDATE padiem_engine_continuations SET pause_json=? "
        "WHERE app_id=? AND continuation_ref=?",
        (_pause_json(pause(invocation_sha256="b" * 64)), APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_receipt_shape_is_opaque_and_product_routes_remain_unwired(db):
    seed(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(), now=NOW))
    columns = [r[1] for r in db.db.execute(
        "PRAGMA table_info(padiem_engine_browser_control_p01_receipts)"
    ).fetchall()]
    assert not any(x in columns for x in (
        "arguments", "approval_payload", "access_token", "cookie",
        "action", "origin_url", "user_message",
    ))
    assert ENGINE_BROWSER_CONTROL_P01_RECEIPT_PRODUCER_WIRED is False
    assert ENGINE_BROWSER_CONTROL_P01_RECEIPT_READER_WIRED is False


@pytest.mark.parametrize("mutation", [
    {"approval_scope": ("process.execute",)},
    {"approval_scope": ("browser.control", "process.execute")},
    {"expires_at": NOW + timedelta(minutes=1)},
    {"tool_id": "process.execute"},
    {"run_id": "run.changed"},
])
def test_canonical_pause_changes_hide_previously_saved_receipt(db, mutation):
    original = pause()
    seed(db, original)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    run(store.store_completed(approved(original), now=NOW))
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW))
    db.db.execute(
        "UPDATE padiem_engine_continuations SET pause_json=? "
        "WHERE app_id=? AND continuation_ref=?",
        (_pause_json(replace(original, **mutation)), APP_ID, CONT_REF),
    )
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_approval_receipt_cannot_be_written_before_engine_continuation_exists(db):
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="no matching consumed"):
        run(store.store_completed(approved(), now=NOW))
    count = db.db.execute(
        "SELECT COUNT(*) FROM padiem_engine_browser_control_p01_receipts"
    ).fetchone()[0]
    assert count == 0


def test_engine_receipt_migration_is_idempotent_in_synthetic_sqlite(db):
    sql = (MIGRATIONS / "0009_browser_control_p01_receipts.sql").read_text(encoding="utf-8")
    db.db.executescript(sql)
    db.db.executescript(sql)
    assert len([
        col for col in db.db.execute(
            "PRAGMA table_info(padiem_engine_browser_control_p01_receipts)"
        )
        if col[1] == "invocation_sha256"
    ]) == 1


def _claim(db, *, state="claimed", token="claim_browser.3782", p=None, ref=CONT_REF):
    seed(db, p, state=state, continuation_ref=ref)
    db.db.execute(
        "UPDATE padiem_engine_continuations SET claim_token=? "
        "WHERE app_id=? AND continuation_ref=?",
        (token, APP_ID, ref),
    )
    db.db.commit()


def _status(db, ref=CONT_REF):
    row = db.db.execute(
        "SELECT state, claim_token FROM padiem_engine_continuations "
        "WHERE app_id=? AND continuation_ref=?", (APP_ID, ref),
    ).fetchone()
    return tuple(row) if row else None


def _atomic_commit(store, *, token="claim_browser.3782", p=None, d=None, ref=CONT_REF):
    p = p or pause()
    return run(store.commit_claimed_browser_approval(
        app_id=APP_ID, continuation_ref=ref, claim_token=token,
        pause=p, decision=d or decision(p), now=NOW,
    ))


def test_claim_and_receipt_are_one_atomic_d1_transaction(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    receipt = _atomic_commit(store)
    assert _status(db) == ("consumed", None)
    assert receipt == approved()
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) == receipt
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store)
    assert _status(db) == ("consumed", None)


@pytest.mark.parametrize("bad_state", ["active", "consumed", "cancelled", "expired", "cancelling"])
def test_no_claim_cannot_atomically_commit_receipt(db, bad_state):
    _claim(db, state=bad_state, token=None)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store)
    assert _status(db) == (bad_state, None)
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_wrong_claim_token_has_zero_consumption_and_zero_receipt(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises(ValueError, match="not completed"):
        _atomic_commit(store, token="claim_other.3782")
    assert _status(db) == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None
    assert _atomic_commit(store) == approved()


@pytest.mark.parametrize("pause_change", [
    {"run_id": "run.other"},
    {"invocation_sha256": "b" * 64},
    {"approval_scope": ("process.execute",)},
    {"expires_at": NOW + timedelta(minutes=1)},
])
def test_pause_drift_rolls_back_claimed_state(db, pause_change):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    try:
        _atomic_commit(store, p=pause(**pause_change))
    except (ValueError, AgentApprovalError):
        pass
    else:
        pytest.fail("pause drift was accepted")
    assert _status(db) == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(app_id=APP_ID, continuation_ref=CONT_REF, now=NOW)) is None


def test_duplicate_decision_causes_transaction_rollback_on_second_claim(db):
    _claim(db)
    _claim(db, ref="cont_secondary.3782")
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    _atomic_commit(store)
    with pytest.raises(ValueError, match="commit failed"):
        _atomic_commit(store, ref="cont_secondary.3782")
    assert _status(db, "cont_secondary.3782") == ("claimed", "claim_browser.3782")
    assert run(store.resolve_active(
        app_id=APP_ID, continuation_ref="cont_secondary.3782", now=NOW,
    )) is None


def test_no_d1_batch_never_downgrades_to_multi_transaction_write(db):
    _claim(db)
    original_batch = db.batch
    db.batch = None
    try:
        with pytest.raises(TypeError, match="batch is required"):
            _atomic_commit(CloudflareD1BrowserControlP01ReceiptStore(db))
    finally:
        db.batch = original_batch
    assert _status(db) == ("claimed", "claim_browser.3782")


def test_wrong_decision_or_tool_cannot_commit_browser_receipt(db):
    _claim(db)
    store = CloudflareD1BrowserControlP01ReceiptStore(db)
    with pytest.raises((ValueError, AgentApprovalError)):
        _atomic_commit(store, d=decision(outcome=ApprovalOutcome.DENIED))
    assert _status(db) == ("claimed", "claim_browser.3782")
    with pytest.raises((ValueError, AgentApprovalError)):
        _atomic_commit(store, p=pause(tool_id="process.execute"))
    assert _status(db) == ("claimed", "claim_browser.3782")
