from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.sandbox_conformance import IsolationPrimitive
from kagent.sandbox_provider_evidence import (
    PROVIDER_SELECTION_FROM_EVIDENCE_PACK_SUPPORTED,
    REAL_PROVIDER_EVIDENCE_COLLECTION_CONFIGURED,
    ProviderControlEvidence,
    SandboxProviderEvidencePack,
    capability_control_names,
)


def evidence_rows(*, missing=None, false_control=None):
    rows = []
    for name in capability_control_names():
        if name == missing:
            continue
        rows.append(ProviderControlEvidence(name, name != false_control, f"evidence:{name}"))
    return tuple(rows)


class SandboxProviderEvidenceTests(unittest.TestCase):
    def test_complete_fixture_maps_every_boolean_into_existing_gate(self):
        pack = SandboxProviderEvidencePack("candidate_fixture", IsolationPrimitive.MICROVM, controls=evidence_rows())
        capabilities = pack.to_capabilities()
        self.assertEqual(capabilities.provider_id, "candidate_fixture")
        self.assertTrue(all(getattr(capabilities, name) for name in capability_control_names()))
        assessment = pack.assess()
        self.assertEqual(assessment.missing_controls, ())
        safe = pack.safe_dict()
        self.assertTrue(safe["full_control_coverage"])
        self.assertFalse(safe["provider_selected"])
        self.assertFalse(safe["production_ready_claim"])

    def test_false_observation_is_preserved_for_existing_gate_result(self):
        name = capability_control_names()[0]
        pack = SandboxProviderEvidencePack("candidate_fixture", IsolationPrimitive.CONTAINER, controls=evidence_rows(false_control=name))
        self.assertFalse(getattr(pack.to_capabilities(), name))
        self.assertIn(name, pack.assess().missing_controls)

    def test_missing_duplicate_and_unknown_controls_fail_closed(self):
        missing = capability_control_names()[0]
        with self.assertRaises(ContractError):
            SandboxProviderEvidencePack("candidate_fixture", IsolationPrimitive.VM, controls=evidence_rows(missing=missing))
        full = evidence_rows()
        with self.assertRaises(ContractError):
            SandboxProviderEvidencePack("candidate_fixture", IsolationPrimitive.VM, controls=full + (full[0],))
        with self.assertRaises(ContractError):
            ProviderControlEvidence("invented_control", True, "evidence:invented")

    def test_evidence_refs_reject_credential_material(self):
        with self.assertRaises(ContractError):
            ProviderControlEvidence(capability_control_names()[0], True, "token=should_not_be_here")

    def test_pack_does_not_choose_vendor_or_call_external_service(self):
        self.assertFalse(PROVIDER_SELECTION_FROM_EVIDENCE_PACK_SUPPORTED)
        self.assertFalse(REAL_PROVIDER_EVIDENCE_COLLECTION_CONFIGURED)


if __name__ == "__main__":
    unittest.main()
