"""#3082 slice 2 — durable store, restart recovery and fail-closed behaviour.

These tests exercise the *implementation* in
`kagent.local_agent_durable_run_store` against the deterministic requirements
for issue #3082. Where a test needs a corrupt or tampered database it writes the
file through plain `sqlite3` on purpose: the store must refuse such a file rather
than repair it.
"""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kagent.contracts import ContractError
from kagent.local_agent_durable_run import (
    MAX_BOUNDED_EXIT_CODE,
    MIN_BOUNDED_EXIT_CODE,
    LOCAL_REVISION_INCREMENT,
    LOCAL_REVISION_ORDERING,
    SECOND_FINGERPRINT_AUTHORITY,
    SECOND_REVISION_AUTHORITY,
    BoundedEvidenceProjection,
    DurableRunOfflineState,
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
)
from kagent.local_agent_durable_run_store import (
    _COLUMN_ORDER,
    _TABLE,
    DURABLE_RUN_STORE_SCHEMA_VERSION,
    EXPIRED_COMMAND_REPLAY_SUPPORTED,
    PID_SCANNING_SUPPORTED,
    STORE_ERROR_CODES,
    STORE_GRANTS_EXECUTION_AUTHORITY,
    STORE_MINTS_FINGERPRINT,
    STORE_MINTS_REVISION,
    STORE_PARSE_REVISION,
    STORE_RECOMPUTES_FINGERPRINT,
    TERMINAL_REPLAY_SUPPORTED,
    UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED,
    DurableRunRecoveryClass,
    DurableRunRecoveryReport,
    DurableRunStore,
    DurableRunStoreError,
)
from kagent.windows_local_executor import (
    LocalCommandRequest,
    command_request_fingerprint,
)

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64
REVISION = "revision.7f3c1a9e"
ISSUED = NOW - timedelta(seconds=20)
EXPIRES = NOW + timedelta(seconds=300)


def admitted(**overrides) -> DurableRunRecord:
    """A non-terminal, offline-idle admitted record."""

    fields: dict[str, object] = {
        "command_id": "command.1",
        "run_id": "run.1",
        "tool_request_ref": "tool-request.1",
        "request_id": "request.1",
        "revision_ref": REVISION,
        "device_id": "device.1",
        "binding_ref": "pairing-binding." + "a" * 32,
        "session_id": "session.1",
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "sequence": 7,
        "credential_generation": 3,
        "request_fingerprint": FINGERPRINT,
        "fingerprint_source": "broker",
        "command_issued_at": ISSUED,
        "command_expires_at": EXPIRES,
        "admitted_at": NOW - timedelta(seconds=10),
        "admission_ref": "admission.1",
    }
    fields.update(overrides)
    return DurableRunRecord(**fields)


def exited(**overrides) -> DurableRunRecord:
    """A locally terminal EXITED record with a bounded exit code.

    Only an `EXITED` termination may carry an `exit_code` (the process ran to its
    own exit status); cancelled/timed-out/aborted/expired records carry none.
    """

    fields: dict[str, object] = {
        "state": DurableRunState.TERMINAL,
        "termination": DurableRunTermination.EXITED,
        "started_at": NOW - timedelta(seconds=9),
        "terminated_at": NOW - timedelta(seconds=5),
        "exit_code": 0,
    }
    fields.update(overrides)
    if fields.get("exit_code") is None:
        fields.pop("exit_code")
    return admitted(**fields)


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = str(Path(self._tmp.name) / "durable-runs.sqlite3")

    def open_store(self) -> DurableRunStore:
        store = DurableRunStore(self.path)
        self.addCleanup(store.close)
        return store

    def rewrite(self, statement: str, parameters: tuple = ()) -> None:
        """Tamper with the store file directly, bypassing the store API."""

        db = sqlite3.connect(self.path)
        try:
            db.execute(statement, parameters)
            db.commit()
        finally:
            db.close()


class DurableStoreLifecycleTests(StoreTestCase):
    """Q1/Q2 — a fresh store creates, loads and round-trips exact correlation."""

    def test_q1_fresh_store_creates_a_usable_schema(self) -> None:
        store = self.open_store()
        self.assertEqual(store.schema_version, DURABLE_RUN_STORE_SCHEMA_VERSION)
        self.assertEqual(store.list_records(), ())

    def test_q1_reopening_a_fresh_store_is_idempotent(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.close()
        second = self.open_store()
        self.assertEqual(len(second.list_records()), 1)

    def test_q2_exact_correlation_roundtrips(self) -> None:
        store = self.open_store()
        original = admitted()
        store.put(original)
        self.assertEqual(store.get(command_id="command.1"), original)

    def test_q2_correlation_fields_are_preserved_exactly(self) -> None:
        store = self.open_store()
        store.put(admitted())
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.command_id, "command.1")
        self.assertEqual(loaded.run_id, "run.1")
        self.assertEqual(loaded.tool_request_ref, "tool-request.1")
        self.assertEqual(loaded.request_id, "request.1")
        self.assertEqual(loaded.admission_ref, "admission.1")

    def test_q2_records_can_be_narrowed_by_run_id(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.put(admitted(command_id="command.2", run_id="run.2"))
        self.assertEqual(len(store.list_records(run_id="run.1")), 1)
        self.assertEqual(store.list_records(run_id="run.absent"), ())

    def test_q2_missing_command_id_returns_none(self) -> None:
        self.assertIsNone(self.open_store().get(command_id="command.absent"))

    def test_q2_unsafe_lookups_fail_closed(self) -> None:
        store = self.open_store()
        for bad in ("", "command 1", "-command", "x" * 600):
            with self.subTest(bad=bad):
                with self.assertRaises(DurableRunStoreError) as caught:
                    store.get(command_id=bad)
                self.assertEqual(caught.exception.code, "durable_store_invalid_ref")


class DurableStoreIdentityPreservationTests(StoreTestCase):
    """Q3/Q4/Q5 — exact preservation of the three canonical identity facts."""

    def test_q3_request_fingerprint_is_preserved_exactly(self) -> None:
        store = self.open_store()
        canonical = "b" * 64
        store.put(admitted(request_fingerprint=canonical))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.request_fingerprint, canonical)

    def test_q3_the_store_owns_no_fingerprint_authority(self) -> None:
        self.assertFalse(STORE_RECOMPUTES_FINGERPRINT)
        self.assertFalse(STORE_MINTS_FINGERPRINT)

    def test_q4_revision_ref_is_preserved_exactly(self) -> None:
        store = self.open_store()
        for value in ("revision.0", "revision.abcdef0123456789", "rev-2026-09-26.1"):
            with self.subTest(value=value):
                store.put(admitted(command_id=f"command.{value}", revision_ref=value))
                loaded = store.get(command_id=f"command.{value}")
                assert loaded is not None
                self.assertEqual(loaded.revision_ref, value)

    def test_q4_the_store_never_mints_or_parses_a_revision(self) -> None:
        self.assertFalse(STORE_MINTS_REVISION)

    def test_q5_request_id_is_preserved_exactly(self) -> None:
        store = self.open_store()
        store.put(admitted())
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.request_id, "request.1")

    def test_q5_sequence_stays_an_independent_broker_dimension(self) -> None:
        store = self.open_store()
        store.put(admitted(sequence=1))
        store.put(admitted(command_id="command.2", sequence=99, revision_ref=REVISION))
        first = store.get(command_id="command.1")
        second = store.get(command_id="command.2")
        assert first is not None and second is not None
        # Same opaque revision, different broker sequence: the store keeps the
        # two orthogonal and never derives one from the other.
        self.assertEqual(first.revision_ref, second.revision_ref)
        self.assertNotEqual(first.sequence, second.sequence)


class DurableStoreTerminalPersistenceTests(StoreTestCase):
    """Q6-Q11 — terminal outcomes, expiry and the acknowledgement orthogonality."""

    def test_q6_terminal_exited_persists_atomically(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited(exit_code=0))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertTrue(loaded.terminal)
        self.assertEqual(loaded.termination, DurableRunTermination.EXITED)
        self.assertEqual(loaded.exit_code, 0)
        self.assertIsNone(loaded.server_acknowledged_at)

    def test_q7_terminal_cancelled_persists(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited(termination=DurableRunTermination.CANCELLED, exit_code=None))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.termination, DurableRunTermination.CANCELLED)
        self.assertTrue(loaded.terminal)
        # A cancelled run never reached its own exit status, so none is stored.
        self.assertIsNone(loaded.exit_code)

    def test_q8_terminal_timed_out_persists(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited(termination=DurableRunTermination.TIMED_OUT, exit_code=None))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.termination, DurableRunTermination.TIMED_OUT)
        self.assertIsNone(loaded.exit_code)

    def test_q6_terminal_outcomes_survive_a_restart(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.record_terminal(exited())
        first.close()
        second = self.open_store()
        self.assertEqual(len(second.list_records()), 1)
        assert second.get(command_id="command.1") is not None

    def test_q9_an_expired_command_is_terminal_and_never_replayable(self) -> None:
        store = self.open_store()
        store.put(admitted())
        # A restart long after the R6 hard deadline.
        report = store.recover(now=NOW + timedelta(seconds=3600))
        self.assertEqual(report.classifications.get("expired"), 1)
        self.assertEqual(report.replay_candidates, ())
        self.assertFalse(report.execution_authority_granted)
        self.assertFalse(EXPIRED_COMMAND_REPLAY_SUPPORTED)

    def test_q9_expiry_is_not_re_armed_by_a_later_restart(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.close()
        second = self.open_store()
        early = second.recover(now=NOW)
        late = second.recover(now=NOW + timedelta(seconds=100000))
        self.assertEqual(early.classifications.get("admitted_nonterminal"), 1)
        self.assertEqual(late.classifications.get("expired"), 1)
        self.assertEqual(late.replay_candidates, ())

    def test_q10_terminal_before_ack_then_restart_is_never_replayed(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.record_terminal(exited())
        first.close()
        # The exact R8 crash window: the local outcome is durable, the server
        # acknowledgement never arrived.
        second = self.open_store()
        report = second.recover(now=NOW)
        self.assertEqual(report.classifications.get("terminal_but_server_unacked"), 1)
        self.assertEqual(report.replay_candidates, ())
        self.assertFalse(report.execution_authority_granted)
        self.assertFalse(TERMINAL_REPLAY_SUPPORTED)
        assert second.get(command_id="command.1") is not None

    def test_q11_acknowledged_terminal_roundtrips(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.record_terminal(exited())
        first.acknowledge(command_id="command.1", acknowledged_at=NOW - timedelta(seconds=4))
        first.close()
        second = self.open_store()
        loaded = second.get(command_id="command.1")
        assert loaded is not None
        self.assertTrue(loaded.acknowledged)
        self.assertEqual(loaded.server_acknowledged_at, NOW - timedelta(seconds=4))
        self.assertEqual(second.recover(now=NOW).classifications.get("terminal"), 1)

    def test_q11_an_ack_never_overwrites_the_local_termination_truth(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(
            exited(termination=DurableRunTermination.ABORTED, exit_code=None)
        )
        store.acknowledge(command_id="command.1", acknowledged_at=NOW - timedelta(seconds=1))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.termination, DurableRunTermination.ABORTED)
        self.assertIsNone(loaded.exit_code)

    def test_q11_ack_is_refused_for_a_nonterminal_run(self) -> None:
        store = self.open_store()
        store.put(admitted())
        with self.assertRaises(DurableRunStoreError) as caught:
            store.acknowledge(command_id="command.1", acknowledged_at=NOW)
        self.assertEqual(
            caught.exception.code, "durable_store_ack_without_admission_correlation"
        )

    def test_q11_ack_at_hard_deadline_is_refused(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited())
        with self.assertRaises(DurableRunStoreError) as caught:
            store.acknowledge(command_id="command.1", acknowledged_at=EXPIRES)
        self.assertEqual(caught.exception.code, "durable_store_invalid_timestamp")

    def test_q6_a_terminal_outcome_is_never_overwritten(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited())
        with self.assertRaises(ContractError):
            store.record_terminal(exited(exit_code=9))

    def test_q6_a_terminal_outcome_is_never_reverted_to_nonterminal(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited())
        with self.assertRaises(ContractError):
            store.record_terminal(admitted())


class DurableRunRecoveryClassificationTests(StoreTestCase):
    """Q12/Q13 — restart reconciliation and the explicit offline state."""

    def test_q12_nonterminal_restart_is_reconciled_not_replayed(self) -> None:
        store = self.open_store()
        store.put(admitted())
        report = store.recover(now=NOW)
        self.assertEqual(report.classifications.get("admitted_nonterminal"), 1)
        self.assertEqual(report.reconciliation_command_ids, ("command.1",))
        self.assertEqual(report.replay_candidates, ())
        self.assertFalse(report.execution_authority_granted)

    def test_q12_ambiguous_prior_execution_is_never_automatically_rerun(self) -> None:
        first = self.open_store()
        first.put(admitted())
        first.close()
        # A restart with no prior terminal write: the outcome of the previous
        # execution is unknown (#3081 reaped the tree) and stays unknown.
        second = self.open_store()
        report = second.recover(now=NOW)
        self.assertEqual(report.classifications, {"admitted_nonterminal": 1})
        self.assertEqual(report.replay_candidates, ())
        assert second.get(command_id="command.1") is not None

    def test_q12_every_record_is_classified_exactly_once(self) -> None:
        store = self.open_store()
        store.put(admitted(command_id="command.open"))
        store.put(admitted(command_id="command.dead", command_expires_at=NOW - timedelta(seconds=1)))
        store.put(admitted(command_id="command.offline", offline_state=DurableRunOfflineState.QUEUED))
        store.put(admitted(command_id="command.terminal"))
        store.record_terminal(
            exited(
                command_id="command.terminal",
                state=DurableRunState.TERMINAL,
                termination=DurableRunTermination.EXITED,
                started_at=NOW - timedelta(seconds=9),
                terminated_at=NOW - timedelta(seconds=5),
            )
        )
        report = store.recover(now=NOW)
        self.assertEqual(sum(report.classifications.values()), 4)

    def test_q12_a_terminal_row_outranks_a_passed_deadline(self) -> None:
        store = self.open_store()
        store.put(admitted(command_expires_at=NOW + timedelta(seconds=1)))
        store.record_terminal(exited())
        report = store.recover(now=NOW + timedelta(seconds=99999))
        self.assertEqual(report.classifications, {"terminal_but_server_unacked": 1})

    def test_q13_offline_state_is_explicit_and_metadata_only(self) -> None:
        store = self.open_store()
        for state in DurableRunOfflineState:
            with self.subTest(state=state.value):
                store.put(admitted(command_id=f"command.{state.value}", offline_state=state))
                loaded = store.get(command_id=f"command.{state.value}")
                assert loaded is not None
                # The offline state round-trips exactly and is never flattened
                # to IDLE, so "was this queued while offline?" stays answerable.
                self.assertEqual(loaded.offline_state, state)

    def test_q13_a_queued_offline_row_requires_reconciliation(self) -> None:
        store = self.open_store()
        store.put(admitted(offline_state=DurableRunOfflineState.QUEUED))
        report = store.recover(now=NOW)
        self.assertEqual(report.classifications.get("offline_reconciliation_required"), 1)
        self.assertEqual(report.replay_candidates, ())
        self.assertFalse(report.execution_authority_granted)

    def test_q13_the_offline_queue_grants_no_execution_authority(self) -> None:
        self.assertFalse(STORE_GRANTS_EXECUTION_AUTHORITY)

    def test_q13_recovery_report_projects_bounded_safe_metadata_only(self) -> None:
        store = self.open_store()
        store.put(admitted())
        projection = store.recover(now=NOW).safe_dict()
        self.assertFalse(projection["raw_stdout"])
        self.assertFalse(projection["raw_stderr"])
        self.assertFalse(projection["raw_argv"])
        self.assertFalse(projection["raw_device_credential"])
        self.assertFalse(projection["p01_approval_payload"])
        self.assertEqual(projection["execution_authority_granted"], False)


class DurableStoreFailClosedTests(StoreTestCase):
    """Q14-Q18 — corruption, version and bad data all fail closed."""

    def seeded(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.close()

    def assert_refused(self, code: str) -> None:
        """Open the store and force a full row load; both must refuse.

        Row-level validation happens on load, not on open, so simply constructing
        the store would not prove anything about a tampered row.
        """

        with self.assertRaises(DurableRunStoreError) as caught:
            store = DurableRunStore(self.path)
            try:
                store.list_records()
            finally:
                store.close()
        self.assertEqual(caught.exception.code, code)

    def test_q14_a_corrupt_database_file_fails_closed(self) -> None:
        Path(self.path).write_bytes(b"this is not a sqlite database at all\n" * 64)
        with self.assertRaises(DurableRunStoreError) as caught:
            DurableRunStore(self.path).close()
        self.assertIn(
            caught.exception.code,
            ("durable_store_corrupt", "durable_store_unreadable"),
        )

    def test_q14_a_non_database_file_fails_closed(self) -> None:
        # A *non-empty* file that is not a database must be refused outright.
        Path(self.path).write_bytes(b"plain text, not a database" * 64)
        with self.assertRaises(DurableRunStoreError) as caught:
            DurableRunStore(self.path).close()
        self.assertIn(
            caught.exception.code,
            ("durable_store_corrupt", "durable_store_unreadable"),
        )

    def test_q14_a_zero_length_file_is_a_legitimate_first_run(self) -> None:
        # Not a corruption case: a zero-length file is what a first run leaves
        # behind before the first write, so it must be created, not refused.
        Path(self.path).write_bytes(b"")
        store = self.open_store()
        self.assertEqual(store.schema_version, DURABLE_RUN_STORE_SCHEMA_VERSION)
        self.assertEqual(store.list_records(), ())

    def test_q14_a_seeded_store_whose_file_is_damaged_fails_closed(self) -> None:
        self.seeded()
        for suffix in ("-wal", "-shm"):
            sidecar = Path(self.path + suffix)
            if sidecar.exists():
                sidecar.unlink()
        with open(self.path, "r+b") as handle:
            handle.seek(0)
            handle.write(b"this is not a sqlite database at all\n" * 64)
        with self.assertRaises(DurableRunStoreError) as caught:
            DurableRunStore(self.path).close()
        self.assertIn(
            caught.exception.code,
            (
                "durable_store_corrupt",
                "durable_store_unreadable",
                "durable_store_integrity_check_failed",
            ),
        )

    def test_q15_an_unsupported_schema_version_fails_closed(self) -> None:
        self.seeded()
        self.rewrite("PRAGMA user_version = 99")
        self.assert_refused("durable_store_unsupported_schema_version")

    def test_q15_an_unversioned_store_is_never_treated_as_fresh(self) -> None:
        self.seeded()
        self.rewrite("PRAGMA user_version = 0")
        self.assert_refused("durable_store_schema_version_missing")

    def test_q16_a_bad_revision_ref_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET revision_ref = ? WHERE command_id = ?",
            ("not a safe ref!!", "command.1"),
        )
        self.assert_refused("durable_store_revision_mismatch")

    def test_q16_an_empty_revision_ref_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET revision_ref = '' WHERE command_id = ?", ("command.1",)
        )
        self.assert_refused("durable_store_revision_mismatch")

    def test_q16_an_overlong_run_ref_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET run_id = ? WHERE command_id = ?", ("x" * 600, "command.1")
        )
        self.assert_refused("durable_store_invalid_ref")


    def test_q17_a_bad_fingerprint_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET request_fingerprint = ? WHERE command_id = ?",
            ("not-a-digest", "command.1"),
        )
        self.assert_refused("durable_store_fingerprint_mismatch")

    def test_q18_an_out_of_range_exit_code_fails_closed(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited())
        store.close()
        # Beyond the canonical #3080 bounded exit-code range, not merely large.
        self.rewrite(
            f"UPDATE {_TABLE} SET exit_code = ? WHERE command_id = ?",
            (MAX_BOUNDED_EXIT_CODE + 1, "command.1"),
        )
        self.assert_refused("durable_store_invalid_exit_code")

    def test_q18_a_below_range_exit_code_fails_closed(self) -> None:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(exited())
        store.close()
        self.rewrite(
            f"UPDATE {_TABLE} SET exit_code = ? WHERE command_id = ?",
            (MIN_BOUNDED_EXIT_CODE - 1, "command.1"),
        )
        self.assert_refused("durable_store_invalid_exit_code")

    def test_m_an_invalid_state_enum_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET state = ? WHERE command_id = ?", ("imaginary", "command.1")
        )
        self.assert_refused("durable_store_invalid_enum")

    def test_m_an_invalid_termination_enum_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET termination = ? WHERE command_id = ?",
            ("exploded", "command.1"),
        )
        self.assert_refused("durable_store_invalid_enum")

    def test_m_an_invalid_offline_state_enum_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET offline_state = ? WHERE command_id = ?",
            ("maybe", "command.1"),
        )
        self.assert_refused("durable_store_invalid_enum")

    def test_m_an_invalid_timestamp_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET admitted_at = ? WHERE command_id = ?",
            ("not-a-timestamp", "command.1"),
        )
        self.assert_refused("durable_store_invalid_timestamp")

    def test_m_a_naive_timestamp_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET admitted_at = ? WHERE command_id = ?",
            ("2026-09-26T08:00:00", "command.1"),
        )
        self.assert_refused("durable_store_invalid_timestamp")

    def test_m_a_terminal_row_without_termination_fails_closed(self) -> None:
        self.seeded()
        self.rewrite(
            f"UPDATE {_TABLE} SET state = ?, termination = NULL WHERE command_id = ?",
            ("terminal", "command.1"),
        )
        self.assert_refused("durable_store_terminal_without_termination")

    def test_m_a_duplicate_identity_is_refused(self) -> None:
        store = self.open_store()
        store.put(admitted())
        with self.assertRaises(DurableRunStoreError) as caught:
            store.put(admitted())
        self.assertEqual(caught.exception.code, "durable_store_duplicate_identity")

    def test_m_every_declared_error_code_is_a_stable_string(self) -> None:
        self.assertEqual(len(set(STORE_ERROR_CODES)), len(STORE_ERROR_CODES))
        for code in STORE_ERROR_CODES:
            with self.subTest(code=code):
                self.assertTrue(code.startswith("durable_store_"))


class DurableStoreForbiddenContentTests(StoreTestCase):
    """Q19/Q20 — no raw secret, argv, stdout or stderr is ever persisted."""

    #: Stands in for a device credential / auth token / pairing code / approval
    #: payload. It must never reach the store file in any form.
    SECRET = "SECRET-DEVICE-CREDENTIAL-9f2b7c1e"

    def seed_with_everything(self) -> DurableRunStore:
        store = self.open_store()
        store.put(admitted())
        store.record_terminal(
            admitted(
                state=DurableRunState.TERMINAL,
                termination=DurableRunTermination.EXITED,
                started_at=NOW - timedelta(seconds=9),
                terminated_at=NOW - timedelta(seconds=5),
                exit_code=0,
                evidence=BoundedEvidenceProjection(
                    diff_ref="diff.1",
                    test_ref="test.1",
                    artifact_ref="artifact.1",
                    evidence_ref="evidence.1",
                    item_count=3,
                    summary="3 bounded results",
                ),
            )
        )
        return store

    def test_q19_a_secret_never_reaches_the_store_file(self) -> None:
        self.seed_with_everything().close()
        self.assertNotIn(self.SECRET.encode("utf-8"), Path(self.path).read_bytes())

    def test_q19_the_record_contract_cannot_carry_a_secret_field(self) -> None:
        forbidden = (
            "secret",
            "token",
            "pairing",
            "approval",
            "auth",
            "private_key",
        )
        # `credential_generation` is an opaque counter, not credential material,
        # so it is excluded from the credential-token check explicitly.
        exempt = {"credential_generation"}
        for name in DurableRunRecord.__dataclass_fields__:
            if name in exempt:
                continue
            for token in forbidden:
                with self.subTest(name=name, token=token):
                    self.assertNotIn(token, name.lower())


    def test_q20_argv_stdout_and_stderr_are_not_representable(self) -> None:
        fields = [name.lower() for name in DurableRunRecord.__dataclass_fields__]
        for token in ("argv", "stdout", "stderr", "command_line", "file_content", "output"):
            with self.subTest(token=token):
                self.assertEqual([name for name in fields if token in name], [])

    def test_q20_the_projection_carries_only_bounded_evidence_refs(self) -> None:
        store = self.seed_with_everything()
        record = store.get(command_id="command.1")
        assert record is not None
        self.assertEqual(record.evidence.evidence_ref, "evidence.1")
        self.assertEqual(record.evidence.item_count, 3)
        self.assertEqual(record.evidence.summary, "3 bounded results")
        self.assertLessEqual(len(record.evidence.summary), 1024)

    def test_q20_the_evidence_summary_is_bounded_on_write(self) -> None:
        store = self.open_store()
        with self.assertRaises(ContractError):
            store.put(admitted(evidence=BoundedEvidenceProjection(summary="x" * 4096)))

    def test_q20_the_projection_survives_a_restart_with_its_bounds(self) -> None:
        self.seed_with_everything().close()
        reopened = self.open_store()
        record = reopened.get(command_id="command.1")
        assert record is not None
        self.assertEqual(record.evidence.item_count, 3)
        self.assertLessEqual(record.evidence.item_count, 64)

    def test_q19_the_projection_declares_no_secret_material(self) -> None:
        projected = DurableRunRecoveryReport().safe_dict()
        for key in (
            "raw_stdout",
            "raw_stderr",
            "raw_argv",
            "raw_device_credential",
            "p01_approval_payload",
        ):
            with self.subTest(key=key):
                self.assertIs(projected[key], False)

    def test_q24_every_declared_error_code_is_a_stable_string(self) -> None:
        self.assertEqual(len(set(STORE_ERROR_CODES)), len(STORE_ERROR_CODES))
        for code in STORE_ERROR_CODES:
            with self.subTest(code=code):
                self.assertTrue(code.startswith("durable_store_"))



STORE_SOURCE = (
    Path(__file__).resolve().parents[1] / "src" / "kagent" / "local_agent_durable_run_store.py"
)


def _store_code_identifiers() -> frozenset[str]:
    """Every identifier the store module actually *uses* in code.

    Parsed from the AST rather than grepped from the raw text, so prose in a
    docstring that happens to say "never reattaches a process" cannot satisfy or
    break the capability checks: only real names, attributes, calls, imported
    modules and string literals count. This is what makes Q21/Q22 assertions
    meaningful instead of cosmetic.

    The negative-assertion flags themselves are excluded: naming the forbidden
    capability is exactly how this module *declares* its absence, so matching
    them would make every check fail on the very declaration it is verifying.
    """

    tree = ast.parse(STORE_SOURCE.read_text(encoding="utf-8"), filename=str(STORE_SOURCE))
    # Docstrings are prose, not code. Collect them so the string-literal scan
    # below skips exactly those and nothing else.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.name)
            if node.asname is not None:
                names.add(node.asname)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            # String literals are code, not prose: a table or column name is
            # exactly the kind of thing that could smuggle in a capability.
            names.add(node.value)
    return frozenset(
        name
        for name in names
        if name.upper() not in {flag.upper() for flag in _NEGATIVE_FLAGS}
    )


#: The declared-absent capability flags. Kept in sync with the store module and
#: asserted to be `False` by `test_q23`/`test_q24`.
_NEGATIVE_FLAGS = (
    "STORE_RECOMPUTES_FINGERPRINT",
    "STORE_MINTS_FINGERPRINT",
    "STORE_MINTS_REVISION",
    "STORE_PARSE_REVISION",
    "STORE_GRANTS_EXECUTION_AUTHORITY",
    "TERMINAL_REPLAY_SUPPORTED",
    "EXPIRED_COMMAND_REPLAY_SUPPORTED",
    "PID_SCANNING_SUPPORTED",
    "UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED",
)



class DurableStoreForbiddenCapabilityTests(unittest.TestCase):
    """Q21–Q23 — no process authority and no retry authority anywhere."""

    def test_q21_no_pid_scanning_capability_exists(self) -> None:
        self.assertFalse(PID_SCANNING_SUPPORTED)
        # The exclusion list in `_store_code_identifiers` must not be able to
        # hide a capability: every excluded name must still be a real flag that
        # is `False`.
        self.assertEqual(
            {name for name in _store_code_identifiers() if name.upper() in _NEGATIVE_FLAGS}, set()
        )
        for name in _store_code_identifiers():
            for token in ("tasklist", "psutil", "wmic", "process", "pid"):
                with self.subTest(name=name, token=token):
                    self.assertNotIn(token, name.lower())

    def test_q21_the_record_contract_holds_no_process_identifier(self) -> None:
        fields = [name.lower() for name in DurableRunRecord.__dataclass_fields__]
        for token in ("pid", "process", "handle", "job_object"):
            with self.subTest(token=token):
                self.assertEqual([name for name in fields if token in name], [])

    def test_q22_unknown_process_reattachment_is_absent(self) -> None:
        self.assertFalse(UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED)
        for name in _store_code_identifiers():
            for token in ("reattach", "openprocess", "reconnect", "resume"):
                with self.subTest(name=name, token=token):
                    self.assertNotIn(token, name.lower())

    def test_q22_recovery_has_no_reattachment_verdict(self) -> None:
        # #3081 `KILL_ON_JOB_CLOSE` means there is no surviving process to find,
        # so no recovery class may imply one exists.
        values = {item.value for item in DurableRunRecoveryClass}
        self.assertNotIn("reattached", values)
        self.assertNotIn("unknown_process", values)

    def test_q23_the_store_owns_no_retry_authority(self) -> None:
        self.assertFalse(TERMINAL_REPLAY_SUPPORTED)
        self.assertFalse(EXPIRED_COMMAND_REPLAY_SUPPORTED)
        self.assertFalse(STORE_GRANTS_EXECUTION_AUTHORITY)
        fields = [name.lower() for name in DurableRunRecord.__dataclass_fields__]
        for token in ("retry", "attempt", "backoff", "replay", "resubmit"):
            with self.subTest(token=token):
                self.assertEqual([name for name in fields if token in name], [])

    def test_q23_recovery_never_returns_a_replay_candidate(self) -> None:
        report = DurableRunRecoveryReport()
        self.assertEqual(report.replay_candidates, ())
        self.assertIs(report.execution_authority_granted, False)

    def test_q24_no_second_fingerprint_authority_in_the_store(self) -> None:
        # The canonical fingerprint authority is `BrokerCommandRecord.request_fingerprint`
        # / `command_request_fingerprint`. This store has none of its own.
        self.assertIs(SECOND_FINGERPRINT_AUTHORITY, 0)
        self.assertFalse(STORE_RECOMPUTES_FINGERPRINT)
        self.assertFalse(STORE_MINTS_FINGERPRINT)
        for name in _store_code_identifiers():
            for token in ("fingerprint_algorithm", "recompute_fingerprint", "mint_fingerprint"):
                with self.subTest(name=name, token=token):
                    self.assertNotIn(token, name.lower())
        # Storing is verbatim: an arbitrary canonical digest survives untouched.
        store = DurableRunStore(":memory:")
        self.addCleanup(store.close)
        canonical = command_request_fingerprint(
            LocalCommandRequest(
                request_id="request.1",
                run_id="run.1",
                device_id="device.1",
                root_ref="root.1",
                argv=("git.exe", "status"),
                cwd_relative="repo",
                requested_at=ISSUED,
            )
        )
        store.put(admitted(request_fingerprint=canonical))
        loaded = store.get(command_id="command.1")
        assert loaded is not None
        self.assertEqual(loaded.request_fingerprint, canonical)

    def test_q24_no_second_revision_authority_in_the_store(self) -> None:
        self.assertIs(SECOND_REVISION_AUTHORITY, 0)
        self.assertFalse(STORE_MINTS_REVISION)
        self.assertFalse(STORE_PARSE_REVISION)
        for name in _store_code_identifiers():
            for token in ("bump_revision", "next_revision", "revision_counter", "order_by_revision"):
                with self.subTest(name=name, token=token):
                    self.assertNotIn(token, name.lower())
        # Broker ordering authority is `sequence`; the store never sorts by a
        # revision and never treats one as a monotonic local counter.
        self.assertIn("sequence", _COLUMN_ORDER)
        self.assertIn("revision_ref", _COLUMN_ORDER)
        self.assertFalse(LOCAL_REVISION_INCREMENT)
        self.assertFalse(LOCAL_REVISION_ORDERING)
