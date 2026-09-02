from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.integration_readiness import (
    DEPLOYMENT_APPROVAL_FROM_READINESS,
    FAKE_COUNTS_AS_CONNECTED,
    REAL_CONNECTOR_PROBES_CONFIGURED,
    SECURITY_CERTIFICATION_FROM_READINESS,
    ExternalAdapterKind,
    ExternalAdapterState,
    LiveCapability,
    TrustedAdapterProbe,
    evaluate_live_capability,
)

NOW = datetime(2026, 9, 3, 14, 0, tzinfo=timezone.utc)


def probe(kind, *, state=ExternalAdapterState.CONNECTED, issued_at=None, expires_at=None):
    return TrustedAdapterProbe(
        probe_id=f"probe:{kind.value}",
        adapter_kind=kind,
        state=state,
        issued_at=issued_at or NOW - timedelta(minutes=5),
        expires_at=expires_at or NOW + timedelta(minutes=30),
        authority_ref="trusted:integration-probe",
        evidence_ref=f"evidence:{kind.value}",
    )


def managed_probes(*, fake_kind=None, omitted_kind=None):
    kinds = (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.B14_MODEL_EXECUTION,
        ExternalAdapterKind.SANDBOX_PROVIDER,
        ExternalAdapterKind.GITHUB_REPOSITORY_READ,
    )
    return tuple(
        probe(kind, state=ExternalAdapterState.DETERMINISTIC_FAKE if kind is fake_kind else ExternalAdapterState.CONNECTED)
        for kind in kinds
        if kind is not omitted_kind
    )


class IntegrationReadinessTests(unittest.TestCase):
    def test_managed_cloud_requires_exact_adapter_set(self):
        decision = evaluate_live_capability(probes=managed_probes(), capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW)
        self.assertTrue(decision.live_configured)
        self.assertEqual(decision.missing_or_untrusted_adapters, ())
        missing = evaluate_live_capability(
            probes=managed_probes(omitted_kind=ExternalAdapterKind.SANDBOX_PROVIDER),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            now=NOW,
        )
        self.assertFalse(missing.live_configured)
        self.assertIn(ExternalAdapterKind.SANDBOX_PROVIDER, missing.missing_or_untrusted_adapters)

    def test_fake_unconfigured_stale_and_future_probes_do_not_count(self):
        fake = evaluate_live_capability(
            probes=managed_probes(fake_kind=ExternalAdapterKind.B14_MODEL_EXECUTION),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            now=NOW,
        )
        self.assertFalse(fake.live_configured)
        unconfigured = list(managed_probes())
        unconfigured[0] = probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY, state=ExternalAdapterState.UNCONFIGURED)
        self.assertFalse(evaluate_live_capability(probes=tuple(unconfigured), capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW).live_configured)
        stale = list(managed_probes())
        stale[0] = probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY, issued_at=NOW - timedelta(hours=1), expires_at=NOW)
        self.assertFalse(evaluate_live_capability(probes=tuple(stale), capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW).live_configured)
        future = list(managed_probes())
        future[0] = probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY, issued_at=NOW + timedelta(minutes=1), expires_at=NOW + timedelta(hours=1))
        self.assertFalse(evaluate_live_capability(probes=tuple(future), capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW).live_configured)

    def test_draft_pr_adds_github_write_and_other_capabilities_have_narrow_sets(self):
        draft = managed_probes() + (probe(ExternalAdapterKind.GITHUB_DRAFT_WRITE),)
        self.assertTrue(evaluate_live_capability(probes=draft, capability=LiveCapability.DRAFT_PR_OUTPUT, now=NOW).live_configured)
        messaging = (
            probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY),
            probe(ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT),
            probe(ExternalAdapterKind.COMMUNICATION_OUTBOUND),
        )
        self.assertTrue(evaluate_live_capability(probes=messaging, capability=LiveCapability.BUSINESS_MESSAGING, now=NOW).live_configured)
        finance = (
            probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY),
            probe(ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT),
            probe(ExternalAdapterKind.ACCOUNTING_READ),
        )
        self.assertTrue(evaluate_live_capability(probes=finance, capability=LiveCapability.FINANCE_PROJECTION_LIVE_READ, now=NOW).live_configured)

    def test_duplicate_probe_kind_and_secret_like_refs_fail_closed(self):
        duplicate = managed_probes() + (probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY),)
        with self.assertRaises(ContractError):
            evaluate_live_capability(probes=duplicate, capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW)
        with self.assertRaises(ContractError):
            TrustedAdapterProbe(
                probe_id="token=should-not-be-here",
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=ExternalAdapterState.CONNECTED,
                issued_at=NOW,
                expires_at=NOW + timedelta(minutes=1),
                authority_ref="trusted:probe",
                evidence_ref="evidence:probe",
            )

    def test_readiness_is_not_security_certification_or_deploy_approval(self):
        self.assertFalse(FAKE_COUNTS_AS_CONNECTED)
        self.assertFalse(SECURITY_CERTIFICATION_FROM_READINESS)
        self.assertFalse(DEPLOYMENT_APPROVAL_FROM_READINESS)
        self.assertFalse(REAL_CONNECTOR_PROBES_CONFIGURED)
        safe = evaluate_live_capability(probes=managed_probes(), capability=LiveCapability.MANAGED_CLOUD_RUN, now=NOW).safe_dict()
        self.assertFalse(safe["fake_counts_as_connected"])
        self.assertFalse(safe["security_certification"])
        self.assertFalse(safe["deployment_approval"])


if __name__ == "__main__":
    unittest.main()
