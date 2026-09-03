from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.sandbox_conformance import IsolationPrimitive
from kagent.sandbox_provider_review import (
    DETERMINISTIC_HARNESS_ONLY_SELECTION_SUPPORTED,
    DOCUMENTATION_ONLY_SELECTION_SUPPORTED,
    PRODUCTION_APPROVAL_FROM_PROVIDER_REVIEW_SUPPORTED,
    PROVIDER_SELECTION_FROM_RESEARCH_REVIEW_SUPPORTED,
    ProviderEvidenceBasis,
    ProviderEvidenceStatus,
    ReviewedProviderControlEvidence,
    SandboxProviderEvidenceReview,
)
from kagent.sandbox_provider_evidence import capability_control_names


NOW = datetime(2026, 9, 3, 0, 15, tzinfo=timezone.utc)


def rows(
    *,
    basis=ProviderEvidenceBasis.LIVE_PROVIDER_PROBE,
    status=ProviderEvidenceStatus.VERIFIED,
    override_control=None,
    override_basis=None,
    override_status=None,
    stale_control=None,
):
    result = []
    for name in capability_control_names():
        item_basis = override_basis if name == override_control and override_basis is not None else basis
        item_status = override_status if name == override_control and override_status is not None else status
        observed_at = NOW - timedelta(minutes=10)
        expires_at = NOW + timedelta(hours=1)
        if name == stale_control:
            observed_at = NOW - timedelta(hours=2)
            expires_at = NOW - timedelta(seconds=1)
        result.append(
            ReviewedProviderControlEvidence(
                control=name,
                status=item_status,
                basis=item_basis,
                evidence_ref=f"evidence:{name}",
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    return tuple(result)


def review(**kwargs):
    values = dict(
        provider_candidate_ref="candidate_fixture",
        isolation_primitive=IsolationPrimitive.MICROVM,
        controls=rows(),
        review_ref="review:fixture",
    )
    values.update(kwargs)
    return SandboxProviderEvidenceReview(**values)


class SandboxProviderEvidenceReviewTests(unittest.TestCase):
    def test_complete_acceptance_grade_review_promotes_into_existing_v1_gate(self):
        reviewed = review()
        self.assertTrue(reviewed.eligible_for_acceptance(NOW))
        pack = reviewed.promote_to_v1(NOW)
        assessment = pack.assess()
        self.assertTrue(assessment.accepted_for_cloud_m1)
        self.assertEqual(assessment.missing_controls, ())

    def test_official_documentation_alone_cannot_promote_to_acceptance(self):
        reviewed = review(controls=rows(basis=ProviderEvidenceBasis.OFFICIAL_DOCUMENTATION))
        self.assertFalse(reviewed.eligible_for_acceptance(NOW))
        blockers = reviewed.acceptance_blockers(NOW)
        self.assertTrue(all(item.endswith(":insufficient_evidence_basis") for item in blockers))
        with self.assertRaises(ContractError):
            reviewed.promote_to_v1(NOW)

    def test_deterministic_harness_alone_cannot_promote_to_acceptance(self):
        reviewed = review(controls=rows(basis=ProviderEvidenceBasis.DETERMINISTIC_HARNESS))
        self.assertFalse(reviewed.eligible_for_acceptance(NOW))
        with self.assertRaises(ContractError):
            reviewed.promote_to_v1(NOW)

    def test_unproven_not_supported_and_stale_controls_fail_closed(self):
        names = capability_control_names()
        unproven = review(
            controls=rows(
                override_control=names[0],
                override_status=ProviderEvidenceStatus.UNPROVEN,
            )
        )
        self.assertIn(f"{names[0]}:unproven", unproven.acceptance_blockers(NOW))

        unsupported = review(
            controls=rows(
                override_control=names[1],
                override_status=ProviderEvidenceStatus.NOT_SUPPORTED,
            )
        )
        self.assertIn(f"{names[1]}:not_supported", unsupported.acceptance_blockers(NOW))

        stale = review(controls=rows(stale_control=names[2]))
        self.assertIn(f"{names[2]}:stale_or_future", stale.acceptance_blockers(NOW))

    def test_one_docs_only_row_blocks_otherwise_live_review(self):
        name = capability_control_names()[0]
        reviewed = review(
            controls=rows(
                override_control=name,
                override_basis=ProviderEvidenceBasis.OFFICIAL_DOCUMENTATION,
            )
        )
        self.assertEqual(
            reviewed.acceptance_blockers(NOW),
            (f"{name}:insufficient_evidence_basis",),
        )

    def test_research_gaps_do_not_mislabel_current_verified_docs_as_missing_capability(self):
        reviewed = review(controls=rows(basis=ProviderEvidenceBasis.OFFICIAL_DOCUMENTATION))
        self.assertEqual(reviewed.research_gaps(NOW), ())
        self.assertTrue(reviewed.acceptance_blockers(NOW))

    def test_unknown_isolation_remains_acceptance_blocker(self):
        reviewed = review(isolation_primitive=IsolationPrimitive.UNKNOWN)
        self.assertIn("known_isolation_primitive:unproven", reviewed.acceptance_blockers(NOW))
        with self.assertRaises(ContractError):
            reviewed.promote_to_v1(NOW)

    def test_missing_duplicate_unknown_and_bad_time_fail_closed(self):
        full = rows()
        with self.assertRaises(ContractError):
            review(controls=full[:-1])
        with self.assertRaises(ContractError):
            review(controls=full + (full[0],))
        with self.assertRaises(ContractError):
            ReviewedProviderControlEvidence(
                control="invented_control",
                status=ProviderEvidenceStatus.VERIFIED,
                basis=ProviderEvidenceBasis.LIVE_PROVIDER_PROBE,
                evidence_ref="evidence:bad",
                observed_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )
        with self.assertRaises(ContractError):
            ReviewedProviderControlEvidence(
                control=capability_control_names()[0],
                status=ProviderEvidenceStatus.VERIFIED,
                basis=ProviderEvidenceBasis.LIVE_PROVIDER_PROBE,
                evidence_ref="evidence:bad_time",
                observed_at=NOW,
                expires_at=NOW,
            )

    def test_secret_like_ref_is_rejected(self):
        with self.assertRaises(ContractError):
            ReviewedProviderControlEvidence(
                control=capability_control_names()[0],
                status=ProviderEvidenceStatus.VERIFIED,
                basis=ProviderEvidenceBasis.OFFICIAL_DOCUMENTATION,
                evidence_ref="token=should-not-be-here",
                observed_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )

    def test_safe_projection_never_claims_selection_certification_or_deployment_authority(self):
        rendered = review().safe_dict(NOW)
        self.assertTrue(rendered["acceptance_grade"])
        self.assertFalse(rendered["provider_selected"])
        self.assertFalse(rendered["security_certification"])
        self.assertFalse(rendered["deployment_approval"])
        self.assertFalse(rendered["production_ready_claim"])
        self.assertFalse(rendered["raw_provider_payload"])
        self.assertFalse(rendered["credential_fields"])
        self.assertFalse(rendered["provider_endpoint_fields"])
        self.assertFalse(DOCUMENTATION_ONLY_SELECTION_SUPPORTED)
        self.assertFalse(DETERMINISTIC_HARNESS_ONLY_SELECTION_SUPPORTED)
        self.assertFalse(PROVIDER_SELECTION_FROM_RESEARCH_REVIEW_SUPPORTED)
        self.assertFalse(PRODUCTION_APPROVAL_FROM_PROVIDER_REVIEW_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
