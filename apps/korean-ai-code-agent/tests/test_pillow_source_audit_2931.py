"""#2931 Pillow 12.3.0 immutable source behavior audit contract tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import unittest

from kagent.oss_skill_intake import AUTO_RUNTIME_REGISTRATION, OSS_GATE_IS_SKILL_REGISTRY

DOC_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "PILLOW_12_3_0_SOURCE_AUDIT_2931.md"
)
GATE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "kagent" / "oss_skill_intake.py"
)
GATE_SHA256 = (
    "E0994FF666A041FCE7484BFE22C0F57DA1E56FF0938F474CA63B3576DFDDF259"
)

UPSTREAM_COMMIT = "bb1d8e8ab8d29048624d96e3ee53cecf7c13d13d"
ALLOWED_DISPOSITIONS = {
    "SOURCE_AUDIT_PASS",
    "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS",
    "DEFERRED",
    "REJECTED",
}
ZERO_COUNTERS = (
    "RUNTIME_ADOPTION",
    "RUNTIME_DEPENDENCY_ADDED",
    "PACKAGE_INSTALL",
    "CANDIDATE_EXECUTION",
    "THIRD_PARTY_SOURCE_COPY",
    "UNREVIEWED_CODE_EXECUTION",
    "SKILL_REGISTRATION",
    "LIVE_PROVIDER_CALLS",
    "SECRET_READS",
    "PRODUCTION_MUTATION",
    "PADIEM_MATRIX_EDITED",
)
REQUIRED_KEYS = (
    "ISSUE",
    "PACKAGE",
    "PACKAGE_VERSION",
    "UPSTREAM_REPOSITORY",
    "UPSTREAM_TAG",
    "UPSTREAM_COMMIT",
    "IMMUTABLE_SOURCE_VERIFIED",
    "PYPI_SDIST_SHA256",
    "SOURCE_AUDIT_METHOD",
    "SOURCE_BEHAVIOR_AUDIT_COMPLETE",
    "FINAL_SOURCE_DISPOSITION",
    "NATIVE_BINARY_PROVENANCE_PENDING",
    "NETWORK_BEHAVIOR",
    "FILESYSTEM_READ",
    "FILESYSTEM_WRITE",
    "SHELL_ACCESS",
    "SUBPROCESS_BEHAVIOR",
    "EXTERNAL_EXECUTABLE_BEHAVIOR",
    "ENVIRONMENT_READS",
    "CREDENTIAL_READS",
    "DYNAMIC_PLUGIN_LOADING",
    "DYNAMIC_LIBRARY_LOADING",
    "METADATA_BEHAVIOR",
    "DECOMPRESSION_BOMB_PROTECTION",
    "MULTIFRAME_RESOURCE_RISK",
    "MALFORMED_IMAGE_FAILURE",
    "TRANSITIVE_RUNTIME_DEPENDENCIES",
    "MAX_IMAGE_PIXELS_DEFAULT",
    "OSS_GATE_UNCHANGED",
    "CENTRAL_RECONCILIATION_REQUIRED",
)
NON_EQUIVALENCE_LINES = (
    "METADATA_LICENSE_REVIEW != SOURCE_BEHAVIOR_AUDIT != RUNTIME_ADOPTION",
    "PILLOW_INTERNAL_GUARDS != PADIEM_FILE_INTAKE_AUTHORITY",
    "SOURCE_AUDIT_PASS_WITH_RESTRICTIONS != NATIVE_WHEEL_PROVENANCE_ACCEPTED",
)
EXTERNAL_EXEC_MODULES = (
    "EpsImagePlugin",
    "JpegImagePlugin",
    "GifImagePlugin",
    "ImageShow",
    "ImageGrab",
)


def load_doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def parse_kv(doc: str) -> dict[str, str]:
    kv: dict[str, str] = {}
    for line in doc.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]+)=(.+)$", line)
        if m and m.group(1) not in kv:
            kv[m.group(1)] = m.group(2).strip()
    return kv


class PillowSourceAudit2931Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load_doc()
        cls.kv = parse_kv(cls.doc)

    def test_document_present_with_commit_pinned_evidence_links(self) -> None:
        self.assertTrue(DOC_PATH.is_file())
        self.assertIn(f"blob/{UPSTREAM_COMMIT}/src/PIL/Image.py", self.doc)
        self.assertIn(UPSTREAM_COMMIT, self.kv["UPSTREAM_COMMIT"])
        self.assertRegex(self.kv["UPSTREAM_COMMIT"], r"^[0-9a-f]{40}$")
        self.assertEqual(self.kv["IMMUTABLE_SOURCE_VERIFIED"], "YES")
        self.assertEqual(self.kv["UPSTREAM_TAG"], "12.3.0")
        self.assertEqual(self.kv["PACKAGE"], "Pillow")
        self.assertRegex(
            self.kv["PYPI_SDIST_SHA256"], r"^[0-9a-f]{64}$"
        )

    def test_required_keys_present(self) -> None:
        missing = [k for k in REQUIRED_KEYS if k not in self.kv]
        self.assertEqual(missing, [])

    def test_disposition_and_completion_contract(self) -> None:
        self.assertEqual(self.kv["ISSUE"], "2931")
        self.assertEqual(self.kv["SOURCE_BEHAVIOR_AUDIT_COMPLETE"], "YES")
        self.assertIn(self.kv["FINAL_SOURCE_DISPOSITION"], ALLOWED_DISPOSITIONS)
        self.assertEqual(self.kv["NATIVE_BINARY_PROVENANCE_PENDING"], "YES")
        self.assertEqual(self.kv["SOURCE_AUDIT_METHOD"], "STATIC_READ_ONLY")
        self.assertEqual(self.kv["OSS_GATE_UNCHANGED"], "YES")
        self.assertEqual(self.kv["CENTRAL_RECONCILIATION_REQUIRED"], "YES")
        self.assertEqual(self.kv["CREDENTIAL_READS"], "NONE_FOUND")
        self.assertEqual(self.kv["MAX_IMAGE_PIXELS_DEFAULT"], "89478485")
        self.assertEqual(
            self.kv["PY_IMPORT_SOCKET_URLLIB_REQUESTS_COUNT"], "0"
        )
        self.assertEqual(self.kv["SHELL_TRUE_CALL_COUNT"], "0")
        self.assertEqual(self.kv["OS_SYSTEM_CALL_COUNT"], "1")

    def test_zero_adoption_and_safety_counters(self) -> None:
        for key in ZERO_COUNTERS:
            self.assertEqual(self.kv.get(key), "0", key)
        self.assertEqual(self.kv.get("PADIEM_MATRIX_EDITED"), "0")

    def test_non_equivalence_statements_recorded(self) -> None:
        for line in NON_EQUIVALENCE_LINES:
            self.assertIn(line, self.doc)

    def test_external_executable_matrix_covers_known_tools(self) -> None:
        for module in EXTERNAL_EXEC_MODULES:
            self.assertIn(module, self.doc)
        self.assertEqual(self.kv["EXTERNAL_EXECUTABLE_BEHAVIOR"], "FORMAT_OR_API_GATED")

    def test_no_secret_material_in_document(self) -> None:
        lowered = self.doc.lower()
        self.assertNotIn("password=", lowered)
        self.assertNotIn("api_key=", lowered)
        self.assertNotIn("private key", lowered)
        self.assertNotIn("bearer ", lowered)

    def test_oss_gate_unchanged_and_not_skill_registry(self) -> None:
        normalized = GATE_PATH.read_bytes().replace(b"\r\n", b"\n")
        digest = hashlib.sha256(normalized).hexdigest().upper()
        self.assertEqual(digest, GATE_SHA256)
        self.assertFalse(OSS_GATE_IS_SKILL_REGISTRY)
        self.assertFalse(AUTO_RUNTIME_REGISTRATION)


if __name__ == "__main__":
    unittest.main()
