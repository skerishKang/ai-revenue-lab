"""#2990 OSS intake reconciliation contract tests.

These tests pin the reconciled admissibility/provenance posture recorded in
``docs/OSS_INTAKE_RECONCILIATION_2990.md`` for the two candidates whose
source-behavior audits completed in #2930 and #2931.

The reconciliation is an evidence layer, not a disposition change. These tests
therefore assert, beyond the document contents:

* the immutable version pins are preserved exactly and never floating;
* both candidates keep ``SOURCE_AUDIT_PASS_WITH_RESTRICTIONS`` and are **not**
  promoted to runtime-adoption eligibility;
* the remaining provenance gaps stay explicitly UNKNOWN/DEFERRED;
* the canonical #2925 matrix rows, decisions, and gate receipts are unchanged
  (CENTRAL owns disposition);
* the canonical OSS gate is not weakened.

No candidate package is imported or executed by this module.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from kagent.oss_skill_intake import (
    AUTO_RUNTIME_REGISTRATION,
    OSS_GATE_IS_SKILL_REGISTRY,
    OSSDecision,
    OSSIntakeGate,
    PRODUCTION_MUTATION,
    PROVIDER_CALLS,
)

from test_oss_intake_matrix_2925 import pillow_record, pypdf_record

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

RECONCILIATION_DOC = DOCS / "OSS_INTAKE_RECONCILIATION_2990.md"
PYPDF_AUDIT_DOC = DOCS / "PYPDF_6_19_0_SOURCE_BEHAVIOR_AUDIT_2930.md"
PILLOW_AUDIT_DOC = DOCS / "PILLOW_12_3_0_SOURCE_AUDIT_2931.md"
MATRIX_DOC = DOCS / "OSS_CANDIDATE_INTAKE_MATRIX_2925.md"

PYPDF_TAG_OBJECT = "51f9c303af50fa0f55df7640f38e3df0239e8060"
PYPDF_COMMIT = "d62cb58d3988b291b0435eddfd118c4f8f6b6a46"
PILLOW_COMMIT = "bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d"

PYPDF_WHEEL_SHA256 = "7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14"
PYPDF_SDIST_SHA256 = "bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155"
PILLOW_SDIST_SHA256 = "3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce"

ZERO_COUNTERS = (
    "RUNTIME_DEPENDENCY_ADDED",
    "PACKAGE_INSTALL",
    "CANDIDATE_EXECUTION",
    "THIRD_PARTY_SOURCE_COPY",
    "UNREVIEWED_CODE_EXECUTION",
    "RUNTIME_REGISTRATION",
    "SKILL_REGISTRATION",
    "LIVE_PROVIDER_CALLS",
    "SECRET_READS",
    "PRODUCTION_MUTATION",
)

NON_EQUIVALENCE_LINES = (
    "METADATA_LICENSE_REVIEW != SOURCE_BEHAVIOR_AUDIT != RUNTIME_ADOPTION",
    "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS != ADOPTION_ELIGIBLE",
    "NATIVE_BINARY_PROVENANCE_PENDING != NATIVE_BINARY_PROVENANCE_ACCEPTED",
)


def load(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_kv(doc: str) -> dict[str, str]:
    """Parse top-level ``KEY=value`` lines.

    Only the block before the first candidate section is parsed, because the
    per-candidate sections deliberately reuse the same key names (for example
    ``SUBPROCESS_POSTURE``) with different values. Those are read through
    :func:`candidate_kv` instead, so a shared first-occurrence parse can never
    silently attribute pypdf's value to Pillow or vice versa.
    """

    head = doc.split("## pypdf 6.19.0 disposition")[0]
    kv: dict[str, str] = {}
    for line in head.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]+)=(.+)$", line)
        if match and match.group(1) not in kv:
            kv[match.group(1)] = match.group(2).strip()
    return kv


def candidate_kv(doc: str, heading: str, next_heading: str) -> dict[str, str]:
    """Parse the ``KEY=value`` lines of exactly one candidate section."""

    block = doc.split(heading)[1].split(next_heading)[0]
    kv: dict[str, str] = {}
    for line in block.splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]+)=(.+)$", line)
        if match and match.group(1) not in kv:
            kv[match.group(1)] = match.group(2).strip()
    return kv


PYPDF_KV = "## pypdf 6.19.0 disposition"
PILLOW_KV = "## Pillow 12.3.0 disposition"
NEXT_SECTION = "## Reconciliation effect on the canonical matrix"


class ReconciliationDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load(RECONCILIATION_DOC)
        cls.kv = parse_kv(cls.doc)

    def test_reconciliation_artifact_exists(self) -> None:
        self.assertTrue(RECONCILIATION_DOC.is_file())

    def test_safety_counters_are_zero_and_gate_not_weakened(self) -> None:
        for key in ZERO_COUNTERS:
            self.assertEqual(self.kv.get(key), "0", key)
        self.assertEqual(self.kv.get("GATE_WEAKENED"), "NO")

    def test_non_equivalence_statements_recorded(self) -> None:
        for line in NON_EQUIVALENCE_LINES:
            self.assertIn(line, self.doc)

    def test_acceptance_block_is_complete(self) -> None:
        acceptance = candidate_kv(self.doc, "## Acceptance", "\nCENTRAL owns")
        for key, expected in (
            ("PYPDF_AUDIT_RECONCILED", "YES"),
            ("PILLOW_AUDIT_RECONCILED", "YES"),
            ("IMMUTABLE_PINS_PRESERVED", "YES"),
            ("RESTRICTIONS_PRESERVED", "YES"),
            ("UNKNOWN_REMAINS_UNKNOWN", "YES"),
            ("RUNTIME_ADOPTION", "0"),
            ("GATE_WEAKENED", "NO"),
            ("NEXT_DECISIONS_EXPLICIT", "YES"),
        ):
            self.assertEqual(acceptance.get(key), expected, key)

    def test_future_child_numbers_are_not_preallocated(self) -> None:
        self.assertNotIn("#3026", self.doc)
        self.assertNotIn("#3027", self.doc)
        self.assertIn(
            "NEXT_CHILD_PYPDF_JBIG2DEC_SUBPROCESS_AUTHORITY=UNASSIGNED",
            self.doc,
        )
        self.assertIn(
            "NEXT_CHILD_PILLOW_NATIVE_WHEEL_PROVENANCE=UNASSIGNED",
            self.doc,
        )

    def test_no_secret_material_in_document(self) -> None:
        lowered = self.doc.lower()
        for token in ("password=", "api_key=", "private key", "bearer "):
            self.assertNotIn(token, lowered)


class ImmutablePinPreservationTests(unittest.TestCase):
    """The reconciliation must carry the same immutable identities, never floats."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load(RECONCILIATION_DOC)
        cls.kv = parse_kv(cls.doc)
        cls.pypdf_audit = load(PYPDF_AUDIT_DOC)
        cls.pillow_audit = load(PILLOW_AUDIT_DOC)

    def test_pypdf_identity_matches_the_2930_audit(self) -> None:
        self.assertIn(PYPDF_TAG_OBJECT, self.doc)
        self.assertIn(PYPDF_COMMIT, self.doc)
        self.assertIn(PYPDF_TAG_OBJECT, self.pypdf_audit)
        self.assertIn(PYPDF_COMMIT, self.pypdf_audit)
        self.assertIn(PYPDF_WHEEL_SHA256, self.doc)
        self.assertIn(PYPDF_SDIST_SHA256, self.doc)

    def test_pillow_identity_matches_the_2931_audit(self) -> None:
        self.assertIn(PILLOW_COMMIT, self.doc)
        self.assertIn(PILLOW_COMMIT, self.pillow_audit)
        self.assertIn(PILLOW_SDIST_SHA256, self.doc)

    def test_no_floating_reference_is_used_as_a_pin(self) -> None:
        self.assertEqual(self.kv.get("FLOATING_REF_USED"), "NO")
        self.assertEqual(self.kv.get("IMMUTABLE_PINS_PRESERVED"), "YES")
        for forbidden in ("main", "master", "latest"):
            self.assertNotEqual(PYPDF_COMMIT, forbidden)
            self.assertNotEqual(PILLOW_COMMIT, forbidden)

    def test_pillow_tag_type_asymmetry_is_recorded(self) -> None:
        # Pillow's 12.3.0 tag is lightweight: the commit IS the tag target,
        # so the pin must always be cited as the commit.
        self.assertIn("PILLOW_UPSTREAM_TAG_TYPE=LIGHTWEIGHT", self.doc)
        self.assertIn("PYPDF_UPSTREAM_TAG_TYPE=ANNOTATED", self.doc)


class PypdfReconciliationTests(unittest.TestCase):
    """Values parsed from the pypdf section only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load(RECONCILIATION_DOC)
        cls.kv = candidate_kv(cls.doc, PYPDF_KV, PILLOW_KV)
        cls.block = cls.doc.split(PYPDF_KV)[1].split(PILLOW_KV)[0]

    def test_candidate_identity_is_pypdf_6_19_0(self) -> None:
        self.assertEqual(self.kv.get("CANDIDATE"), "candidate:pypdf")
        self.assertEqual(self.kv.get("VERSION"), "6.19.0")
        self.assertEqual(self.kv.get("IMMUTABLE_PIN"), "6.19.0")
        self.assertEqual(self.kv.get("LICENSE"), "BSD-3-Clause")

    def test_source_audit_status_is_pass_with_restrictions(self) -> None:
        self.assertEqual(
            self.kv.get("SOURCE_AUDIT_STATUS"), "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS"
        )
        self.assertEqual(self.kv.get("SOURCE_AUDIT_COMPLETE"), "YES")

    def test_runtime_adoption_eligible_is_no(self) -> None:
        self.assertEqual(self.kv.get("RUNTIME_ADOPTION_ELIGIBLE"), "NO")
        self.assertEqual(self.kv.get("RUNTIME_ADOPTION"), "0")
        self.assertEqual(self.kv.get("SKILL_REGISTRATION"), "0")

    def test_subprocess_posture_is_conditional_jbig2dec_not_absent(self) -> None:
        posture = self.kv.get("SUBPROCESS_POSTURE", "")
        self.assertIn("PRESENT_CONDITIONAL_JBIG2DEC", posture)
        self.assertIn("fail-closed", posture.lower())

    def test_environment_credential_posture_distinguishes_reads_from_propagation(self) -> None:
        posture = self.kv.get("ENVIRONMENT_CREDENTIAL_POSTURE", "")
        self.assertIn("CREDENTIAL_READS_ABSENT", posture)
        # the conditional child-env propagation must be named explicitly
        self.assertIn(
            "CREDENTIAL_ENV_PROPAGATION=PRESENT_CONDITIONAL_JBIG2DEC", posture
        )
        self.assertIn("os.environ.copy()", self.block)

    def test_optional_dependency_gaps_remain_deferred(self) -> None:
        self.assertIn(
            "DEFERRED_TRANSITIVE_AUDIT", self.kv.get("OPTIONAL_DEPENDENCY_GAPS", "")
        )
        for extra in ("cryptography", "PyCryptodome", "fonttools", "python-bidi"):
            self.assertIn(extra, self.block)

    def test_native_binary_gap_reflects_pure_python_core_wheel(self) -> None:
        gap = self.kv.get("NATIVE_BINARY_GAPS", "")
        self.assertIn("CORE_WHEEL_IS_PURE_PYTHON", gap)
        self.assertIn("OPTIONAL_EXTRA_WHEELS_ONLY", gap)

    def test_remaining_provenance_gaps_are_named(self) -> None:
        gaps = self.kv.get("REMAINING_PROVENANCE_GAPS", "")
        self.assertIn("OPTIONAL_EXTRA_INTERNALS_NOT_ESTABLISHED", gaps)
        self.assertIn("JBIG2DEC_BINARY_PROVENANCE_NOT_ESTABLISHED", gaps)

    def test_next_bounded_decision_is_explicit(self) -> None:
        decision = self.kv.get("NEXT_BOUNDED_DECISION", "")
        self.assertIn("JBIG2DEC", decision.upper())


class PillowReconciliationTests(unittest.TestCase):
    """Values parsed from the Pillow section only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load(RECONCILIATION_DOC)
        cls.kv = candidate_kv(cls.doc, PILLOW_KV, NEXT_SECTION)
        cls.block = cls.doc.split(PILLOW_KV)[1].split(NEXT_SECTION)[0]

    def test_candidate_identity_is_pillow_12_3_0(self) -> None:
        self.assertEqual(self.kv.get("CANDIDATE"), "candidate:pillow")
        self.assertEqual(self.kv.get("VERSION"), "12.3.0")
        self.assertEqual(self.kv.get("IMMUTABLE_PIN"), "12.3.0")
        self.assertEqual(self.kv.get("LICENSE"), "MIT-CMU")

    def test_source_audit_status_is_pass_with_restrictions(self) -> None:
        self.assertEqual(
            self.kv.get("SOURCE_AUDIT_STATUS"), "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS"
        )
        self.assertEqual(self.kv.get("SOURCE_AUDIT_COMPLETE"), "YES")

    def test_runtime_adoption_eligible_is_no(self) -> None:
        self.assertEqual(self.kv.get("RUNTIME_ADOPTION_ELIGIBLE"), "NO")
        self.assertEqual(self.kv.get("RUNTIME_ADOPTION"), "0")
        self.assertEqual(self.kv.get("SKILL_REGISTRATION"), "0")

    def test_native_binary_provenance_stays_pending(self) -> None:
        self.assertIn(
            "NATIVE_WHEEL_PROVENANCE_PENDING",
            self.kv.get("REMAINING_PROVENANCE_GAPS", ""),
        )
        self.assertIn("NATIVE_WHEEL_PROVENANCE_PENDING", self.block)

    def test_native_binary_gaps_count_the_extension_targets(self) -> None:
        gap = self.kv.get("NATIVE_BINARY_GAPS", "")
        self.assertIn("8_C_EXTENSION_TARGETS", gap)
        for ext in ("_imaging", "_imagingft", "_webp", "_avif", "_imagingmath"):
            self.assertIn(ext, gap)

    def test_subprocess_posture_is_format_or_api_gated(self) -> None:
        posture = self.kv.get("SUBPROCESS_POSTURE", "")
        self.assertTrue(
            "FORMAT_OR_API_GATED" in posture,
            "Pillow posture must remain format/API gated, not absent",
        )
        self.assertIn("gs", self.block)
        self.assertIn(".eps", self.block)

    def test_environment_credential_posture_reports_no_credential_reads(self) -> None:
        posture = self.kv.get("ENVIRONMENT_CREDENTIAL_POSTURE", "")
        self.assertIn("CREDENTIAL_READS=NONE_FOUND", posture)

    def test_safeguards_are_recorded_as_observed_facts(self) -> None:
        self.assertIn("MAX_IMAGE_PIXELS_DEFAULT=89478485", self.block)
        self.assertIn("DECOMPRESSION_BOMB_PROTECTION=ENFORCED_DEFAULT", self.block)
        self.assertIn("MULTIFRAME_RESOURCE_RISK=UNCAPPED_FRAME_COUNT", self.block)
        self.assertIn("METADATA_BEHAVIOR=READ_WRITE_NO_AUTO_SANITIZATION", self.block)

    def test_next_bounded_decision_is_explicit(self) -> None:
        decision = self.kv.get("NEXT_BOUNDED_DECISION", "")
        self.assertIn("NATIVE_WHEEL_PROVENANCE", decision.upper())


class UnknownRemainsUnknownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load(RECONCILIATION_DOC)
        cls.kv = parse_kv(cls.doc)
        cls.gap_block = cls.doc.split("## Remaining provenance gaps")[1].split("## Next")[0]

    def test_every_named_gap_is_unknown_not_pass(self) -> None:
        gaps = candidate_kv(self.doc, "## Remaining provenance gaps", "## Next")
        self.assertTrue(gaps, "the reconciliation must name its remaining gaps")
        for key, value in gaps.items():
            with self.subTest(gap=key):
                self.assertTrue(
                    value == "UNKNOWN" or value.startswith("UNAUDITED"),
                    f"{key} must remain UNKNOWN/UNAUDITED, got {value!r}",
                )

    def test_gap_covers_both_candidates_families(self) -> None:
        gaps = candidate_kv(self.doc, "## Remaining provenance gaps", "## Next")
        for key in (
            "JBIG2DEC_BINARY_PROVENANCE",
            "CRYPTOGRAPHY_INTERNALS",
            "PILLOW_WHEEL_ATTESTATION",
            "FUTURE_RELEASES",
        ):
            self.assertIn(key, gaps)

    def test_no_gap_is_silently_promoted(self) -> None:
        self.assertIn("no unknown is silently", self.doc.lower())
        self.assertIn("No absence is inferred from package metadata", self.doc)


class MatrixDispositionUnchangedTests(unittest.TestCase):
    """Reconciliation is an evidence layer; it must not move dispositions."""

    def test_matrix_declares_no_disposition_change(self) -> None:
        doc = load(RECONCILIATION_DOC)
        self.assertIn("MATRIX_ROWS_UNCHANGED=YES", doc)
        self.assertIn("MATRIX_DECISIONS_UNCHANGED=YES", doc)
        self.assertIn("DISPOSITION_CHANGED=NO", doc)
        self.assertIn("UPGRADE_FROM_DEFERRED=NO", doc)

    def test_matrix_document_points_at_reconciliation_without_row_edits(self) -> None:
        matrix = load(MATRIX_DOC)
        self.assertIn("OSS_INTAKE_RECONCILIATION_2990.md", matrix)
        self.assertIn("#2990", matrix)
        # both candidate rows still present with their original pin and outcome
        self.assertIn("| pypdf | PDF | package | `6.19.0` | BSD-3-Clause |", matrix)
        self.assertIn("| pillow | image | package | `12.3.0` | MIT-CMU |", matrix)

    def test_pypdf_gate_receipt_is_unchanged_by_reconciliation(self) -> None:
        record = pypdf_record()
        self.assertEqual(record.immutable_version_or_commit, "6.19.0")
        self.assertIn("network_behavior_review_required", record.policy_failures())
        receipt = OSSIntakeGate().evaluate(record)
        self.assertIs(receipt.decision, OSSDecision.REJECTED)
        self.assertFalse(receipt.adoption_allowed)
        self.assertFalse(receipt.runtime_skill_registered)
        self.assertFalse(receipt.auto_runtime_registration)

    def test_pillow_gate_receipt_is_unchanged_by_reconciliation(self) -> None:
        record = pillow_record()
        self.assertEqual(record.immutable_version_or_commit, "12.3.0")
        self.assertIn("network_behavior_review_required", record.policy_failures())
        receipt = OSSIntakeGate().evaluate(record)
        self.assertIs(receipt.decision, OSSDecision.REJECTED)
        self.assertFalse(receipt.adoption_allowed)
        self.assertFalse(receipt.runtime_skill_registered)
        self.assertFalse(receipt.auto_runtime_registration)

    def test_gate_constants_remain_non_registry_and_provider_free(self) -> None:
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)
        self.assertFalse(PROVIDER_CALLS)
        self.assertFalse(PRODUCTION_MUTATION)


if __name__ == "__main__":
    unittest.main()
