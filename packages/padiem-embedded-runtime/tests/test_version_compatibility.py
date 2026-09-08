"""Focused contract tests: runtime/host version compatibility (S3)."""

import json
import unittest

from padiem_embedded_runtime.compatibility import (
    REASON_COMPATIBLE,
    REASON_MALFORMED_VERSION,
    REASON_MISSING_VERSION,
    REASON_UNSUPPORTED_MAJOR,
    RUNTIME_CONTRACT_VERSION,
    check_contract_compatibility,
)


class VersionCompatibilityTests(unittest.TestCase):
    def test_current_major_is_supported(self):
        verdict = check_contract_compatibility("1.0")
        self.assertTrue(verdict.supported)
        self.assertEqual(verdict.reason_code, REASON_COMPATIBLE)
        self.assertEqual(verdict.runtime_version, RUNTIME_CONTRACT_VERSION)

    def test_newer_minor_of_supported_major_is_compatible(self):
        verdict = check_contract_compatibility("1.7")
        self.assertTrue(verdict.supported)

    def test_unsupported_major_is_deterministic_no_raise(self):
        verdict = check_contract_compatibility("2.0")
        self.assertFalse(verdict.supported)
        self.assertEqual(verdict.reason_code, REASON_UNSUPPORTED_MAJOR)

    def test_malformed_input_never_raises(self):
        for bad in ["", "x", "1", "1.0.0", "v1.0", "1.0 ", 7, None, ["1.0"]]:
            verdict = check_contract_compatibility(bad)
            self.assertFalse(verdict.supported)
            if bad is None:
                self.assertEqual(verdict.reason_code, REASON_MISSING_VERSION)
            else:
                self.assertEqual(verdict.reason_code, REASON_MALFORMED_VERSION)

    def test_wellformed_high_major_is_unsupported_not_malformed(self):
        verdict = check_contract_compatibility("999999.0")
        self.assertFalse(verdict.supported)
        self.assertEqual(verdict.reason_code, REASON_UNSUPPORTED_MAJOR)

    def test_public_view_is_bounded_and_json_safe(self):
        verdict = check_contract_compatibility("y" * 500)
        self.assertLessEqual(len(verdict.host_version), 32)
        json.dumps(verdict.to_public_dict())

    def test_verdict_is_immutable(self):
        verdict = check_contract_compatibility("1.0")
        with self.assertRaises(Exception):
            verdict.supported = False  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
