"""#3012 pypdf jbig2dec authority contract tests.

These tests validate a source-only evidence/decision artifact. They do not import or
execute pypdf, resolve PATH, invoke jbig2dec, or weaken the canonical OSS gate.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from kagent.oss_skill_intake import (
    AUTO_RUNTIME_REGISTRATION,
    OSS_GATE_IS_SKILL_REGISTRY,
    PRODUCTION_MUTATION,
    PROVIDER_CALLS,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "PYPDF_6_19_0_JBIG2DEC_AUTHORITY_3012.md"
MATRIX = REPO_ROOT / "docs" / "OSS_CANDIDATE_INTAKE_MATRIX_2925.md"
RECON = REPO_ROOT / "docs" / "OSS_INTAKE_RECONCILIATION_2990.md"
PARSER_BOUNDARY = REPO_ROOT.parent / ".." / "packages" / "padiem-ai-core" / "padiem_ai_core" / "document_parser_boundary.py"


class PypdfJbig2decAuthorityEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = DOC.read_text(encoding="utf-8")

    def test_immutable_pypdf_identity_and_current_main_are_recorded(self) -> None:
        for token in (
            "UPSTREAM_TAG=6.19.0",
            "UPSTREAM_TAG_OBJECT=51f9c303af50fa0f55df7640f38e3df0239e8060",
            "UPSTREAM_COMMIT=d62cb58d3988b291b0435eddfd118c4f8f6b6a46",
            "PYPDF_WHEEL_SHA256=7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14",
            "PYPDF_SDIST_SHA256=bbc43aca292369ccc6cbc8a921991ecf2538a3587ab5a116eff06c321d647155",
            "FLOATING_REF_USED=NO",
        ):
            self.assertIn(token, self.doc)

    def test_default_is_disabled_and_subprocess_risk_is_not_hidden(self) -> None:
        for token in (
            "JBIG2DEC_DEFAULT_ENABLED=NO",
            "JBIG2DEC_REQUIRED_FOR_COMMON_PDF=NO",
            "SUBPROCESS_ENV_INHERITS_HOST=YES_IN_PINNED_UPSTREAM_PATH",
            "RAW_SECRET_INHERITANCE_RISK=YES",
            "NETWORK_AUTHORITY_GAINED=NO",
            "SAFE_DISABLE_POSSIBLE=YES",
            "BOUNDED_WRAPPER_POSSIBLE=YES",
            "os.environ.copy()",
            "shutil.which",
        ):
            self.assertIn(token, self.doc)

    def test_later_wrapper_contract_is_fail_closed_and_bounded(self) -> None:
        for token in (
            "EXECUTABLE_ORIGIN=REVIEWED_AND_IMMUTABLE",
            "CHILD_ENVIRONMENT=ALLOWLISTED_ENV_ONLY",
            "RAW_HOST_ENV_INHERITANCE=NO",
            "SHELL_EXECUTION=NO",
            "UNBOUNDED_SUBPROCESS=NO",
            "FLOATING_BINARY=NO",
            "NETWORK_ESCALATION=NO",
            "FAIL_CLOSED_WHEN_BINARY_ABSENT_OR_UNAPPROVED=YES",
        ):
            self.assertIn(token, self.doc)

    def test_required_negative_cases_are_explicit(self) -> None:
        for token in (
            "UNEXPECTED_EXECUTABLE=REJECT",
            "UNEXPECTED_PATH=REJECT",
            "SECRET_LIKE_ENV_INHERITANCE=REJECT",
            "UNPINNED_VERSION=REJECT",
            "UNSUPPORTED_BINARY_ORIGIN=REJECT",
            "HASH_OR_PROVENANCE_MISMATCH=REJECT",
        ):
            self.assertIn(token, self.doc)

    def test_no_runtime_or_production_authority_is_claimed(self) -> None:
        for token in (
            "RUNTIME_ADOPTION=0",
            "RUNTIME_SKILL_REGISTRATION=0",
            "THIRD_PARTY_SKILL_EXECUTION=0",
            "PIP_INSTALL=0",
            "PACKAGE_IMPORT=0",
            "JBIG2DEC_EXECUTION=0",
            "PROVIDER_CALL=0",
            "NETWORK_PROVIDER_CALL=0",
            "SECRET_VALUE_READ=0",
            "SECRET_MUTATION=0",
            "PRODUCTION_DEPLOY=0",
            "PRODUCTION_MUTATION=0",
            "GATE_WEAKENED=NO",
        ):
            self.assertIn(token, self.doc)


class PypdfJbig2decNonRegressionTests(unittest.TestCase):
    def test_canonical_gate_remains_non_registry_and_provider_free(self) -> None:
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)
        self.assertFalse(PROVIDER_CALLS)
        self.assertFalse(PRODUCTION_MUTATION)

    def test_existing_reconciliation_remains_non_adoption(self) -> None:
        recon = RECON.read_text(encoding="utf-8")
        self.assertIn("RUNTIME_ADOPTION=0", recon)
        self.assertIn("RUNTIME_ADOPTION_ELIGIBLE=NO", recon)
        self.assertIn("JBIG2DEC_BINARY_PROVENANCE=UNKNOWN", recon)

    def test_matrix_rows_remain_deferred_and_unchanged(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
        self.assertIn("| pypdf | PDF | package | `6.19.0` | BSD-3-Clause |", matrix)
        self.assertIn("| pillow | image | package | `12.3.0` | MIT-CMU |", matrix)
        self.assertIn("decision=DEFERRED", matrix)

    def test_parser_boundary_remains_existing_fail_closed_authority(self) -> None:
        source = PARSER_BOUNDARY.resolve().read_text(encoding="utf-8")
        self.assertIn("resolve_binary_document_parser_authority", source)
        self.assertIn("DocumentParserAuthorityUnavailable", source)
        self.assertIn("fail closed", source.lower())
        self.assertNotIn("install_worker_isolated_parser_composition", DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
