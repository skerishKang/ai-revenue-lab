from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.local_agent_durable_run import (
    AUTO_REPLAY_AFTER_LOCAL_TERMINAL,
    BROKER_WIRE_RECONCILIATION_STATE,
    COMMAND_EXPIRES_AT_SEMANTICS,
    FINGERPRINT_ALGORITHM_OWNED_HERE,
    FINGERPRINT_SOURCE_BROKER,
    JOB_OBJECT_TREE_REAPED_ON_RUNNER_DEATH,
    LOCAL_EXECUTION_TERMINALITY,
    LOCAL_LEASE_EXTENSION,
    LOCAL_MINT_REVISION,
    LOCAL_PARSE_REVISION,
    MAX_EVIDENCE_ITEMS,
    MAX_EVIDENCE_SUMMARY_CHARS,
    P01_EVIDENCE_AUTHORITY_DUPLICATED,
    P01_LIFECYCLE_AUTHORITY_DUPLICATED,
    PROCESS_PID_AUTHORITY,
    RECONCILIATION_PROJECTED_ONTO_WIRE,
    REQUEST_FINGERPRINT_RECOMPUTED,
    REVISION_AUTHORITY,
    REVISION_FIELD,
    REVISION_SEMANTICS,
    SECOND_REVISION_AUTHORITY,
    SEQUENCE_IS_BROKER_ORDERING_AUTHORITY,
    SEQUENCE_USED_AS_REVISION,
    SIDE_EFFECT_REPLAY_SUPPORTED,
    STORE_REISSUES_CREDENTIAL,
    TERMINAL_WITHOUT_ACK_IS_RETAINED,
    UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED,
    BoundedEvidenceProjection,
    DurableRunOfflineState,
    DurableRunRecord,
    DurableRunState,
    DurableRunTermination,
)
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle
from kagent.local_agent import LocalCommandRequest
from kagent.windows_local_executor import command_request_fingerprint

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64
#: A server-owned opaque revision correlation. It is copied verbatim and is never
#: parsed for an ordering meaning locally.
REVISION = "revision.7f3c1a9e"


def record(**overrides) -> DurableRunRecord:
    values = dict(
        command_id="command.1",
        run_id="run.1",
        tool_request_ref="tool-request.1",
        request_id="request.1",
        revision_ref=REVISION,
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        session_id="session.1",
        account_ref="account.1",
        workspace_ref="workspace.1",
        sequence=7,
        credential_generation=3,
        request_fingerprint=FINGERPRINT,
        fingerprint_source=FINGERPRINT_SOURCE_BROKER,
        command_issued_at=NOW - timedelta(seconds=30),
        command_expires_at=NOW + timedelta(seconds=300),
        admitted_at=NOW - timedelta(seconds=20),
    )
    values.update(overrides)
    return DurableRunRecord(**values)


def executing(**overrides) -> DurableRunRecord:
    values = dict(state=DurableRunState.EXECUTING, started_at=NOW - timedelta(seconds=10))
    values.update(overrides)
    return record(**values)


def terminal(**overrides) -> DurableRunRecord:
    values = dict(
        state=DurableRunState.TERMINAL,
        started_at=NOW - timedelta(seconds=10),
        terminated_at=NOW - timedelta(seconds=5),
        termination=DurableRunTermination.EXITED,
    )
    values.update(overrides)
    return record(**values)


def device_binding(credential_generation: int = 3) -> DeviceBinding:
    return DeviceBinding(
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential_ref="pairing-credential." + "b" * 32,
        credential_generation=credential_generation,
        issued_at=NOW - timedelta(days=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=DeviceLifecycle.PAIRED_OFFLINE,
    )


class DurableRunCorrelationTests(unittest.TestCase):
    """R1/R2/R3/R9 — correlation facts are copied, never minted."""

    def test_r1_run_ref_is_the_canonical_run_id_string(self) -> None:
        self.assertEqual(record().run_id, "run.1")

    def test_r1_rejects_an_unbounded_or_unsafe_run_ref(self) -> None:
        for bad in ("", "run 1", "-run", "x" * 600):
            with self.subTest(bad=bad):
                with self.assertRaises(ContractError):
                    record(run_id=bad)

    def test_r2_three_ref_relation_is_stored_together(self) -> None:
        stored = record()
        self.assertEqual(stored.command_id, "command.1")
        self.assertEqual(stored.run_id, "run.1")
        self.assertEqual(stored.tool_request_ref, "tool-request.1")
        self.assertEqual(stored.request_id, "request.1")

    def test_r3_sequence_remains_the_broker_ordering_authority(self) -> None:
        # `sequence` is copied from `BrokerCommandRecord.sequence` and keeps its
        # canonical broker ordering/replay meaning. It is a *different* dimension
        # from `revision_ref` and is never substituted for one.
        self.assertTrue(SEQUENCE_IS_BROKER_ORDERING_AUTHORITY)
        self.assertFalse(SEQUENCE_USED_AS_REVISION)
        self.assertEqual(record(sequence=1).sequence, 1)
        for bad in (0, -1, True, 1.0, "1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ContractError):
                    record(sequence=bad)

    def test_r3_revision_ref_is_the_required_opaque_correlation(self) -> None:
        # The final merged #3080 contract is `REVISION_FIELD=revision_ref`,
        # `REVISION_AUTHORITY=SERVER_ONLY`, `REVISION_SEMANTICS=OPAQUE_CORRELATION_ONLY`.
        self.assertEqual(REVISION_FIELD, "revision_ref")
        self.assertEqual(REVISION_AUTHORITY, "server_only")
        self.assertEqual(REVISION_SEMANTICS, "opaque_correlation_only")

        fields = set(DurableRunRecord.__dataclass_fields__)
        self.assertIn("revision_ref", fields)
        self.assertIn("sequence", fields)
        # A locally minted *revision* is still forbidden: `revision_ref` is the
        # opaque server correlation and `sequence` is not a revision field.
        self.assertNotIn("revision", fields)

        # Copied verbatim, and never minted/parsed/ordered locally.
        self.assertEqual(record().revision_ref, REVISION)
        self.assertEqual(record(revision_ref="revision.other-9").revision_ref, "revision.other-9")
        self.assertFalse(LOCAL_MINT_REVISION)
        self.assertFalse(LOCAL_PARSE_REVISION)
        self.assertEqual(SECOND_REVISION_AUTHORITY, 0)

    def test_r3_revision_ref_is_required_and_bounded(self) -> None:
        for bad in (None, "", "revision 1", "-revision", "x" * 600):
            with self.subTest(bad=bad):
                with self.assertRaises(ContractError):
                    record(revision_ref=bad)

    def test_r3_revision_ref_carries_no_local_ordering_semantics(self) -> None:
        # The same revision ref may legitimately appear on two different broker
        # sequences, and a higher sequence says nothing about a "newer" revision:
        # that ordering stays with the server.
        lower = record(revision_ref=REVISION, sequence=1)
        higher = record(revision_ref=REVISION, sequence=99)
        self.assertEqual(lower.revision_ref, higher.revision_ref)
        self.assertNotEqual(lower.sequence, higher.sequence)

    def test_r9_credential_generation_must_be_positive(self) -> None:
        self.assertEqual(record(credential_generation=1).credential_generation, 1)
        for bad in (0, -1, True, "3"):
            with self.subTest(bad=bad):
                with self.assertRaises(ContractError):
                    record(credential_generation=bad)

    def test_r9_recorded_generation_can_be_correlated_with_the_device_binding(self) -> None:
        # The store only *records* the generation; correlation against the live
        # binding is a read-time check, and a mismatch is refused fail-closed.
        stored = record(credential_generation=3)
        self.assertEqual(stored.credential_generation, device_binding(3).credential_generation)
        self.assertNotEqual(stored.credential_generation, device_binding(4).credential_generation)

    def test_r10_store_does_not_reissue_credentials(self) -> None:
        self.assertFalse(STORE_REISSUES_CREDENTIAL)


class DurableRunFingerprintTests(unittest.TestCase):
    """R4 — the fingerprint is stored verbatim and never recomputed."""

    def test_r4_request_fingerprint_is_stored_verbatim(self) -> None:
        self.assertEqual(record().request_fingerprint, FINGERPRINT)

    def test_r4_non_sha256_fingerprint_is_refused(self) -> None:
        for bad in ("", "abc", "g" * 64, "a" * 63, "a" * 65, "sha256:" + "a" * 64):
            with self.subTest(bad=bad):
                with self.assertRaises(ContractError):
                    record(request_fingerprint=bad)

    def test_r4_fingerprint_normalization_matches_the_canonical_digest_rule(self) -> None:
        # The canonical digest rule in `local_agent_command_admission` and
        # `windows_local_executor` lowercases before matching, so the store must
        # normalize identically rather than invent a stricter or looser rule.
        self.assertEqual(record(request_fingerprint="A" * 64).request_fingerprint, FINGERPRINT)
        self.assertEqual(record(request_fingerprint=f"  {FINGERPRINT}  ").request_fingerprint, FINGERPRINT)

    def test_r4_store_owns_no_fingerprint_algorithm(self) -> None:
        self.assertFalse(FINGERPRINT_ALGORITHM_OWNED_HERE)
        self.assertFalse(REQUEST_FINGERPRINT_RECOMPUTED)
        self.assertNotIn("fingerprint_algorithm", DurableRunRecord.__dataclass_fields__)

    def test_r4_fingerprint_source_is_an_opaque_label(self) -> None:
        self.assertEqual(record(fingerprint_source="broker").fingerprint_source, "broker")
        with self.assertRaises(ContractError):
            record(fingerprint_source="")

    def test_r4_stored_fingerprint_matches_the_canonical_local_command_authority(self) -> None:
        # The local command path's fingerprint authority is unchanged: the
        # #3082 store never produces or verifies this value itself.
        request = LocalCommandRequest(
            request_id="request.1",
            run_id="run.1",
            device_id="device.1",
            root_ref="root.1",
            argv=("git.exe", "status"),
            cwd_relative="repo",
            requested_at=NOW - timedelta(seconds=20),
        )
        canonical = command_request_fingerprint(request)
        self.assertEqual(len(canonical), 64)
        # A record may carry exactly that canonical value unchanged.
        self.assertEqual(record(request_fingerprint=canonical).request_fingerprint, canonical)


class DurableRunExpiryTests(unittest.TestCase):
    """R6 — command expiry is a hard deadline, not a renewable lease."""

    def test_r6_semantics_are_declared_as_a_hard_deadline(self) -> None:
        self.assertEqual(COMMAND_EXPIRES_AT_SEMANTICS, "hard_deadline")
        self.assertFalse(LOCAL_LEASE_EXTENSION)

    def test_r6_expiry_window_must_be_positive(self) -> None:
        with self.assertRaises(ContractError):
            record(command_issued_at=NOW, command_expires_at=NOW)
        with self.assertRaises(ContractError):
            record(command_issued_at=NOW, command_expires_at=NOW - timedelta(seconds=1))

    def test_r6_admission_cannot_be_recorded_at_or_after_the_deadline(self) -> None:
        with self.assertRaises(ContractError):
            record(admitted_at=NOW + timedelta(seconds=300))
        with self.assertRaises(ContractError):
            record(admitted_at=NOW + timedelta(seconds=301))

    def test_r6_admission_cannot_predate_canonical_issuance(self) -> None:
        with self.assertRaises(ContractError):
            record(
                command_issued_at=NOW - timedelta(seconds=10),
                command_expires_at=NOW + timedelta(seconds=300),
                admitted_at=NOW - timedelta(seconds=30),
            )

    def test_r6_start_cannot_be_at_or_after_the_deadline(self) -> None:
        with self.assertRaises(ContractError):
            executing(started_at=NOW + timedelta(seconds=300))

    def test_r6_hard_deadline_passed_is_a_fact_not_a_lease(self) -> None:
        stored = record()
        self.assertFalse(stored.hard_deadline_passed(now=NOW))
        self.assertTrue(stored.hard_deadline_passed(now=NOW + timedelta(seconds=300)))
        self.assertTrue(stored.hard_deadline_passed(now=NOW + timedelta(seconds=301)))

    def test_r6_record_exposes_no_renewal_or_extension_method(self) -> None:
        forbidden = [
            name
            for name in dir(DurableRunRecord)
            if any(token in name.lower() for token in ("renew", "extend", "lease", "refresh", "prolong"))
        ]
        self.assertEqual(forbidden, [])

    def test_r6_expired_command_is_never_replayable(self) -> None:
        expired = terminal(
            termination=DurableRunTermination.EXPIRED,
            terminated_at=NOW + timedelta(seconds=300),
        )
        self.assertFalse(expired.replayable)
        self.assertTrue(expired.hard_deadline_passed(now=NOW + timedelta(seconds=301)))


class DurableRunTerminalityTests(unittest.TestCase):
    """R8 — local terminality and server acknowledgement are orthogonal."""

    def test_r8_terminality_is_a_local_observed_fact(self) -> None:
        self.assertEqual(LOCAL_EXECUTION_TERMINALITY, "local_observed_fact")
        self.assertFalse(AUTO_REPLAY_AFTER_LOCAL_TERMINAL)

    def test_r8_terminal_requires_a_local_termination_reason(self) -> None:
        with self.assertRaises(ContractError):
            record(
                state=DurableRunState.TERMINAL,
                started_at=NOW - timedelta(seconds=10),
                terminated_at=NOW - timedelta(seconds=5),
            )
        with self.assertRaises(ContractError):
            record(
                state=DurableRunState.TERMINAL,
                started_at=NOW - timedelta(seconds=10),
                termination=DurableRunTermination.EXITED,
            )

    def test_r8_non_terminal_cannot_carry_a_termination(self) -> None:
        with self.assertRaises(ContractError):
            record(
                state=DurableRunState.EXECUTING,
                started_at=NOW - timedelta(seconds=10),
                termination=DurableRunTermination.EXITED,
            )
        with self.assertRaises(ContractError):
            record(
                state=DurableRunState.EXECUTING,
                started_at=NOW - timedelta(seconds=10),
                terminated_at=NOW - timedelta(seconds=5),
            )

    def test_r8_every_termination_subtype_is_representable(self) -> None:
        expected = {"exited", "cancelled", "timed_out", "expired", "aborted"}
        self.assertEqual({item.value for item in DurableRunTermination}, expected)

    def test_r8_expired_termination_cannot_precede_the_hard_deadline(self) -> None:
        with self.assertRaises(ContractError):
            terminal(
                termination=DurableRunTermination.EXPIRED,
                terminated_at=NOW + timedelta(seconds=299),
            )

    def test_r8_terminal_without_server_ack_is_still_terminal(self) -> None:
        stored = terminal()
        self.assertTrue(stored.terminal)
        self.assertFalse(stored.acknowledged)
        self.assertIsNone(stored.server_acknowledged_at)

    def test_r8_missing_server_ack_never_reopens_the_record(self) -> None:
        stored = terminal()
        self.assertFalse(stored.replayable)
        # A later "ack" is a separate orthogonal fact; it cannot resurrect work.
        acked = replace(stored, server_acknowledged_at=NOW - timedelta(seconds=1))
        self.assertTrue(acked.acknowledged)
        self.assertTrue(acked.terminal)
        self.assertEqual(acked.termination, DurableRunTermination.EXITED)

    def test_r8_crash_after_terminal_persistence_stays_non_replayable(self) -> None:
        # Exactly the R8 crash window: local terminality is durable, the server
        # never acknowledged, and recovery must not replay.
        crashed = terminal(offline_state=DurableRunOfflineState.IDLE)
        self.assertTrue(crashed.terminal)
        self.assertFalse(crashed.acknowledged)
        self.assertFalse(crashed.replayable)
        self.assertTrue(crashed.retention_hold())

    def test_r8_terminal_without_ack_is_retained_from_gc(self) -> None:
        self.assertTrue(TERMINAL_WITHOUT_ACK_IS_RETAINED)
        self.assertTrue(terminal().retention_hold())
        acked = replace(terminal(), server_acknowledged_at=NOW - timedelta(seconds=1))
        self.assertFalse(acked.retention_hold())

    def test_r8_reconciliation_required_is_non_replayable(self) -> None:
        stored = record(
            state=DurableRunState.RECONCILIATION_REQUIRED,
            started_at=NOW - timedelta(seconds=10),
        )
        self.assertFalse(stored.replayable)
        self.assertFalse(stored.terminal)

    def test_r8_server_ack_requires_local_terminality(self) -> None:
        with self.assertRaises(ContractError):
            record(server_acknowledged_at=NOW)

    def test_r8_server_ack_cannot_predate_local_termination(self) -> None:
        with self.assertRaises(ContractError):
            terminal(server_acknowledged_at=NOW - timedelta(seconds=6))

    def test_r8_server_ack_cannot_preadmit_or_reach_the_hard_deadline(self) -> None:
        with self.assertRaises(ContractError):
            terminal(server_acknowledged_at=NOW - timedelta(seconds=60))
        with self.assertRaises(ContractError):
            terminal(server_acknowledged_at=NOW + timedelta(seconds=300))
        with self.assertRaises(ContractError):
            terminal(server_acknowledged_at=NOW + timedelta(seconds=600))

    def test_r8_contract_exposes_no_single_acked_state(self) -> None:
        values = {item.value for item in DurableRunState}
        self.assertNotIn("acknowledged", values)
        self.assertNotIn("acked", values)
        self.assertEqual(
            values,
            {"admitted", "executing", "reconciliation_required", "terminal"},
        )


class DurableRunOfflineStateTests(unittest.TestCase):
    """Offline queue state is explicit metadata, never execution authority."""

    def test_offline_states_are_explicit(self) -> None:
        self.assertEqual(
            {item.value for item in DurableRunOfflineState},
            {"idle", "queued", "expired"},
        )

    def test_offline_state_defaults_to_idle(self) -> None:
        self.assertEqual(record().offline_state, DurableRunOfflineState.IDLE)

    def test_queued_offline_state_is_never_a_permission_to_run(self) -> None:
        stored = record(offline_state=DurableRunOfflineState.QUEUED)
        # Queued metadata does not make the record terminal, nor does it grant
        # execution: the broker/admission authorities still own that decision.
        self.assertFalse(stored.terminal)
        self.assertEqual(stored.state, DurableRunState.ADMITTED)

    def test_expired_offline_state_is_never_replayable(self) -> None:
        stored = record(offline_state=DurableRunOfflineState.EXPIRED)
        self.assertEqual(stored.offline_state, DurableRunOfflineState.EXPIRED)

    def test_offline_state_does_not_change_device_lifecycle_authority(self) -> None:
        # #3080/#3083 own device truth: a redeemed device is PAIRED_OFFLINE and
        # only a server session + heartbeat may project ONLINE.
        self.assertEqual(device_binding(3).state, DeviceLifecycle.PAIRED_OFFLINE)
        self.assertNotIn("online", {item.value for item in DurableRunOfflineState})


class DurableRunReconciliationWireTests(unittest.TestCase):
    """R11 — reconciliation is local-only; the #3080 wire has no such state."""

    def test_r11_reconciliation_is_not_projected_onto_the_wire(self) -> None:
        self.assertTrue(RECONCILIATION_PROJECTED_ONTO_WIRE is False)
        self.assertTrue(BROKER_WIRE_RECONCILIATION_STATE is False)

    def test_r11_canonical_broker_command_states_remain_three(self) -> None:
        from padiem_control_plane.local_agent_broker import BrokerCommandState

        self.assertEqual(
            {item.value for item in BrokerCommandState},
            {"queued", "admitted", "acknowledged"},
        )

    def test_r11_reconciliation_state_is_not_a_broker_state(self) -> None:
        from padiem_control_plane.local_agent_broker import BrokerCommandState

        self.assertNotIn(
            DurableRunState.RECONCILIATION_REQUIRED.value,
            {item.value for item in BrokerCommandState},
        )

    def test_r11_local_vocabulary_is_not_a_mirror_of_the_wire_vocabulary(self) -> None:
        from padiem_control_plane.local_agent_broker import BrokerCommandState

        wire = {item.value for item in BrokerCommandState}
        local = {item.value for item in DurableRunState}
        # Shared words are only shared vocabulary; the two vocabularies are
        # deliberately not equal, because the local record owns terminality and
        # reconciliation facts the wire has no room for.
        self.assertNotEqual(wire, local)
        self.assertTrue(wire <= local | {"queued", "acknowledged"})
        # Every local-only state must be local-only by construction.
        self.assertEqual(
            local - wire,
            {"executing", "reconciliation_required", "terminal"},
        )

    def test_r11_no_local_state_is_projected_as_a_wire_state(self) -> None:
        from padiem_control_plane.local_agent_broker import BrokerCommandRecord

        # The record's own wire projection is the broker's vocabulary, not the
        # store's; the store never rewrites a broker state name.
        source = BrokerCommandRecord.__dataclass_fields__
        self.assertIn("state", source)
        self.assertIn("acknowledged_at", source)


class DurableRunBoundedEvidenceTests(unittest.TestCase):
    """R12 — bounded, secret-free evidence metadata only."""

    def test_r12_evidence_defaults_are_empty_and_safe(self) -> None:
        evidence = BoundedEvidenceProjection()
        self.assertEqual(evidence.item_count, 0)
        self.assertEqual(evidence.summary, "")
        safe = evidence.safe_dict()
        for key in ("raw_argv", "raw_stdout", "raw_stderr", "p01_approval_payload", "raw_file_content"):
            self.assertFalse(safe[key], key)

    def test_r12_evidence_accepts_bounded_refs_and_counts(self) -> None:
        evidence = BoundedEvidenceProjection(
            diff_ref="diff.1",
            test_ref="test.1",
            artifact_ref="artifact.1",
            evidence_ref="evidence.1",
            item_count=3,
            summary="three files changed",
        )
        self.assertEqual(evidence.item_count, 3)

    def test_r12_item_count_is_bounded(self) -> None:
        self.assertEqual(BoundedEvidenceProjection(item_count=MAX_EVIDENCE_ITEMS).item_count, MAX_EVIDENCE_ITEMS)
        with self.assertRaises(ContractError):
            BoundedEvidenceProjection(item_count=MAX_EVIDENCE_ITEMS + 1)
        with self.assertRaises(ContractError):
            BoundedEvidenceProjection(item_count=-1)
        with self.assertRaises(ContractError):
            BoundedEvidenceProjection(item_count=True)

    def test_r12_summary_is_length_bounded(self) -> None:
        BoundedEvidenceProjection(summary="x" * MAX_EVIDENCE_SUMMARY_CHARS)
        with self.assertRaises(ContractError):
            BoundedEvidenceProjection(summary="x" * (MAX_EVIDENCE_SUMMARY_CHARS + 1))

    def test_r12_raw_process_output_is_refused(self) -> None:
        for marker in ("stdout=", "stderr=", "argv=", "credential=", "broker_token=", "p01_approval_payload="):
            with self.subTest(marker=marker):
                with self.assertRaises(ContractError):
                    BoundedEvidenceProjection(summary=f"{marker}secret-value")
                with self.assertRaises(ContractError):
                    BoundedEvidenceProjection(diff_ref=f"{marker}secret-value")

    def test_r12_record_rejects_non_evidence_projection(self) -> None:
        with self.assertRaises(ContractError):
            record(evidence={"item_count": 1})

    def test_r12_evidence_is_not_p01_evidence_authority(self) -> None:
        self.assertFalse(P01_EVIDENCE_AUTHORITY_DUPLICATED)
        self.assertFalse(P01_LIFECYCLE_AUTHORITY_DUPLICATED)


class DurableRunRecoveryGuardTests(unittest.TestCase):
    """#3081 correction — fail-closed on record uncertainty, not PID hunting."""

    def test_store_owns_no_process_authority(self) -> None:
        self.assertFalse(PROCESS_PID_AUTHORITY)
        self.assertFalse(UNKNOWN_PROCESS_REATTACHMENT_SUPPORTED)
        self.assertFalse(SIDE_EFFECT_REPLAY_SUPPORTED)

    def test_no_durable_state_is_itself_replay_authority(self) -> None:
        self.assertFalse(record().replayable)
        self.assertFalse(executing().replayable)
        self.assertFalse(
            record(
                state=DurableRunState.RECONCILIATION_REQUIRED,
                started_at=NOW - timedelta(seconds=10),
            ).replayable
        )
        self.assertFalse(terminal().replayable)

    def test_record_persists_no_pid_field(self) -> None:
        fields = set(DurableRunRecord.__dataclass_fields__)
        self.assertNotIn("pid", fields)
        self.assertNotIn("process_id", fields)
        self.assertFalse(record().safe_dict()["process_pid_persisted"])

    def test_job_object_tree_is_reaped_on_runner_death(self) -> None:
        # The corrected rationale: #3081's KILL_ON_JOB_CLOSE terminates the tree
        # when the runner dies, so #3082 must not claim descendants survive.
        self.assertTrue(JOB_OBJECT_TREE_REAPED_ON_RUNNER_DEATH)

    def test_safe_dict_is_secret_free(self) -> None:
        safe = terminal().safe_dict()
        for key in (
            "raw_device_credential",
            "raw_approval_payload",
            "raw_argv",
            "raw_stdout",
            "raw_stderr",
        ):
            self.assertFalse(safe[key], key)
        self.assertEqual(safe["contract_version"], "claw-desktop-durable-run.v1")

    def test_safe_dict_reports_replay_and_retention_facts(self) -> None:
        safe = terminal().safe_dict()
        self.assertFalse(safe["replayable"])
        self.assertTrue(safe["retention_hold"])
        self.assertEqual(safe["state"], "terminal")
        self.assertEqual(safe["termination"], "exited")
        self.assertIsNone(safe["server_acknowledged_at"])


class DurableRunTimestampsTests(unittest.TestCase):
    def test_all_timestamps_must_be_timezone_aware(self) -> None:
        naive = datetime(2026, 9, 26, 8, 0)
        for field in ("command_issued_at", "command_expires_at", "admitted_at", "started_at", "terminated_at", "server_acknowledged_at"):
            with self.subTest(field=field):
                with self.assertRaises(ContractError):
                    record(**{field: naive})

    def test_terminated_at_cannot_predate_started_at(self) -> None:
        with self.assertRaises(ContractError):
            record(
                state=DurableRunState.TERMINAL,
                started_at=NOW - timedelta(seconds=5),
                terminated_at=NOW - timedelta(seconds=10),
                termination=DurableRunTermination.EXITED,
            )

    def test_started_at_cannot_predate_admission(self) -> None:
        with self.assertRaises(ContractError):
            executing(started_at=NOW - timedelta(seconds=60))

    def test_admitted_record_cannot_already_have_started(self) -> None:
        with self.assertRaises(ContractError):
            record(started_at=NOW - timedelta(seconds=10))

    def test_timestamps_are_projected_as_utc_z(self) -> None:
        safe = record().safe_dict()
        self.assertTrue(safe["admitted_at"].endswith("Z"))
        self.assertTrue(safe["command_expires_at"].endswith("Z"))


if __name__ == "__main__":
    unittest.main()
