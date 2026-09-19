from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import unittest

from kagent.cloud_execution_plan import CloudM1ExecutionPlan, CloudM1Stage
from kagent.cloud_teardown import (
    FALSE_CLEAN_TEARDOWN_SUPPORTED,
    REAL_TEARDOWN_PROBE_CONFIGURED,
    CloudM1TeardownReceipt,
    TrustedTeardownObservation,
    verify_teardown_evidence,
)
from kagent.cloud_stage_receipts import CloudStageOutcome
from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    ResourceClass,
    SandboxLease,
    SandboxLeaseState,
)
from kagent.sandbox import SandboxLeaseError
from kagent.sandbox_artifact_collection import ArtifactCandidateCollection


NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
REV = "abcdef1234567890abcdef1234567890abcdef12"


def plan():
    return CloudM1ExecutionPlan(
        plan_id="plan_1",
        run_id="run_1",
        workspace_id="ws_1",
        repository_ref="skerishKang/example",
        input_revision=REV,
        verification_command_ids=("verify_unit",),
        artifact_policy_ref="artifact-policy:m1",
    )


def observation(**kwargs):
    values = dict(
        observation_id="obs_1",
        plan_id="plan_1",
        run_id="run_1",
        sandbox_lease_ref="sandbox:1",
        computer_ref="computer:1",
        observed_at=NOW,
        process_tree_killed=True,
        active_child_process_count=0,
        workspace_destroyed=True,
        sandbox_terminal=True,
        computer_terminal=True,
        preview_shares_terminal=True,
        human_control_terminal=True,
        artifacts_finalized=True,
        authority_ref="provider-attestation:1",
    )
    values.update(kwargs)
    return TrustedTeardownObservation(**values)

def lease(state=SandboxLeaseState.RELEASED, *, run_id="run_1", lease_id="sandbox:1"):
    return SandboxLease(
        lease_id=lease_id,
        run_id=run_id,
        execution_mode=ExecutionMode.CLOUD,
        resource_class=ResourceClass.STANDARD,
        network_policy=NetworkPolicy.OFF,
        writable_workspace=True,
        created_at=NOW,
        expires_at=NOW + timedelta(seconds=900),
        state=state,
    )


def fixed_lease(candidate=None):
    """Stand in for the trusted lease lookup the receipt depends on."""
    target = candidate if candidate is not None else lease()
    return lambda ref: target if ref == target.lease_id else None


def raising_lease_lookup(_ref):
    raise SandboxLeaseError("unknown lease")


def collection(**kwargs):
    values = dict(collection_id="col_1", run_id="run_1", lease_id="sandbox:1")
    values.update(kwargs)
    return ArtifactCandidateCollection(**values)



class CloudTeardownTests(unittest.TestCase):
    def test_all_required_controls_produce_clean_success_stage_receipt(self):
        p = plan()
        obs = observation()
        self.assertTrue(obs.clean)
        receipt = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_1", plan=p, observation=obs,
            lease_lookup=fixed_lease(), artifact_collection=collection(),
        )
        self.assertTrue(receipt.clean)
        stage = receipt.as_stage_receipt(event_id="event_teardown_1")
        self.assertEqual(stage.stage, CloudM1Stage.TEARDOWN)
        self.assertEqual(stage.outcome, CloudStageOutcome.SUCCEEDED)
        self.assertEqual(stage.plan_fingerprint, p.fingerprint)

    def test_each_incomplete_control_prevents_clean_teardown(self):
        cases = (
            {"process_tree_killed": False},
            {"active_child_process_count": 1},
            {"workspace_destroyed": False},
            {"sandbox_terminal": False},
            {"computer_terminal": False},
            {"preview_shares_terminal": False},
            {"human_control_terminal": False},
            {"artifacts_finalized": False},
        )
        p = plan()
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                obs = observation(observation_id=f"obs_{index}", **changes)
                self.assertFalse(obs.clean)
                receipt = CloudM1TeardownReceipt.from_observation(
                receipt_id=f"receipt_{index}", plan=p, observation=obs,
                lease_lookup=fixed_lease(), artifact_collection=collection(),
            )
                self.assertFalse(receipt.clean)
                self.assertEqual(receipt.as_stage_receipt(event_id=f"event_{index}").outcome, CloudStageOutcome.FAILED)

    def test_observation_identity_must_match_plan(self):
        p = plan()
        with self.assertRaises(ContractError):
            CloudM1TeardownReceipt.from_observation(
                receipt_id="r1", plan=p, observation=observation(plan_id="other_plan"),
                lease_lookup=fixed_lease(), artifact_collection=collection(),
            )
        with self.assertRaises(ContractError):
            CloudM1TeardownReceipt.from_observation(
                receipt_id="r2", plan=p, observation=observation(run_id="other_run"),
                lease_lookup=fixed_lease(), artifact_collection=collection(),
            )

    def test_child_process_count_is_bounded_and_boolean_rejected(self):
        for value in (-1, True, 1_000_001):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    observation(active_child_process_count=value)

    def test_no_computer_requires_terminal_truth_not_unknown_state(self):
        with self.assertRaises(ContractError):
            observation(computer_ref=None, computer_terminal=False)
        obs = observation(computer_ref=None, computer_terminal=True)
        self.assertTrue(obs.clean)

    def test_safe_receipt_contains_hash_and_no_raw_provider_or_credential_payload(self):
        receipt = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_1", plan=plan(), observation=observation(),
            lease_lookup=fixed_lease(), artifact_collection=collection(),
        )
        rendered = receipt.safe_dict()
        self.assertEqual(len(rendered["evidence_sha256"]), 64)
        self.assertFalse(rendered["raw_runtime_payload"])
        self.assertFalse(rendered["provider_endpoint"])
        self.assertFalse(rendered["credential_value"])
        self.assertFalse(rendered["false_clean_teardown_supported"])
        self.assertFalse(REAL_TEARDOWN_PROBE_CONFIGURED)
        self.assertFalse(FALSE_CLEAN_TEARDOWN_SUPPORTED)


class TeardownEvidenceVerificationTests(unittest.TestCase):
    """#2783: lease terminality and artifact finalization must be verified."""

    def receipt(self, *, obs=None, lease_state=None, lease_obj=None, coll=None):
        resolved_lease = lease_obj if lease_obj is not None else lease(state=lease_state or SandboxLeaseState.RELEASED)
        return CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_verify_1",
            plan=plan(),
            observation=obs if obs is not None else observation(),
            lease_lookup=fixed_lease(resolved_lease),
            artifact_collection=coll if coll is not None else collection(),
        )

    # 1
    def test_reserved_lease_blocks_a_clean_teardown(self):
        r = self.receipt(lease_state=SandboxLeaseState.RESERVED)
        self.assertFalse(r.clean)
        self.assertIn("LEASE_NOT_TERMINAL", r.verification_blockers)
        self.assertEqual(r.as_stage_receipt(event_id="e1").outcome, CloudStageOutcome.FAILED)

    # 2
    def test_terminal_lease_of_another_run_blocks_a_clean_teardown(self):
        r = self.receipt(lease_obj=lease(run_id="someone_elses_run"))
        self.assertFalse(r.clean)
        self.assertIn("LEASE_RUN_MISMATCH", r.verification_blockers)

    # 3
    def test_unresolvable_lease_blocks_a_clean_teardown(self):
        r = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_unknown", plan=plan(), observation=observation(),
            lease_lookup=lambda ref: None, artifact_collection=collection(),
        )
        self.assertFalse(r.clean)
        self.assertIn("LEASE_UNRESOLVED", r.verification_blockers)
        self.assertEqual(r.lease_state_verified, "UNRESOLVED")

    def test_lookup_raising_unknown_lease_fails_closed(self):
        r = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_raises", plan=plan(), observation=observation(),
            lease_lookup=raising_lease_lookup, artifact_collection=collection(),
        )
        self.assertFalse(r.clean)
        self.assertIn("LEASE_UNRESOLVED", r.verification_blockers)

    # 4
    def test_expired_lease_and_matching_collection_satisfy_both_components(self):
        for state in (SandboxLeaseState.RELEASED, SandboxLeaseState.EXPIRED):
            with self.subTest(state=state.value):
                r = self.receipt(lease_state=state)
                self.assertTrue(r.clean)
                self.assertEqual(r.verification_blockers, ())
                self.assertEqual(r.lease_state_verified, state.value.upper())
                self.assertEqual(r.artifact_collection_id, "col_1")

    # 5, 6
    def test_artifact_collection_must_correlate_to_run_and_lease(self):
        wrong_run = self.receipt(coll=collection(run_id="other_run"))
        self.assertFalse(wrong_run.clean)
        self.assertIn("ARTIFACT_COLLECTION_RUN_MISMATCH", wrong_run.verification_blockers)
        wrong_lease = self.receipt(coll=collection(lease_id="sandbox:other"))
        self.assertFalse(wrong_lease.clean)
        self.assertIn("ARTIFACT_COLLECTION_LEASE_MISMATCH", wrong_lease.verification_blockers)

    # 7
    def test_missing_collection_blocks_and_empty_collection_is_explicit(self):
        absent = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_no_collection", plan=plan(), observation=observation(),
            lease_lookup=fixed_lease(), artifact_collection=None,
        )
        self.assertFalse(absent.clean)
        self.assertIn("ARTIFACT_COLLECTION_ABSENT", absent.verification_blockers)
        # A bounded, empty collection is explicit evidence of "nothing to
        # publish"; it is not the free boolean this child removes.
        empty = self.receipt(coll=collection(changed_files=()))
        self.assertTrue(empty.clean)
        self.assertEqual(empty.artifact_collection_id, "col_1")

    def test_free_boolean_can_no_longer_claim_clean_alone(self):
        # artifacts_finalized stays on the observation as an attested fact, but
        # with the collection withheld the attestation is not sufficient.
        r = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_attest_only", plan=plan(),
            observation=observation(artifacts_finalized=True),
            lease_lookup=fixed_lease(), artifact_collection=None,
        )
        self.assertFalse(r.clean)

    # 8
    def test_existing_attested_controls_still_block_clean(self):
        for kwargs in (
            {"process_tree_killed": False},
            {"active_child_process_count": 3},
            {"workspace_destroyed": False},
            {"sandbox_terminal": False},
            {"preview_shares_terminal": False},
            {"human_control_terminal": False},
        ):
            with self.subTest(**kwargs):
                r = self.receipt(obs=observation(**kwargs))
                self.assertFalse(r.clean)
                self.assertEqual(r.verification_blockers, ())

    def test_verifier_rejects_structural_nonsense(self):
        with self.assertRaises(ContractError):
            verify_teardown_evidence(observation=observation(), lease_lookup="not-callable", artifact_collection=None)
        with self.assertRaises(ContractError):
            verify_teardown_evidence(
                observation=observation(), lease_lookup=fixed_lease(), artifact_collection={"not": "a collection"},
            )

    def test_no_network_or_provider_surface_is_reachable(self):
        import inspect

        from kagent import cloud_teardown

        source = inspect.getsource(cloud_teardown)
        for forbidden in ("urllib", "requests", "subprocess", "httpx", "curl", "socket"):
            self.assertNotIn(forbidden, source)

    # 10 (mutation targets; see also the two dedicated guards below)
    def test_evidence_fields_are_part_of_the_receipt_record(self):
        r = self.receipt()
        payload = r.safe_dict()
        self.assertEqual(payload["lease_state_verified"], "RELEASED")
        self.assertEqual(payload["artifact_collection_id"], "col_1")
        self.assertEqual(payload["verification_blockers"], [])
        blocked = self.receipt(lease_state=SandboxLeaseState.RESERVED).safe_dict()
        self.assertEqual(blocked["lease_state_verified"], "RESERVED")
        self.assertIn("LEASE_NOT_TERMINAL", blocked["verification_blockers"])
        # the digest must cover the verification, or it fingerprints only the claim
        self.assertNotEqual(r.evidence_sha256, blocked["evidence_sha256"])


class VerifiedFactoryOnlyTests(unittest.TestCase):
    """#2785 review: the public constructor must not be able to mint clean=True."""

    def direct(self, **overrides):
        values = dict(
            receipt_id="teardown_direct",
            plan_id="plan_1",
            plan_fingerprint="a" * 64,
            run_id="run_1",
            observation_id="obs_1",
            observed_at=NOW,
            clean=True,
            evidence_sha256="b" * 64,
            lease_state_verified="RELEASED",
            artifact_collection_id="col_1",
            verification_blockers=(),
        )
        values.update(overrides)
        return CloudM1TeardownReceipt(**values)

    def test_direct_construction_cannot_synthesize_a_clean_verdict(self):
        # Every field is shaped exactly like a verified terminal teardown. That is
        # no longer sufficient: nothing resolved the lease or the collection.
        with self.assertRaises(ContractError) as caught:
            self.direct()
        self.assertIn("verified factory", str(caught.exception))

    def test_diagnostic_non_clean_receipt_is_still_constructible(self):
        # Closing the clean bypass must not remove the ability to record a stuck
        # teardown for diagnosis.
        blocked = self.direct(
            clean=False,
            lease_state_verified="RESERVED",
            verification_blockers=("LEASE_NOT_TERMINAL",),
        )
        self.assertFalse(blocked.clean)
        self.assertIn("LEASE_NOT_TERMINAL", blocked.safe_dict()["verification_blockers"])

    def test_factory_path_still_issues_clean_for_both_terminal_states(self):
        for state in (SandboxLeaseState.RELEASED, SandboxLeaseState.EXPIRED):
            with self.subTest(state=state.value):
                r = CloudM1TeardownReceipt.from_observation(
                    receipt_id="teardown_ok", plan=plan(), observation=observation(),
                    lease_lookup=fixed_lease(lease(state=state)), artifact_collection=collection(),
                )
                self.assertTrue(r.clean)

    def test_unsafe_artifact_collection_id_is_rejected_by_the_receipt(self):
        for unsafe in ("", "  ", "col 1", "col;rm -rf /", "col" + "x" * 600, "token:gho_secret"):
            with self.subTest(collection_id=unsafe[:20]):
                with self.assertRaises(ContractError):
                    self.direct(artifact_collection_id=unsafe, clean=False)

    def test_unsafe_directly_built_collection_cannot_reach_the_projection(self):
        # ArtifactCandidateCollection does not police its own collection_id, so the
        # teardown boundary must refuse it rather than project it downstream.
        smuggled = collection(collection_id="col 1")
        with self.assertRaises(ContractError):
            CloudM1TeardownReceipt.from_observation(
                receipt_id="teardown_smuggle", plan=plan(), observation=observation(),
                lease_lookup=fixed_lease(), artifact_collection=smuggled,
            )

    def test_verification_ticket_is_not_projected(self):
        r = CloudM1TeardownReceipt.from_observation(
            receipt_id="teardown_proj", plan=plan(), observation=observation(),
            lease_lookup=fixed_lease(), artifact_collection=collection(),
        )
        # The ticket guards construction; it is not operator-facing evidence and
        # must not leak into the projection that becomes run history.
        projected = r.safe_dict()
        self.assertNotIn("verification_ticket", projected)
        json.dumps(projected)  # a non-JSON sentinel stored in the projection fails here
        # and not through repr either, so it cannot reach logs or diffs
        self.assertNotIn("verification_ticket", repr(r))


class FactoryOnlyTicketTests(unittest.TestCase):
    """#2785 round 2: nothing reachable from the public surface may mint clean."""

    def direct(self, ticket):
        return CloudM1TeardownReceipt(
            receipt_id="teardown_ticket_probe",
            plan_id="plan_1",
            plan_fingerprint="a" * 64,
            run_id="run_1",
            observation_id="obs_1",
            observed_at=NOW,
            clean=True,
            evidence_sha256="b" * 64,
            lease_state_verified="RELEASED",
            artifact_collection_id="col_1",
            verification_blockers=(),
            verification_ticket=ticket,
        )

    def test_public_surface_exposes_no_reusable_token(self):
        from kagent import cloud_teardown as module

        public_values = [
            getattr(module, name) for name in dir(module) if not name.startswith("_")
        ]
        # Every value a caller can reach without touching a private name must fail,
        # including any string, hash, class, function or sentinel-looking object.
        minted = []
        for value in public_values:
            try:
                receipt = self.direct(value)
            except ContractError:
                continue
            minted.append((value, receipt.clean))
        self.assertEqual(minted, [], "a public value was accepted as a verification ticket")

    def test_ordinary_values_cannot_mint_clean(self):
        import hashlib

        guesses = [
            None, "", "x" * 64, object(), CloudM1TeardownReceipt,
            hashlib.sha256(b"claw-m1-teardown-verified-factory/v1").hexdigest(),
            hashlib.sha256(b"").hexdigest(),
            frozenset(), (lambda: None),
        ]
        for value in guesses:
            with self.subTest(ticket=type(value).__name__):
                with self.assertRaises(ContractError):
                    self.direct(value)


if __name__ == "__main__":
    unittest.main()
