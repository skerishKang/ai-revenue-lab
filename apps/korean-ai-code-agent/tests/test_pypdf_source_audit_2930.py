"""#2930 pypdf 6.19.0 source-behavior audit contract tests.

These tests pin the static-audit findings recorded in
``docs/PYPDF_6_19_0_SOURCE_BEHAVIOR_AUDIT_2930.md``. They never import or
execute the candidate package; they assert the evidence artifact's identity,
behavior verdicts, safety invariants, and that the canonical OSS gate and the
#2925 matrix remain unweakened.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unittest

from kagent.contracts import ContractError
from kagent.oss_skill_intake import (
    AUTO_RUNTIME_REGISTRATION,
    OSS_GATE_IS_SKILL_REGISTRY,
    OSSDecision,
    OSSIntakeGate,
    PRODUCTION_MUTATION,
    PROVIDER_CALLS,
)

from test_oss_intake_matrix_2925 import pypdf_record

UPSTREAM_REPOSITORY = "https://github.com/py-pdf/pypdf"
UPSTREAM_TAG = "6.19.0"
UPSTREAM_TAG_OBJECT = "51f9c303af50fa0f55df7640f38e3df0239e8060"
UPSTREAM_COMMIT = "d62cb58d3988b291b0435eddfd118c4f8f6b6a46"
WHEEL_SHA256 = "7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14"
SDIST_SHA256 = "bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155"

EVIDENCE_DOC = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "PYPDF_6_19_0_SOURCE_BEHAVIOR_AUDIT_2930.md"
)


@dataclass(frozen=True, slots=True)
class BehaviorVerdict:
    status: str  # ABSENT | PRESENT | PRESENT_CONDITIONAL | DATA_ONLY | ...

    @property
    def absent(self) -> bool:
        return self.status.startswith("ABSENT")


@dataclass(frozen=True, slots=True)
class SourceAuditFindings:
    package: str
    version: str
    upstream_repository: str
    upstream_tag: str
    upstream_commit: str
    immutable_source_verified: bool
    network: BehaviorVerdict
    shell: BehaviorVerdict
    subprocess: BehaviorVerdict
    credential_reads: BehaviorVerdict
    dynamic_loading: BehaviorVerdict
    javascript_execution: BehaviorVerdict
    external_uri_fetch: BehaviorVerdict
    embedded_file_auto_extract: BehaviorVerdict
    environment_reads: BehaviorVerdict
    config_discovery: BehaviorVerdict
    required_runtime_deps_on_py311: tuple[str, ...]
    disposition: str
    source_audit_complete: bool
    adoption_eligibility_review_ready: bool
    runtime_adoption: int
    file_intake_gate_substituted: bool
    gate_weakened: bool


def findings() -> SourceAuditFindings:
    return SourceAuditFindings(
        package="pypdf",
        version="6.19.0",
        upstream_repository=UPSTREAM_REPOSITORY,
        upstream_tag=UPSTREAM_TAG,
        upstream_commit=UPSTREAM_COMMIT,
        immutable_source_verified=True,
        network=BehaviorVerdict("ABSENT_IN_PACKAGE_SOURCE"),
        shell=BehaviorVerdict("ABSENT"),
        subprocess=BehaviorVerdict("PRESENT_CONDITIONAL_JBIG2DEC"),
        credential_reads=BehaviorVerdict("ABSENT"),
        dynamic_loading=BehaviorVerdict("ABSENT"),
        javascript_execution=BehaviorVerdict("ABSENT_NO_JS_ENGINE"),
        external_uri_fetch=BehaviorVerdict("ABSENT_NO_FETCH"),
        embedded_file_auto_extract=BehaviorVerdict("ABSENT_IN_MEMORY_ONLY"),
        environment_reads=BehaviorVerdict("PRESENT_CONDITIONAL_JBIG2_PATH"),
        config_discovery=BehaviorVerdict("ABSENT_PATH_LOOKUP_ONLY"),
        required_runtime_deps_on_py311=(),
        disposition="SOURCE_AUDIT_PASS_WITH_RESTRICTIONS",
        source_audit_complete=True,
        adoption_eligibility_review_ready=True,
        runtime_adoption=0,
        file_intake_gate_substituted=False,
        gate_weakened=False,
    )


class PypdfSourceAuditIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = findings()
        self.doc = EVIDENCE_DOC.read_text(encoding="utf-8")

    def test_immutable_pin_is_exact_tag_and_commit_not_floating(self) -> None:
        self.assertEqual(self.findings.version, "6.19.0")
        self.assertEqual(self.findings.upstream_tag, "6.19.0")
        self.assertRegex(self.findings.upstream_commit, r"^[0-9a-f]{40}$")
        self.assertRegex(UPSTREAM_TAG_OBJECT, r"^[0-9a-f]{40}$")
        for floating in ("main", "master", "latest"):
            self.assertNotEqual(self.findings.upstream_commit, floating)
            self.assertNotEqual(self.findings.upstream_tag, floating)
        self.assertTrue(self.findings.immutable_source_verified)

    def test_evidence_doc_pins_the_same_immutable_identity(self) -> None:
        self.assertIn(f"UPSTREAM_TAG={UPSTREAM_TAG}", self.doc)
        self.assertIn(f"UPSTREAM_TAG_OBJECT={UPSTREAM_TAG_OBJECT}", self.doc)
        self.assertIn(f"UPSTREAM_COMMIT={UPSTREAM_COMMIT}", self.doc)
        self.assertIn(f"UPSTREAM_REPOSITORY={UPSTREAM_REPOSITORY}", self.doc)
        self.assertIn(WHEEL_SHA256, self.doc)
        self.assertIn(SDIST_SHA256, self.doc)
        self.assertIn("IMMUTABLE_SOURCE_VERIFIED=YES", self.doc)
        self.assertIn("FLOATING_REF_USED=NO", self.doc)
        self.assertRegex(
            self.doc,
            re.compile(r"__version__ = \"6\.19\.0\""),
        )

    def test_evidence_doc_declares_static_analysis_scope_only(self) -> None:
        for token in (
            "PACKAGE_INSTALL=0",
            "CANDIDATE_EXECUTION=0",
            "THIRD_PARTY_SOURCE_COPY=0",
            "UNREVIEWED_CODE_EXECUTION=0",
            "RUNTIME_DEPENDENCY_ADDED=0",
            "RUNTIME_ADOPTION=0",
            "SKILL_REGISTRATION=0",
            "LIVE_PROVIDER_CALLS=0",
            "SECRET_READS=0",
            "PRODUCTION_MUTATION=0",
        ):
            self.assertIn(token, self.doc)


class PypdfSourceAuditBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = findings()
        self.doc = EVIDENCE_DOC.read_text(encoding="utf-8")

    def test_absence_verdicts_cover_network_shell_credential_and_dynamic(self) -> None:
        self.assertTrue(self.findings.network.absent)
        self.assertTrue(self.findings.shell.absent)
        self.assertTrue(self.findings.credential_reads.absent)
        self.assertTrue(self.findings.dynamic_loading.absent)
        self.assertTrue(self.findings.config_discovery.absent)

    def test_subprocess_is_recorded_as_conditional_not_absent(self) -> None:
        # The audit must not claim absence where jbig2dec subprocess exists.
        self.assertEqual(
            self.findings.subprocess.status, "PRESENT_CONDITIONAL_JBIG2DEC"
        )
        self.assertIn("SUBPROCESS_BEHAVIOR=PRESENT_CONDITIONAL_JBIG2DEC", self.doc)
        self.assertIn("shell=True", self.doc)
        self.assertIn("zero matches", self.doc)

    def test_environment_reads_are_distinguished_from_credential_reads(self) -> None:
        self.assertTrue(
            self.findings.environment_reads.status.startswith("PRESENT_CONDITIONAL")
        )
        self.assertTrue(self.findings.credential_reads.absent)
        self.assertIn("os.environ.copy()", self.doc)
        self.assertIn("shutil.which", self.doc)
        self.assertIn("CREDENTIAL_READS=ABSENT", self.doc)

    def test_javascript_and_uri_are_data_only_not_execution(self) -> None:
        self.assertTrue(self.findings.javascript_execution.absent)
        self.assertTrue(self.findings.external_uri_fetch.absent)
        self.assertIn("JAVASCRIPT_EXECUTION=NO", self.doc)
        self.assertIn("EXTERNAL_URI_FETCH=NO", self.doc)
        self.assertIn("no JavaScript interpreter", self.doc)

    def test_embedded_files_stay_in_memory_without_auto_extract(self) -> None:
        self.assertTrue(self.findings.embedded_file_auto_extract.absent)
        self.assertIn("IN_MEMORY_ONLY", self.doc)
        self.assertIn("NO_AUTO_EXTRACTION", self.doc)

    def test_py311_required_runtime_dependency_set_is_empty(self) -> None:
        self.assertEqual(self.findings.required_runtime_deps_on_py311, ())
        self.assertIn("required runtime (py>=3.11): NONE", self.doc)

    def test_optional_dependency_authority_stays_deferred_to_own_audits(self) -> None:
        self.assertIn("OPTIONAL_DEPENDENCY_AUTHORITY=DEFERRED_TRANSITIVE_AUDIT", self.doc)
        self.assertIn("optional dependency internals not established here", self.doc)
        self.assertIn("Pillow 12.3.0 is tracked separately by #2931", self.doc)
        self.assertIn("PURE_PYTHON_FALLBACK_AVAILABLE=YES", self.doc)
        self.assertIn('crypto     = cryptography>3.0', self.doc)


class PypdfSourceAuditDispositionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.findings = findings()
        self.doc = EVIDENCE_DOC.read_text(encoding="utf-8")

    def test_disposition_is_pass_with_restrictions_not_bare_accept(self) -> None:
        self.assertEqual(
            self.findings.disposition, "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS"
        )
        self.assertIn("FINAL_SOURCE_DISPOSITION=SOURCE_AUDIT_PASS_WITH_RESTRICTIONS", self.doc)
        self.assertIn("SOURCE_BEHAVIOR_AUDIT_COMPLETE=YES", self.doc)
        self.assertIn("ADOPTION_ELIGIBILITY_REVIEW_READY=YES", self.doc)

    def test_source_audit_never_approves_runtime_adoption(self) -> None:
        self.assertEqual(self.findings.runtime_adoption, 0)
        self.assertFalse(self.findings.file_intake_gate_substituted)
        self.assertFalse(self.findings.gate_weakened)
        self.assertIn("RUNTIME_ADOPTION=0", self.doc)
        self.assertIn("RUNTIME_ADOPTION_APPROVED", self.doc)

    def test_candidate_guards_do_not_substitute_padiem_intake_gate(self) -> None:
        self.assertIn("CANDIDATE_INTERNAL_GUARDS", self.doc)
        self.assertIn("PADIEM_FILE_INTAKE_GATE", self.doc)
        self.assertIn("#2824", self.doc)
        self.assertIn("do not", self.doc)
        self.assertIn("substitute for, weaken, or replace", self.doc)

    def test_restrictions_section_exists_and_names_jbig2(self) -> None:
        self.assertIn("## 11. Disposition", self.doc)
        self.assertIn("Restrictions", self.doc)
        self.assertIn("jbig2dec", self.doc)
        self.assertIn("DependencyError", self.doc)


class PypdfSourceAuditGateNonRegressionTests(unittest.TestCase):
    """The audit must not weaken the canonical gate or the #2925 matrix."""

    def test_gate_constants_remain_non_registry_and_provider_free(self) -> None:
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)
        self.assertFalse(PROVIDER_CALLS)
        self.assertFalse(PRODUCTION_MUTATION)

    def test_matrix_pypdf_record_is_unchanged_by_this_audit(self) -> None:
        # CENTRAL reconciles the matrix later; this slice must not edit it.
        record = pypdf_record()
        self.assertEqual(record.candidate_id, "candidate:pypdf")
        self.assertEqual(record.immutable_version_or_commit, "6.19.0")
        self.assertIn(
            "network_behavior_review_required", record.policy_failures()
        )
        self.assertIn(
            "credential_or_environment_read_review_required",
            record.policy_failures(),
        )
        receipt = OSSIntakeGate().evaluate(record)
        self.assertIs(receipt.decision, OSSDecision.REJECTED)
        self.assertFalse(receipt.adoption_allowed)
        with self.assertRaises(ContractError):
            receipt.assert_adoptable()

    def test_evidence_doc_requires_central_matrix_reconciliation(self) -> None:
        doc = EVIDENCE_DOC.read_text(encoding="utf-8")
        self.assertIn("OSS_CANDIDATE_INTAKE_MATRIX_2925.md", doc)
        self.assertIn("CENTRAL review", doc)


if __name__ == "__main__":
    unittest.main()
