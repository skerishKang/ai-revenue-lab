"""Focused contract tests: public-safe integration diagnostics (S3)."""

import json
import unittest

from padiem_embedded_runtime import SidecarContractError
from padiem_embedded_runtime.compatibility import check_contract_compatibility
from padiem_embedded_runtime.diagnostics import (
    DIAGNOSTIC_REASONS,
    REASON_BOOTSTRAP_REJECTED,
    REASON_CONTEXT_MALFORMED,
    REASON_OK,
    REASON_SHELL_DISABLED,
    REASON_VERSION_INCOMPATIBLE,
    STATUS_DEGRADED,
    STATUS_DISABLED,
    STATUS_READY,
    IntegrationDiagnostics,
    build_diagnostics,
)


class DiagnosticsContractTests(unittest.TestCase):
    def test_reason_maps_to_status_deterministically(self):
        compatible = check_contract_compatibility("1.0")
        incompatible = check_contract_compatibility("2.0")
        cases = [
            (REASON_OK, compatible, STATUS_READY),
            (REASON_CONTEXT_MALFORMED, compatible, STATUS_DEGRADED),
            (REASON_VERSION_INCOMPATIBLE, incompatible, STATUS_DISABLED),
            (REASON_BOOTSTRAP_REJECTED, compatible, STATUS_DISABLED),
            (REASON_SHELL_DISABLED, compatible, STATUS_DISABLED),
        ]
        for reason, verdict, expected_status in cases:
            diag = build_diagnostics("diag-host", verdict, reason)
            self.assertEqual(diag.status, expected_status)
            self.assertEqual(diag.reason_code, reason)

    def test_rejects_unclassified_codes(self):
        verdict = check_contract_compatibility("1.0")
        with self.assertRaises(SidecarContractError):
            build_diagnostics("diag-host", verdict, "RAW_TRACEBACK")
        with self.assertRaises(SidecarContractError):
            IntegrationDiagnostics(
                host_id="h",
                status="ready",
                reason_code="engine secret leaked",
                contract_supported=True,
            )

    def test_rejects_bad_bounds_and_types(self):
        with self.assertRaises(SidecarContractError):
            build_diagnostics("diag-host", "not-a-verdict", REASON_OK)
        with self.assertRaises(SidecarContractError):
            build_diagnostics("", check_contract_compatibility("1.0"), REASON_OK)
        with self.assertRaises(SidecarContractError):
            build_diagnostics(
                "h", check_contract_compatibility("1.0"), REASON_OK, dropped_reserved_count=-1
            )

    def test_public_view_carries_only_allowlisted_codes(self):
        diag = build_diagnostics(
            "diag-host", check_contract_compatibility("1.0"), REASON_OK, dropped_reserved_count=2
        )
        public = diag.to_public_dict()
        json.dumps(public)
        self.assertIn(public["status"], {STATUS_READY, STATUS_DEGRADED, STATUS_DISABLED})
        self.assertIn(public["reason_code"], DIAGNOSTIC_REASONS)


if __name__ == "__main__":
    unittest.main()
