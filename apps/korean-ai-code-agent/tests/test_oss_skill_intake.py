"""#2823 OSS Skill intake, license, provenance, and pinning gate tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import unittest

from kagent.contracts import ContractError
from kagent.oss_skill_intake import (
    AuditStatus,
    BehaviorAudit,
    CredentialEnvironmentAudit,
    DependencyAudit,
    EvidenceRef,
    LegalUseStatus,
    OSSDecision,
    OSSIntakeGate,
    OSSIntakeRecord,
    OSSReviewMetadata,
    OSSSourceKind,
    PinningStrategy,
    StrategyRecord,
)


NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
COMMIT = "a" * 40
LICENSE_EVIDENCE = EvidenceRef("https://spdx.org/licenses/MIT.html", "license")
REVIEW_EVIDENCE = EvidenceRef("evidence:oss-review-2823", "review")


def behavior(*, declared: bool = False, hidden: bool = False) -> BehaviorAudit:
    return BehaviorAudit(AuditStatus.REVIEWED, declared, hidden, REVIEW_EVIDENCE)


def accepted_record(**overrides) -> OSSIntakeRecord:
    values = dict(
        candidate_id="candidate:synthetic-parser",
        source_kind=OSSSourceKind.REPOSITORY,
        repository_or_package="https://github.com/example/synthetic-parser",
        immutable_version_or_commit=COMMIT,
        license_id="MIT",
        license_source=LICENSE_EVIDENCE,
        commercial_use_status=LegalUseStatus.ALLOWED,
        redistribution_status=LegalUseStatus.ALLOWED,
        transitive_dependency_status=DependencyAudit(AuditStatus.REVIEWED, True, REVIEW_EVIDENCE),
        network_behavior=behavior(),
        filesystem_behavior=behavior(),
        shell_behavior=behavior(),
        subprocess_behavior=behavior(),
        credential_environment_reads=CredentialEnvironmentAudit(
            AuditStatus.REVIEWED,
            True,
            True,
            False,
            False,
            REVIEW_EVIDENCE,
        ),
        update_strategy=StrategyRecord("reviewed_updates", REVIEW_EVIDENCE),
        pinning_strategy=StrategyRecord(PinningStrategy.IMMUTABLE.value, REVIEW_EVIDENCE),
        known_format_limitations=("synthetic fixture only",),
        test_evidence=(EvidenceRef("evidence:unit-oss-intake", "test"),),
        adversarial_evidence=(EvidenceRef("evidence:mutation-oss-intake", "adversarial"),),
        decision=OSSDecision.ACCEPTED,
        decision_reason="synthetic fixture reviewed",
        review=OSSReviewMetadata(NOW, "reviewer:local3", REVIEW_EVIDENCE),
    )
    values.update(overrides)
    return OSSIntakeRecord(**values)


class OSSIntakeContractTests(unittest.TestCase):
    def test_valid_pinned_candidate_is_accepted_without_runtime_registration(self) -> None:
        receipt = OSSIntakeGate().evaluate(accepted_record())
        self.assertEqual(receipt.decision, OSSDecision.ACCEPTED)
        self.assertTrue(receipt.adoption_allowed)
        self.assertFalse(receipt.runtime_skill_registered)
        self.assertFalse(receipt.auto_runtime_registration)

    def test_floating_main_latest_and_missing_version_fail_closed(self) -> None:
        for value in ("main", "latest", ""):
            with self.subTest(value=value), self.assertRaises(ContractError):
                accepted_record(immutable_version_or_commit=value)

    def test_package_requires_exact_version_not_floating_reference(self) -> None:
        record = accepted_record(
            source_kind=OSSSourceKind.PACKAGE,
            repository_or_package="synthetic-parser",
            immutable_version_or_commit="1.2.3",
        )
        self.assertEqual(OSSIntakeGate().evaluate(record).decision, OSSDecision.ACCEPTED)
        for value in ("latest", "^1.2.3", "1.2"):
            with self.subTest(value=value), self.assertRaises(ContractError):
                accepted_record(
                    source_kind=OSSSourceKind.PACKAGE,
                    repository_or_package="synthetic-parser",
                    immutable_version_or_commit=value,
                )

    def test_unknown_or_missing_license_record_fails_closed(self) -> None:
        with self.assertRaises(ContractError):
            accepted_record(license_id="unknown")
        with self.assertRaises(ContractError):
            accepted_record(license_source=None)
        receipt = OSSIntakeGate().evaluate(
            accepted_record(
                commercial_use_status=LegalUseStatus.UNKNOWN,
                decision=OSSDecision.REJECTED,
                decision_reason="license review incomplete",
            )
        )
        self.assertEqual(receipt.decision, OSSDecision.REJECTED)

    def test_unreviewed_network_shell_and_subprocess_fail_closed(self) -> None:
        for field in ("network_behavior", "shell_behavior", "subprocess_behavior"):
            with self.subTest(field=field):
                record = accepted_record(**{field: BehaviorAudit(AuditStatus.UNKNOWN, False, False, REVIEW_EVIDENCE)})
                rejected = OSSIntakeGate().evaluate(
                    accepted_record(
                        **{field: BehaviorAudit(AuditStatus.UNKNOWN, False, False, REVIEW_EVIDENCE)},
                        decision=OSSDecision.REJECTED,
                        decision_reason="behavior review denied",
                    )
                )
                self.assertEqual(rejected.decision, OSSDecision.REJECTED)
                with self.assertRaises(ContractError):
                    OSSIntakeGate().evaluate(record)

    def test_hidden_network_and_shell_behavior_fail_closed(self) -> None:
        for field in ("network_behavior", "shell_behavior"):
            with self.subTest(field=field), self.assertRaises(ContractError):
                OSSIntakeGate().evaluate(
                    accepted_record(
                        **{field: BehaviorAudit(AuditStatus.REVIEWED, True, True, REVIEW_EVIDENCE)}
                    )
                )

    def test_undeclared_environment_and_credential_reads_fail_closed(self) -> None:
        audit = CredentialEnvironmentAudit(
            AuditStatus.REVIEWED,
            False,
            False,
            False,
            False,
            REVIEW_EVIDENCE,
        )
        with self.assertRaises(ContractError):
            OSSIntakeGate().evaluate(accepted_record(credential_environment_reads=audit))
        with self.assertRaises(ContractError):
            OSSIntakeGate().evaluate(
                accepted_record(
                    credential_environment_reads=CredentialEnvironmentAudit(
                        AuditStatus.REVIEWED,
                        True,
                        False,
                        False,
                        False,
                        REVIEW_EVIDENCE,
                    )
                )
            )
        with self.assertRaises(ContractError):
            OSSIntakeGate().evaluate(
                accepted_record(
                    credential_environment_reads=CredentialEnvironmentAudit(
                        AuditStatus.REVIEWED,
                        True,
                        True,
                        True,
                        False,
                        REVIEW_EVIDENCE,
                    )
                )
            )

    def test_transitive_dependency_audit_and_evidence_are_required(self) -> None:
        with self.assertRaises(ContractError):
            OSSIntakeGate().evaluate(
                accepted_record(
                    transitive_dependency_status=DependencyAudit(AuditStatus.UNKNOWN, False, REVIEW_EVIDENCE)
                )
            )
        with self.assertRaises(ContractError):
            accepted_record(test_evidence=())
        with self.assertRaises(ContractError):
            accepted_record(adversarial_evidence=())

    def test_rejected_candidate_cannot_be_adopted(self) -> None:
        receipt = OSSIntakeGate().evaluate(
            accepted_record(
                decision=OSSDecision.REJECTED,
                decision_reason="shell review incomplete",
                shell_behavior=BehaviorAudit(AuditStatus.UNKNOWN, False, False, REVIEW_EVIDENCE),
            )
        )
        self.assertFalse(receipt.adoption_allowed)
        with self.assertRaises(ContractError):
            receipt.assert_adoptable()

    def test_safe_projection_contains_bounded_metadata_only(self) -> None:
        receipt = OSSIntakeGate().evaluate(accepted_record())
        safe = receipt.safe_dict()
        rendered = json.dumps(safe, sort_keys=True)
        self.assertEqual(set(safe), {
            "contract_version", "candidate_id", "immutable_version", "license_id",
            "decision", "decision_code", "decision_reason", "network_reviewed",
            "filesystem_reviewed", "shell_reviewed", "subprocess_reviewed",
            "provenance_recorded", "adoption_allowed", "runtime_skill_registered",
            "auto_runtime_registration", "raw_source_record", "raw_evidence",
        })
        self.assertNotIn("github.com", rendered)
        self.assertNotIn("C:\\", rendered)
        self.assertNotIn("token=", rendered)
        self.assertFalse(safe["runtime_skill_registered"])
        self.assertFalse(safe["auto_runtime_registration"])

    def test_private_path_and_secret_provenance_are_rejected(self) -> None:
        with self.assertRaises(ContractError):
            accepted_record(repository_or_package=r"C:\private\candidate")
        with self.assertRaises(ContractError):
            accepted_record(decision_reason="token=secret")


if __name__ == "__main__":
    unittest.main()
