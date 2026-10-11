"""#3669 — canonical durable browser-control lease store tests (CENTRAL ruling §6–§9).

Exercises the implementation in `kagent.browser_control_lease_store` against the
ruling's deterministic requirements:

* idempotent issuance on the UNIQUE request fingerprint, fail-closed on a
  fingerprint/correlation mismatch;
* the DERIVED active facts (no stored lifecycle state): TTL expiry, the
  bounded idle window, the exact N/N+1 budget boundary;
* the in-transaction durable revokes for the cross-origin and idle facts
  (closed vocabulary, monotone, persistent across restarts);
* the explicit `revoke_lease` primitive;
* the restart proof: K consumed slots survive, the next success is K+1, and
  expired/revoked/exhausted rows are non-executable forever;
* the real multiprocess last-slot race: EXACT_SUCCESS_COUNT=1,
  EXACT_REFUSAL_COUNT=1.

Where a test needs a corrupt or tampered database it writes the file through
plain `sqlite3` on purpose: the store must refuse such a file, never repair it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kagent.browser_control_lease_store import (
    BROWSER_CONTROL_LEASE_STORE_SCHEMA_VERSION,
    AUTO_RECOVERY_REAUTHORIZE,
    LEASE_REFUSAL_CODES,
    LEASE_ROW_GC_SUPPORTED,
    REVOKE_REASON_VOCABULARY_IS_OPEN,
    REVOKE_REASONS,
    STORE_GRANTS_EXECUTION_AUTHORITY,
    STORE_MINTS_FINGERPRINT,
    STORE_MINTS_LEASE_ID,
    STORE_RENEWS_LEASE,
    BrowserControlLeaseIssuance,
    BrowserControlLeaseProjection,
    BrowserControlLeaseRefusal,
    BrowserControlLeaseStore,
    BrowserControlLeaseStoreError,
)

APP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_DIR.parent.parent
RACE_CHILD = Path(__file__).resolve().parent / "_browser_control_lease_race_child.py"

NOW = datetime(2026, 10, 8, 9, 0, 0, tzinfo=timezone.utc)
ORIGIN = "https://example.com"
FP = hashlib.sha256(b"3669").hexdigest()  # the one canonical session digest


def make_issuance(request_fingerprint: str = FP, **overrides: object) -> BrowserControlLeaseIssuance:
    fields: dict[str, object] = {
        "request_fingerprint": request_fingerprint,
        "browser_session_ref": "run/session-1",
        "run_ref": "run_3669",
        "workspace_ref": "workspace_3669",
        "owner_ref": "owner_3669",
        "allowed_action_classes": ("click", "type"),
        "origin_scope": ORIGIN,
        "max_actions": 5,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=300),
        "approval_ref": "decision_3669",
        "evidence_ref": "evidence_3669",
    }
    fields.update(overrides)
    return BrowserControlLeaseIssuance(**fields)


def consume(store: BrowserControlLeaseStore, fp: str = FP, *, now: datetime | None = None, **overrides: object) -> BrowserControlLeaseProjection:
    kwargs: dict[str, object] = {
        "browser_session_ref": "run/session-1",
        "run_ref": "run_3669",
        "workspace_ref": "workspace_3669",
        "owner_ref": "owner_3669",
        "action": "click",
        "observed_origin": ORIGIN,
        "now": now or NOW + timedelta(seconds=1),
    }
    kwargs.update(overrides)
    return store.consume_action(fp, **kwargs)


def refusal_code(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    assert isinstance(code, str), f"expected a coded refusal, got {exc!r}"
    return code


class StoreBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="claw-3669-lease-")
        self.path = os.path.join(self._tmp.name, "browser-control-leases.sqlite3")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def store(self) -> BrowserControlLeaseStore:
        return BrowserControlLeaseStore(self.path)


class TestSchemaAndIntegrity(StoreBase):
    def test_a_fresh_store_creates_the_gated_schema(self) -> None:
        with self.store() as store:
            self.assertEqual(store.schema_version, BROWSER_CONTROL_LEASE_STORE_SCHEMA_VERSION)
            db = sqlite3.connect(self.path)
            try:
                objects = {
                    row[0]
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table','index')"
                    ).fetchall()
                }
            finally:
                db.close()
            self.assertIn("claw_browser_control_leases", objects)
            self.assertIn("claw_browser_control_leases_fingerprint", objects)

    def test_a_non_sqlite_file_is_refused(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("this is not a database")
        with self.assertRaises(BrowserControlLeaseStoreError) as ctx:
            BrowserControlLeaseStore(self.path)
        self.assertEqual(ctx.exception.code, "lease_store_corrupt")

    def test_an_unrecognised_schema_version_is_refused(self) -> None:
        with self.store():
            pass
        db = sqlite3.connect(self.path)
        db.execute("PRAGMA user_version = 99")
        db.close()
        with self.assertRaises(BrowserControlLeaseStoreError) as ctx:
            BrowserControlLeaseStore(self.path)
        self.assertEqual(ctx.exception.code, "lease_store_unsupported_schema_version")

    def test_an_invalid_enum_row_is_refused_on_read(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            db = sqlite3.connect(self.path)
            db.execute(
                "UPDATE claw_browser_control_leases SET revoke_reason='made_up' WHERE lease_id=?",
                (projection.lease_id,),
            )
            # Persist the tamper: the default sqlite3 mode rolls back DML on a
            # plain close.
            db.commit()
            db.close()
        with self.store() as store:
            with self.assertRaises(BrowserControlLeaseStoreError) as ctx:
                store.get(FP)
            self.assertEqual(ctx.exception.code, "lease_store_invalid_enum")


class TestIssuance(StoreBase):
    def test_issue_is_idempotent_for_the_same_correlations(self) -> None:
        with self.store() as store:
            projection, issued = store.issue_from_p01(make_issuance())
            self.assertTrue(issued)
            self.assertEqual(projection.consumed_actions, 0)
            again, issued_again = store.issue_from_p01(make_issuance())
            self.assertFalse(issued_again)
            self.assertEqual(again.lease_id, projection.lease_id)
            # The original stamps survive: no renewal of any kind.
            self.assertEqual(again.issued_at, projection.issued_at)
            self.assertEqual(again.expires_at, projection.expires_at)

    def test_the_lease_id_is_a_deterministic_derivation(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            self.assertEqual(projection.lease_id, make_issuance().lease_id)

    def test_a_mismatched_reissue_fails_closed(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.issue_from_p01(make_issuance(run_ref="run_other"))
            self.assertEqual(refusal_code(ctx.exception), "lease_correlation_mismatch")
            # The row is untouched by the failed re-issue.
            self.assertEqual(store.get(FP), projection)

    def test_safe_dict_carries_no_content(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            safe = projection.safe_dict()
            self.assertEqual(safe["raw_page_content"], False)
            self.assertEqual(safe["raw_credential"], False)
            self.assertEqual(safe["p01_approval_payload"], False)


class TestPhaseAResolve(StoreBase):
    def test_resolve_unknown_refuses(self) -> None:
        with self.store() as store:
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW)
            self.assertEqual(refusal_code(ctx.exception), "lease_unknown")

    def test_resolve_is_read_only(self) -> None:
        with self.store() as store:
            issued, _ = store.issue_from_p01(make_issuance())
            projection = store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=10))
            self.assertEqual(projection, issued)
            self.assertEqual(projection.consumed_actions, 0)

    def test_resolve_session_mismatch_refuses(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/other", now=NOW)
            self.assertEqual(refusal_code(ctx.exception), "lease_correlation_mismatch")

    def test_ttl_expiry_refuses_resolve_and_consume(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(expires_at=NOW + timedelta(seconds=300)))
            at_expiry = NOW + timedelta(seconds=300)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=at_expiry)
            self.assertEqual(refusal_code(ctx.exception), "lease_expired")
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=at_expiry)
            self.assertEqual(refusal_code(ctx.exception), "lease_expired")

    def test_idle_before_the_first_action_is_not_a_refusal(self) -> None:
        # Waiting before the first slot is just waiting: only the TTL bounds it.
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            late = NOW + timedelta(seconds=200)
            projection = store.resolve_lease(FP, browser_session_ref="run/session-1", now=late)
            self.assertTrue(projection.active(now=late))

    def test_the_derived_active_fact_tracks_every_boundary(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            self.assertTrue(projection.active(now=NOW + timedelta(seconds=1)))
            # Revoked rows are never active again. Re-read the row after the
            # revoke: the pre-revoke projection is frozen and still sees a
            # null revoked_at.
            revoked = store.revoke_lease(
                projection.lease_id, reason="explicit", now=NOW + timedelta(seconds=2)
            )
            self.assertFalse(revoked.active(now=NOW + timedelta(seconds=3)))


class TestPhaseBConsume(StoreBase):
    def test_consume_is_the_single_slot_owner(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            first = consume(store, now=NOW + timedelta(seconds=1))
            self.assertEqual(first.consumed_actions, 1)
            self.assertEqual(first.last_consumed_at, NOW + timedelta(seconds=1))
            second = consume(store, now=NOW + timedelta(seconds=2))
            self.assertEqual(second.consumed_actions, 2)

    def test_budget_exactly_n_succeeds_and_n_plus_1_refuses(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(max_actions=3))
            for offset in (1, 2, 3):
                projection = consume(store, now=NOW + timedelta(seconds=offset))
                self.assertEqual(projection.consumed_actions, offset)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=NOW + timedelta(seconds=4))
            self.assertEqual(refusal_code(ctx.exception), "action_budget_exhausted")
            # The exhausted row also refuses read-only resolves.
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=4))
            self.assertEqual(refusal_code(ctx.exception), "action_budget_exhausted")
            self.assertEqual(store.get(FP).consumed_actions, 3)

    def test_correlation_mismatch_refuses_without_revoking(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            for field, value in (
                ("run_ref", "run_other"),
                ("workspace_ref", "workspace_other"),
                ("owner_ref", "owner_other"),
            ):
                with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                    consume(store, **{field: value})
                self.assertEqual(refusal_code(ctx.exception), "lease_correlation_mismatch")
            # The lease is still fully usable with its own correlations.
            self.assertEqual(consume(store).consumed_actions, 1)

    def test_unsupported_and_uncovered_actions_refuse_without_writing(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, action="submit")
            self.assertEqual(refusal_code(ctx.exception), "action_not_allowed")
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, action="select")  # eligible, but not in this lease's classes
            self.assertEqual(refusal_code(ctx.exception), "action_not_allowed")
            self.assertEqual(store.get(FP).consumed_actions, 0)

    def test_cross_origin_revokes_in_transaction_and_persists(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            self.assertEqual(consume(store).consumed_actions, 1)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, observed_origin="https://other.example")
            self.assertEqual(refusal_code(ctx.exception), "origin_scope_exceeded")
            row = store.get(FP)
            self.assertEqual(row.revoked_at, NOW + timedelta(seconds=1))
            self.assertEqual(row.revoke_reason, "cross_origin")
            self.assertEqual(row.consumed_actions, 1)  # no increment
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=2))
            self.assertEqual(refusal_code(ctx.exception), "lease_revoked")

        # The revoke survives a restart: the row is non-executable forever.
        with self.store() as store:
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=5))
            self.assertEqual(refusal_code(ctx.exception), "lease_revoked")
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=NOW + timedelta(seconds=5))
            self.assertEqual(refusal_code(ctx.exception), "lease_revoked")

    def test_idle_beyond_the_window_revokes_with_the_closed_reason(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            self.assertEqual(consume(store, now=NOW).consumed_actions, 1)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=NOW + timedelta(seconds=121))
            self.assertEqual(refusal_code(ctx.exception), "lease_idle_exceeded")
            row = store.get(FP)
            self.assertEqual(row.revoke_reason, "idle_expired")
            self.assertEqual(row.consumed_actions, 1)  # no increment

    def test_a_second_consume_inside_the_idle_window_is_admitted(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance())
            self.assertEqual(consume(store, now=NOW).consumed_actions, 1)
            self.assertEqual(consume(store, now=NOW + timedelta(seconds=119)).consumed_actions, 2)


class TestExplicitRevoke(StoreBase):
    def test_explicit_revoke_is_the_one_durable_kill(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            revoked = store.revoke_lease(projection.lease_id, reason="explicit", now=NOW + timedelta(seconds=1))
            self.assertEqual(revoked.revoke_reason, "explicit")
            self.assertEqual(revoked.revoked_at, NOW + timedelta(seconds=1))
            # Monotone: an already-revoked lease is returned, never re-stamped.
            again = store.revoke_lease(projection.lease_id, reason="explicit", now=NOW + timedelta(seconds=9))
            self.assertEqual(again.revoked_at, NOW + timedelta(seconds=1))

    def test_an_open_vocabulary_reason_is_refused(self) -> None:
        with self.store() as store:
            projection, _ = store.issue_from_p01(make_issuance())
            with self.assertRaises(BrowserControlLeaseStoreError) as ctx:
                store.revoke_lease(projection.lease_id, reason="user_made_up", now=NOW)
            self.assertEqual(ctx.exception.code, "lease_store_invalid_enum")

    def test_revoke_unknown_refuses(self) -> None:
        with self.store() as store:
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                # A lease id derived from a fingerprint this store never issued.
                store.revoke_lease(
                    make_issuance(request_fingerprint="9" * 64).lease_id,
                    reason="explicit",
                    now=NOW,
                )
            self.assertEqual(refusal_code(ctx.exception), "lease_unknown")

    def test_the_vocabulary_is_closed_and_stable(self) -> None:
        self.assertEqual(REVOKE_REASONS, ("cross_origin", "idle_expired", "explicit"))
        self.assertFalse(REVOKE_REASON_VOCABULARY_IS_OPEN)


class TestRestart(StoreBase):
    def test_k_consumed_slots_survive_and_the_next_success_is_k_plus_1(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(max_actions=5))
            self.assertEqual(consume(store, now=NOW + timedelta(seconds=1)).consumed_actions, 1)
            self.assertEqual(consume(store, now=NOW + timedelta(seconds=2)).consumed_actions, 2)
        # The process "restarts": a brand-new connection to the same file.
        with self.store() as store:
            projection = store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=3))
            self.assertEqual(projection.consumed_actions, 2)
            self.assertEqual(consume(store, now=NOW + timedelta(seconds=3)).consumed_actions, 3)

    def test_an_expired_row_is_non_executable_after_restart(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(expires_at=NOW + timedelta(seconds=10)))
        with self.store() as store:
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=11))
            self.assertEqual(refusal_code(ctx.exception), "lease_expired")
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=NOW + timedelta(seconds=11))
            self.assertEqual(refusal_code(ctx.exception), "lease_expired")

    def test_the_ruling_markers_are_declared_facts(self) -> None:
        self.assertFalse(STORE_MINTS_LEASE_ID)
        self.assertFalse(STORE_MINTS_FINGERPRINT)
        self.assertFalse(STORE_RENEWS_LEASE)
        self.assertFalse(STORE_GRANTS_EXECUTION_AUTHORITY)
        self.assertFalse(LEASE_ROW_GC_SUPPORTED)
        self.assertFalse(AUTO_RECOVERY_REAUTHORIZE)
        self.assertEqual(len(LEASE_REFUSAL_CODES), 9)


class TestMultiprocessLastSlotRace(StoreBase):
    """The actual multiprocess SQLite race the ruling demands (§6)."""

    def _seed_last_slot(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(max_actions=1))

    def _race(self) -> list[dict[str, object]]:
        self._seed_last_slot()
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [
                str(APP_DIR / "src"),
                str(REPO_ROOT / "packages" / "padiem-ai-core"),
                str(REPO_ROOT / "packages" / "padiem-control-plane"),
                str(REPO_ROOT / "packages" / "padiem-embedded-runtime"),
                env.get("PYTHONPATH", ""),
            ]
        )
        procs = [
            subprocess.Popen(  # noqa: S603 - fixed interpreter, local script
                [
                    sys.executable,
                    str(RACE_CHILD),
                    self.path,
                    FP,
                    "run/session-1",
                    "run_3669",
                    "workspace_3669",
                    "owner_3669",
                    "click",
                    ORIGIN,
                    (NOW + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(APP_DIR),
                env=env,
                text=True,
            )
            for _ in range(2)
        ]
        outcomes: list[dict[str, object]] = []
        for proc in procs:
            out, err = proc.communicate(timeout=180)
            self.assertEqual(proc.returncode, 0, f"racer failed: {err}")
            outcomes.append(json.loads(out.strip().splitlines()[-1]))
        return outcomes

    def test_exactly_one_of_two_concurrent_processes_wins_the_last_slot(self) -> None:
        outcomes = self._race()
        winners = [item for item in outcomes if item["outcome"] == "ok"]
        losers = [item for item in outcomes if item["outcome"] != "ok"]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(winners[0]["consumed_actions"], 1)
        # The loser read the winner's committed state under BEGIN IMMEDIATE,
        # so its refusal is the deterministic budget fact.
        self.assertEqual(losers[0]["outcome"], "action_budget_exhausted")

    def test_after_the_race_the_row_is_exactly_full_and_unrevoked(self) -> None:
        self._race()
        with self.store() as store:
            row = store.get(FP)
            self.assertEqual(row.consumed_actions, 1)
            self.assertIsNone(row.revoked_at)
            # Full: a third process would be refused the same way.
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store)
            self.assertEqual(refusal_code(ctx.exception), "action_budget_exhausted")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestIdleResolveDurableReview(StoreBase):
    """#3669: idle refusal at PHASE A must not leave a reusable lease."""

    def test_first_idle_refusal_revokes_without_spending_slot_and_survives_restart(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(max_actions=3))
            first = consume(store, now=NOW)
            self.assertEqual(first.consumed_actions, 1)
            idle_at = NOW + timedelta(seconds=121)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=idle_at)
            self.assertEqual(refusal_code(ctx.exception), "lease_idle_exceeded")
            row = store.get(FP)
            self.assertEqual(row.revoked_at, idle_at)
            self.assertEqual(row.revoke_reason, "idle_expired")
            self.assertEqual(row.consumed_actions, 1)
        # Roll the wall clock backwards on a fresh process: the durable row,
        # not the process-local timer, still denies every action.
        with self.store() as store:
            earlier = NOW + timedelta(seconds=1)
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                store.resolve_lease(FP, browser_session_ref="run/session-1", now=earlier)
            self.assertEqual(refusal_code(ctx.exception), "lease_revoked")
            with self.assertRaises(BrowserControlLeaseRefusal) as ctx:
                consume(store, now=earlier)
            self.assertEqual(refusal_code(ctx.exception), "lease_revoked")
            self.assertEqual(store.get(FP).consumed_actions, 1)

    def test_active_resolve_remains_read_only_before_idle_limit(self) -> None:
        with self.store() as store:
            store.issue_from_p01(make_issuance(max_actions=3))
            consume(store, now=NOW)
            projection = store.resolve_lease(
                FP, browser_session_ref="run/session-1", now=NOW + timedelta(seconds=120)
            )
            self.assertEqual(projection.consumed_actions, 1)
            self.assertIsNone(store.get(FP).revoked_at)
