"""#2925 initial OSS candidate intake matrix fixture tests."""

from __future__ import annotations

from datetime import datetime, timezone
import unittest

from kagent.contracts import ContractError
from kagent.oss_skill_intake import (
    AUTO_RUNTIME_REGISTRATION,
    AuditStatus,
    BehaviorAudit,
    CredentialEnvironmentAudit,
    DependencyAudit,
    EvidenceRef,
    LegalUseStatus,
    OSSDecision,
    OSS_GATE_IS_SKILL_REGISTRY,
    OSSIntakeGate,
    OSSIntakeRecord,
    OSSReviewMetadata,
    OSSSourceKind,
    PRODUCTION_MUTATION,
    PROVIDER_CALLS,
    PinningStrategy,
    StrategyRecord,
)

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
REVIEW = EvidenceRef("evidence:oss-matrix-2925", "review")
PYPI = "https://pypi.org/pypi/{name}/json"
PROJECT = "https://pypi.org/project/{name}/{version}/"


def ev(ref: str, kind: str) -> EvidenceRef:
    return EvidenceRef(ref, kind)


def behavior(ref: str, *, declared: bool = False) -> BehaviorAudit:
    return BehaviorAudit(AuditStatus.REVIEWED, declared, False, ev(ref, "behavior"))


def unknown_behavior(ref: str) -> BehaviorAudit:
    return BehaviorAudit(AuditStatus.UNKNOWN, False, False, ev(ref, "behavior"))


def make_record(
    *,
    candidate_id: str,
    source_kind: OSSSourceKind,
    repository_or_package: str,
    immutable_version_or_commit: str,
    license_id: str,
    license_ref: str,
    commercial: LegalUseStatus,
    redistribution: LegalUseStatus,
    dependency_ref: str,
    network_ref: str,
    filesystem_ref: str,
    shell_ref: str,
    subprocess_ref: str,
    credential_ref: str,
    pin_ref: str,
    limitations: tuple[str, ...],
    test_ref: str,
    adversarial_ref: str,
    decision: OSSDecision,
    decision_reason: str,
    audits_reviewed: bool = True,
) -> OSSIntakeRecord:
    if audits_reviewed:
        audits = dict(
            transitive_dependency_status=DependencyAudit(
                AuditStatus.REVIEWED, True, ev(dependency_ref, "dependency")
            ),
            network_behavior=behavior(network_ref),
            filesystem_behavior=behavior(filesystem_ref, declared=True),
            shell_behavior=behavior(shell_ref),
            subprocess_behavior=behavior(subprocess_ref, declared=True),
            credential_environment_reads=CredentialEnvironmentAudit(
                AuditStatus.REVIEWED, True, True, False, False, ev(credential_ref, "credential")
            ),
        )
    else:
        audits = dict(
            transitive_dependency_status=DependencyAudit(
                AuditStatus.REVIEWED, True, ev(dependency_ref, "dependency")
            ),
            network_behavior=unknown_behavior(network_ref),
            filesystem_behavior=unknown_behavior(filesystem_ref),
            shell_behavior=unknown_behavior(shell_ref),
            subprocess_behavior=unknown_behavior(subprocess_ref),
            credential_environment_reads=CredentialEnvironmentAudit(
                AuditStatus.UNKNOWN, False, False, False, False, ev(credential_ref, "credential")
            ),
        )
    return OSSIntakeRecord(
        candidate_id=candidate_id,
        source_kind=source_kind,
        repository_or_package=repository_or_package,
        immutable_version_or_commit=immutable_version_or_commit,
        license_id=license_id,
        license_source=ev(license_ref, "license"),
        commercial_use_status=commercial,
        redistribution_status=redistribution,
        update_strategy=StrategyRecord("reviewed_updates", REVIEW),
        pinning_strategy=StrategyRecord(PinningStrategy.IMMUTABLE.value, ev(pin_ref, "pin")),
        known_format_limitations=limitations,
        test_evidence=(ev(test_ref, "test"),),
        adversarial_evidence=(ev(adversarial_ref, "adversarial"),),
        decision=decision,
        decision_reason=decision_reason,
        review=OSSReviewMetadata(NOW, "reviewer:local3", REVIEW),
        **audits,
    )


def pyhwpx_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pyhwpx",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/pyhwpx/",
        immutable_version_or_commit="1.7.2",
        license_id="MIT",
        license_ref="https://github.com/martiniifun/pyhwpx",
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pyhwpx"),
        network_ref="https://martiniifun.github.io/pyhwpx/",
        filesystem_ref="https://martiniifun.github.io/pyhwpx/",
        shell_ref="https://martiniifun.github.io/pyhwpx/",
        subprocess_ref="https://martiniifun.github.io/pyhwpx/",
        credential_ref=PYPI.format(name="pyhwpx"),
        pin_ref=PROJECT.format(name="pyhwpx", version="1.7.2"),
        limitations=(
            "requires installed Hancom HWP desktop application",
            "Windows-only pywin32 automation",
            "no upstream tests directory found at review time",
        ),
        test_ref="review:2925-pyhwpx-no-upstream-tests-directory",
        adversarial_ref="https://github.com/martiniifun/pyhwpx/issues",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "Hancom desktop automation conflicts with the default cloud path; "
            "deferred to the separate worker authority of #2826"
        ),
    )


def pyhwp_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pyhwp",
        source_kind=OSSSourceKind.REPOSITORY,
        repository_or_package="https://github.com/mete0r/pyhwp",
        immutable_version_or_commit="83239f0d3bdf438b2c9f7dcff455a6e841154a39",
        license_id="AGPL-3.0-or-later",
        license_ref=PYPI.format(name="pyhwp"),
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pyhwp"),
        network_ref="https://github.com/mete0r/pyhwp",
        filesystem_ref="https://github.com/mete0r/pyhwp",
        shell_ref="https://github.com/mete0r/pyhwp",
        subprocess_ref="https://github.com/mete0r/pyhwp",
        credential_ref=PYPI.format(name="pyhwp"),
        pin_ref="https://github.com/mete0r/pyhwp/commit/83239f0d3bdf438b2c9f7dcff455a6e841154a39",
        limitations=(
            "pre-1.0 beta version series",
            "AGPL-3.0-or-later copyleft obligations not yet elected",
            "PyPI version 0.1b15 is not an exact semantic version so a repository commit pin is used",
        ),
        test_ref="https://github.com/mete0r/pyhwp/tree/master/tests",
        adversarial_ref="https://github.com/mete0r/pyhwp/issues",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "AGPL copyleft election and pre-1.0 maturity deferred pending an explicit "
            "policy decision"
        ),
    )


def hwp5_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:hwp5",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/hwp5/",
        immutable_version_or_commit="0.1.0",
        license_id="MIT",
        license_ref="https://pypi.org/project/hwp5/",
        commercial=LegalUseStatus.UNKNOWN,
        redistribution=LegalUseStatus.UNKNOWN,
        dependency_ref=PYPI.format(name="hwp5"),
        network_ref="https://pypi.org/project/hwp5/",
        filesystem_ref="https://pypi.org/project/hwp5/",
        shell_ref="https://pypi.org/project/hwp5/",
        subprocess_ref="https://pypi.org/project/hwp5/",
        credential_ref=PYPI.format(name="hwp5"),
        pin_ref=PROJECT.format(name="hwp5", version="0.1.0"),
        limitations=(
            "project URLs reference github.com/your-username placeholder repositories",
            "license claim is not verifiable against a real source repository",
        ),
        test_ref="review:2925-hwp5-no-verifiable-upstream-tests",
        adversarial_ref="https://pypi.org/project/hwp5/",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "provenance not established: placeholder repository URLs leave commercial "
            "and redistribution status unknown"
        ),
        audits_reviewed=False,
    )


def hwpx_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:hwpx",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/hwpx/",
        immutable_version_or_commit="1.1.1",
        license_id="MIT",
        license_ref="https://pypi.org/project/hwpx/",
        commercial=LegalUseStatus.UNKNOWN,
        redistribution=LegalUseStatus.UNKNOWN,
        dependency_ref=PYPI.format(name="hwpx"),
        network_ref="https://pypi.org/project/hwpx/",
        filesystem_ref="https://pypi.org/project/hwpx/",
        shell_ref="https://pypi.org/project/hwpx/",
        subprocess_ref="https://pypi.org/project/hwpx/",
        credential_ref=PYPI.format(name="hwpx"),
        pin_ref=PROJECT.format(name="hwpx", version="1.1.1"),
        limitations=(
            "project URLs reference the PyPA sampleproject template",
            "no trustworthy native HWPX OSS candidate was found in this review pass",
        ),
        test_ref="review:2925-hwpx-no-verifiable-upstream-tests",
        adversarial_ref="https://pypi.org/project/hwpx/",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "provenance not established: sampleproject placeholder URLs leave commercial "
            "and redistribution status unknown"
        ),
        audits_reviewed=False,
    )


def pypdf_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pypdf",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/pypdf/",
        immutable_version_or_commit="6.19.0",
        license_id="BSD-3-Clause",
        license_ref="https://github.com/py-pdf/pypdf/blob/main/LICENSE",
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pypdf"),
        network_ref="https://github.com/py-pdf/pypdf",
        filesystem_ref="https://github.com/py-pdf/pypdf",
        shell_ref="https://github.com/py-pdf/pypdf",
        subprocess_ref="https://github.com/py-pdf/pypdf",
        credential_ref=PYPI.format(name="pypdf"),
        pin_ref=PROJECT.format(name="pypdf", version="6.19.0"),
        limitations=(
            "optional crypto extras are not adopted",
            "embedded JavaScript and external URI behavior re-verified at Skill work (#2827)",
        ),
        test_ref="https://github.com/py-pdf/pypdf/tree/main/tests",
        adversarial_ref="https://github.com/py-pdf/pypdf/issues",
        decision=OSSDecision.ACCEPTED,
        decision_reason=(
            "BSD-3-Clause package pinned at 6.19.0; static intake review found no network, "
            "shell, subprocess, or credential reads"
        ),
    )


def pymupdf_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pymupdf",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/pymupdf/",
        immutable_version_or_commit="1.28.2",
        license_id="AGPL-3.0-only",
        license_ref="https://github.com/pymupdf/PyMuPDF/blob/main/COPYING",
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pymupdf"),
        network_ref="https://github.com/pymupdf/PyMuPDF",
        filesystem_ref="https://github.com/pymupdf/PyMuPDF",
        shell_ref="https://github.com/pymupdf/PyMuPDF",
        subprocess_ref="https://github.com/pymupdf/PyMuPDF",
        credential_ref=PYPI.format(name="pymupdf"),
        pin_ref=PROJECT.format(name="pymupdf", version="1.28.2"),
        limitations=(
            "dual AGPL-3.0-only and Artifex commercial license requires an explicit election",
            "bundled native wheel provenance reviewed at adoption",
        ),
        test_ref="https://github.com/pymupdf/PyMuPDF/tree/main/tests",
        adversarial_ref="https://github.com/pymupdf/PyMuPDF/issues",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "AGPL network copyleft versus Artifex commercial license not yet elected; "
            "deferred to an explicit license policy decision"
        ),
    )


def pillow_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pillow",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/pillow/",
        immutable_version_or_commit="12.3.0",
        license_id="MIT-CMU",
        license_ref="https://github.com/python-pillow/Pillow/blob/main/LICENSE",
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pillow"),
        network_ref="https://github.com/python-pillow/Pillow",
        filesystem_ref="https://github.com/python-pillow/Pillow",
        shell_ref="https://github.com/python-pillow/Pillow",
        subprocess_ref="https://github.com/python-pillow/Pillow",
        credential_ref=PYPI.format(name="pillow"),
        pin_ref=PROJECT.format(name="pillow", version="12.3.0"),
        limitations=(
            "C extension wheel provenance reviewed at adoption",
            "accepted raster formats remain bounded by the Skill contract (#2828)",
        ),
        test_ref="https://github.com/python-pillow/Pillow/tree/main/Tests",
        adversarial_ref="https://github.com/python-pillow/Pillow/issues",
        decision=OSSDecision.ACCEPTED,
        decision_reason=(
            "MIT-CMU package pinned at 12.3.0 with no required runtime dependencies; "
            "static intake review found no network, shell, subprocess, or credential reads"
        ),
    )


def pytesseract_record() -> OSSIntakeRecord:
    return make_record(
        candidate_id="candidate:pytesseract",
        source_kind=OSSSourceKind.PACKAGE,
        repository_or_package="https://pypi.org/project/pytesseract/",
        immutable_version_or_commit="0.3.13",
        license_id="Apache-2.0",
        license_ref="https://github.com/madmaze/pytesseract/blob/master/LICENSE",
        commercial=LegalUseStatus.ALLOWED,
        redistribution=LegalUseStatus.ALLOWED,
        dependency_ref=PYPI.format(name="pytesseract"),
        network_ref="https://github.com/madmaze/pytesseract",
        filesystem_ref="https://github.com/madmaze/pytesseract",
        shell_ref="https://github.com/madmaze/pytesseract",
        subprocess_ref="https://github.com/madmaze/pytesseract",
        credential_ref=PYPI.format(name="pytesseract"),
        pin_ref=PROJECT.format(name="pytesseract", version="0.3.13"),
        limitations=(
            "external tesseract engine binary is not immutably pinned inside the package record",
            "OCR language data version is environment-dependent",
        ),
        test_ref="https://github.com/madmaze/pytesseract/tree/master/tests",
        adversarial_ref="https://github.com/madmaze/pytesseract/issues",
        decision=OSSDecision.REJECTED,
        decision_reason=(
            "wrapper pin alone is insufficient; an environment and engine pin contract is "
            "required before OCR adoption (#2827/#2828)"
        ),
    )


def matrix_records() -> dict[str, OSSIntakeRecord]:
    records = [
        pyhwpx_record(),
        pyhwp_record(),
        hwp5_record(),
        hwpx_record(),
        pypdf_record(),
        pymupdf_record(),
        pillow_record(),
        pytesseract_record(),
    ]
    return {record.candidate_id: record for record in records}


ACCEPTED_IDS = {"candidate:pypdf", "candidate:pillow"}
DEFERRED_IDS = {
    "candidate:pyhwpx",
    "candidate:pyhwp",
    "candidate:pymupdf",
    "candidate:pytesseract",
}
REJECTED_IDS = {"candidate:hwp5", "candidate:hwpx"}
HWP_HWPX_IDS = {"candidate:pyhwpx", "candidate:pyhwp", "candidate:hwp5", "candidate:hwpx"}
PDF_IDS = {"candidate:pypdf", "candidate:pymupdf"}
IMAGE_OCR_IDS = {"candidate:pillow", "candidate:pytesseract"}


class OSSIntakeMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = OSSIntakeGate()
        cls.records = matrix_records()
        cls.receipts = {
            candidate_id: cls.gate.evaluate(record)
            for candidate_id, record in cls.records.items()
        }

    def test_matrix_covers_required_candidate_lanes(self) -> None:
        self.assertEqual(set(self.records), ACCEPTED_IDS | DEFERRED_IDS | REJECTED_IDS)
        self.assertTrue(HWP_HWPX_IDS <= set(self.records))
        self.assertTrue(PDF_IDS <= set(self.records))
        self.assertTrue(IMAGE_OCR_IDS <= set(self.records))

    def test_every_record_carries_license_pin_and_evidence(self) -> None:
        for candidate_id, record in self.records.items():
            with self.subTest(candidate_id=candidate_id):
                self.assertEqual(record.license_source.kind, "license")
                self.assertEqual(record.pinning_strategy.name, PinningStrategy.IMMUTABLE.value)
                self.assertTrue(record.test_evidence)
                self.assertTrue(record.adversarial_evidence)
                self.assertFalse(record.policy_failures() and candidate_id in ACCEPTED_IDS)

    def test_accepted_candidates_pass_gate_without_runtime_registration(self) -> None:
        for candidate_id in sorted(ACCEPTED_IDS):
            with self.subTest(candidate_id=candidate_id):
                receipt = self.receipts[candidate_id]
                self.assertEqual(receipt.decision, OSSDecision.ACCEPTED)
                self.assertEqual(receipt.decision_code, "accepted_pinned_candidate")
                self.assertTrue(receipt.adoption_allowed)
                self.assertFalse(receipt.runtime_skill_registered)
                self.assertFalse(receipt.auto_runtime_registration)
                receipt.assert_adoptable()

    def test_deferred_candidates_fail_closed_and_cannot_be_adopted(self) -> None:
        for candidate_id in sorted(DEFERRED_IDS):
            with self.subTest(candidate_id=candidate_id):
                receipt = self.receipts[candidate_id]
                self.assertEqual(receipt.decision, OSSDecision.REJECTED)
                self.assertEqual(receipt.decision_code, "explicit_rejection")
                self.assertFalse(receipt.adoption_allowed)
                with self.assertRaises(ContractError):
                    receipt.assert_adoptable()

    def test_placeholder_candidates_fail_closed_on_unknown_license_status(self) -> None:
        for candidate_id in sorted(REJECTED_IDS):
            with self.subTest(candidate_id=candidate_id):
                record = self.records[candidate_id]
                self.assertIs(record.commercial_use_status, LegalUseStatus.UNKNOWN)
                receipt = self.receipts[candidate_id]
                self.assertEqual(receipt.decision, OSSDecision.REJECTED)
                self.assertEqual(
                    receipt.decision_code, "commercial_use_not_allowed_or_unknown"
                )

    def test_pyhwp_uses_an_immutable_repository_commit_pin(self) -> None:
        record = self.records["candidate:pyhwp"]
        self.assertIs(record.source_kind, OSSSourceKind.REPOSITORY)
        self.assertRegex(
            record.immutable_version_or_commit, r"^[0-9a-f]{40}$"
        )

    def test_gate_constants_stay_non_registry_and_provider_free(self) -> None:
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)
        self.assertFalse(PROVIDER_CALLS)
        self.assertFalse(PRODUCTION_MUTATION)

    def test_receipts_project_bounded_metadata_only(self) -> None:
        projected = [receipt.safe_dict() for receipt in self.receipts.values()]
        rendered = repr(projected)
        self.assertNotIn("github.com", rendered)
        self.assertNotIn("token=", rendered)
        for receipt in self.receipts.values():
            self.assertFalse(receipt.safe_dict()["runtime_skill_registered"])
            self.assertFalse(receipt.safe_dict()["auto_runtime_registration"])


if __name__ == "__main__":
    unittest.main()
