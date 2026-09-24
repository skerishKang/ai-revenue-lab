"""#3016 Pillow 12.3.0 native-wheel provenance contract tests.

These tests validate a source-only policy artifact. They do not import, install,
or execute Pillow, download a wheel, or change the canonical intake matrix.
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
DOC = REPO_ROOT / "docs" / "PILLOW_12_3_0_NATIVE_WHEEL_PROVENANCE_3016.md"
MATRIX = REPO_ROOT / "docs" / "OSS_CANDIDATE_INTAKE_MATRIX_2925.md"
RECON = REPO_ROOT / "docs" / "OSS_INTAKE_RECONCILIATION_2990.md"
PARSER_BOUNDARY = REPO_ROOT.parent / ".." / "packages" / "padiem-ai-core" / "padiem_ai_core" / "document_parser_boundary.py"


class PillowNativeWheelProvenanceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = DOC.read_text(encoding="utf-8")

    def test_immutable_identity_and_fresh_main_are_recorded(self) -> None:
        for token in (
            "origin/main=070ceee351bf8ce07bfa119f0fc268cc342df18c",
            "PACKAGE=Pillow",
            "VERSION=12.3.0",
            "UPSTREAM_TAG_OBJECT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d",
            "UPSTREAM_COMMIT=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d",
            "PYPI_SDIST_SHA256=3b8182a766685eaa002637e28b4ec8d6b18819a0c71f579bf0dbaa5830297cce",
            "FLOATING_REF_USED=NO",
        ):
            self.assertIn(token, self.doc)

    def test_official_wheel_surface_is_explicit_and_bounded(self) -> None:
        for token in (
            "OFFICIAL_WHEEL_EXISTS=YES",
            "OFFICIAL_WHEEL_ORIGIN=PYPI_PROJECT_Pillow_12.3.0_OFFICIAL_RELEASE",
            "WHEEL_HASH_PINNABLE=YES",
            "WHEEL_PLATFORM_EXPLICIT=YES_IN_WHEEL_FILENAME",
            "WHEEL_ABI_EXPLICIT=YES_IN_WHEEL_FILENAME",
            "BUNDLED_NATIVE_LIBRARIES_PRESENT=YES_PER_RELEASE_WHEEL",
            "SYSTEM_NATIVE_LIBRARIES_REQUIRED=NO_FOR_REVIEWED_OFFICIAL_WHEEL; YES_IF_SOURCE_BUILD",
            "DYNAMIC_NATIVE_LOADING_PRESENT=YES",
            "EXTERNAL_PROCESS_EXECUTION=FORMAT_OR_API_GATED",
            "NETWORK_AUTHORITY_GAINED=NO_IN_CORE",
            "RAW_HOST_ENV_INHERITANCE=NO_RUNTIME_PROCESS",
            "WHEEL_INSTALL_IMPLICITLY_FETCHES_RUNTIME_BINARY=NO",
        ):
            self.assertIn(token, self.doc)

    def test_source_build_is_not_treated_as_automatically_safer(self) -> None:
        for token in (
            "SOURCE_BUILD_REQUIRES_COMPILER=YES",
            "SOURCE_BUILD_REQUIRES_SYSTEM_HEADERS=YES_FOR_NATIVE_CODECS",
            "SOURCE_BUILD_NATIVE_DEPENDENCY_DISCOVERY=YES_ENVIRONMENT_AND_PATH_SENSITIVE",
            "SOURCE_BUILD_ENVIRONMENT_SENSITIVE=YES",
            "SOURCE_BUILD_REPRODUCIBLE_BY_DEFAULT=NO",
            "A source build is not automatically more trustworthy",
        ):
            self.assertIn(token, self.doc)

    def test_policy_requires_platform_specific_receipt(self) -> None:
        for token in (
            "PILLOW_PROVENANCE_DECISION=PLATFORM_SPECIFIC_ACCEPTANCE_REQUIRED",
            "WINDOWS_X64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE",
            "LINUX_X64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE",
            "MACOS_ARM64=RECEIPT_REQUIRED_BEFORE_ACCEPTANCE",
            "OTHER_OR_UNREVIEWED_PLATFORM=REJECT",
            "RELEASE_SPECIFIC_ATTESTATION_VERIFIED_BY_THIS_AUDIT=NO",
            "RELEASE_SPECIFIC_SBOM_VERIFIED_BY_THIS_AUDIT=NO",
        ):
            self.assertIn(token, self.doc)

    def test_receipt_fields_and_negative_cases_are_explicit(self) -> None:
        for token in (
            "WHEEL_FILENAME=",
            "PYTHON_TAG=",
            "ABI_TAG=",
            "PLATFORM_TAG=",
            "SHA256=",
            "SOURCE_RELEASE_REF=bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d",
            "NATIVE_BINARY_POSTURE=",
            "FLOATING_VERSION=NO",
            "UNHASHED_WHEEL=NO",
            "UNREVIEWED_PLATFORM=NO",
            "UNPINNED_PILLOW_VERSION=REJECT",
            "UNKNOWN_WHEEL_FILENAME=REJECT",
            "UNKNOWN_PLATFORM_TAG=REJECT",
            "UNKNOWN_ABI_TAG=REJECT",
            "HASH_MISMATCH=REJECT",
            "NON_OFFICIAL_ORIGIN=REJECT",
            "UNSUPPORTED_PLATFORM=REJECT",
            "MISSING_PROVENANCE_RECEIPT=REJECT",
            "FLOATING_LATEST=REJECT",
        ):
            self.assertIn(token, self.doc)

    def test_source_build_negative_cases_are_explicit(self) -> None:
        for token in (
            "UNPINNED_COMPILER=REJECT",
            "UNPINNED_NATIVE_DEPENDENCY=REJECT",
            "UNRECORDED_BUILD_FLAGS=REJECT",
            "MISSING_OUTPUT_HASH=REJECT",
        ):
            self.assertIn(token, self.doc)

    def test_no_runtime_or_production_authority_is_claimed(self) -> None:
        for token in (
            "PIP_INSTALL=0",
            "PILLOW_IMPORT=0",
            "PILLOW_RUNTIME_EXECUTION=0",
            "IMAGE_RUNTIME_REGISTRATION=0",
            "IMAGE_SKILL_REGISTRATION=0",
            "THIRD_PARTY_SKILL_EXECUTION=0",
            "PROVIDER_CALL=0",
            "NETWORK_PROVIDER_CALL=0",
            "SECRET_VALUE_READ=0",
            "SECRET_MUTATION=0",
            "PRODUCTION_DEPLOY=0",
            "PRODUCTION_MUTATION=0",
            "MATRIX_ADOPTION_CHANGE=0",
            "GATE_WEAKENED=NO",
            "RUNTIME_ADOPTION=0",
            "DRAFT_ONLY=YES",
            "READY=NO",
            "MERGE=NO",
            "STOP_AND_WAIT_FOR_CENTRAL=YES",
        ):
            self.assertIn(token, self.doc)


class PillowNativeWheelProvenanceNonRegressionTests(unittest.TestCase):
    def test_canonical_gate_remains_non_registry_and_provider_free(self) -> None:
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)
        self.assertFalse(PROVIDER_CALLS)
        self.assertFalse(PRODUCTION_MUTATION)

    def test_existing_reconciliation_remains_non_adoption(self) -> None:
        recon = RECON.read_text(encoding="utf-8")
        self.assertIn("RUNTIME_ADOPTION=0", recon)
        self.assertIn("RUNTIME_ADOPTION_ELIGIBLE=NO", recon)
        self.assertIn("PILLOW_WHEEL_ATTESTATION=UNKNOWN", recon)

    def test_matrix_rows_remain_deferred_and_unchanged(self) -> None:
        matrix = MATRIX.read_text(encoding="utf-8")
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
