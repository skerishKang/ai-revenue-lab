from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from kagent.contracts import ContractError
from kagent.integration_readiness import (
    ExternalAdapterKind,
    ExternalAdapterState,
    LiveCapability,
    TrustedAdapterProbe,
)
from kagent.managed_live_preflight import (
    DEPLOYMENT_APPROVAL_FROM_PREFLIGHT,
    PRODUCTION_READINESS_REQUIRES_SCOPED_PROBES,
    SECURITY_CERTIFICATION_FROM_PREFLIGHT,
    TrustedScopedAdapterProbe,
    evaluate_managed_live_preflight,
)
from kagent.managed_onboarding import (
    ManagedClawOnboardingService,
    TrustedAccountSessionProjection,
    TrustedWorkspaceEntitlementProjection,
)


NOW = datetime(2026, 9, 3, 15, 0, tzinfo=timezone.utc)
PROD_ENV = "env:production"
PROD_DEPLOYMENT = "deployment:claw-prod"
STAGING_ENV = "env:staging"


def trusted_session(*, account_ref="account:1", expires_at=None):
    return TrustedAccountSessionProjection(
        session_ref="session:1",
        account_ref=account_ref,
        issued_at=NOW - timedelta(minutes=10),
        expires_at=expires_at or NOW + timedelta(minutes=30),
        authority_ref="control-plane:identity",
    )


def trusted_entitlement(*, account_ref="account:1", workspace_id="workspace:1", expires_at=None):
    return TrustedWorkspaceEntitlementProjection(
        entitlement_ref="entitlement:1",
        account_ref=account_ref,
        workspace_id=workspace_id,
        org_ref="org:1",
        managed_cloud_allowed=True,
        issued_at=NOW - timedelta(minutes=10),
        expires_at=expires_at or NOW + timedelta(minutes=30),
        authority_ref="control-plane:entitlement",
    )


def managed_onboarding(*, session=None, entitlement=None):
    return ManagedClawOnboardingService().build(
        session=session or trusted_session(),
        entitlement=entitlement or trusted_entitlement(),
        now=NOW,
    )


def scoped_probe(
    kind: ExternalAdapterKind,
    *,
    environment_ref=PROD_ENV,
    deployment_ref=PROD_DEPLOYMENT,
    state=ExternalAdapterState.CONNECTED,
):
    probe = TrustedAdapterProbe(
        probe_id=f"probe:{kind.value}:{environment_ref.split(':')[-1]}",
        adapter_kind=kind,
        state=state,
        issued_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(minutes=15),
        authority_ref="trusted:adapter-probe",
        evidence_ref=f"evidence:{kind.value}",
    )
    return TrustedScopedAdapterProbe(
        probe=probe,
        environment_ref=environment_ref,
        deployment_ref=deployment_ref,
        scope_authority_ref="trusted:deployment-controller",
        scope_evidence_ref=f"scope-evidence:{kind.value}",
    )


def managed_cloud_probes(**overrides):
    kinds = (
        ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
        ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
        ExternalAdapterKind.B14_MODEL_EXECUTION,
        ExternalAdapterKind.SANDBOX_PROVIDER,
        ExternalAdapterKind.GITHUB_REPOSITORY_READ,
    )
    return tuple(scoped_probe(kind, **overrides) for kind in kinds)


class ManagedLivePreflightTests(unittest.TestCase):
    def test_exact_production_scope_can_become_live_ready(self):
        session = trusted_session()
        entitlement = trusted_entitlement()
        decision = evaluate_managed_live_preflight(
            onboarding=managed_onboarding(session=session, entitlement=entitlement),
            session=session,
            entitlement=entitlement,
            scoped_probes=managed_cloud_probes(),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            environment_ref=PROD_ENV,
            deployment_ref=PROD_DEPLOYMENT,
            now=NOW,
        )
        self.assertTrue(decision.live_ready)
        self.assertEqual(decision.readiness.missing_or_untrusted_adapters, ())
        self.assertEqual(len(decision.scoped_probe_ids), 5)

    def test_staging_probe_set_cannot_satisfy_production_preflight(self):
        session = trusted_session()
        entitlement = trusted_entitlement()
        decision = evaluate_managed_live_preflight(
            onboarding=managed_onboarding(session=session, entitlement=entitlement),
            session=session,
            entitlement=entitlement,
            scoped_probes=managed_cloud_probes(environment_ref=STAGING_ENV),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            environment_ref=PROD_ENV,
            deployment_ref=PROD_DEPLOYMENT,
            now=NOW,
        )
        self.assertFalse(decision.live_ready)
        self.assertEqual(len(decision.readiness.missing_or_untrusted_adapters), 5)
        self.assertEqual(decision.scoped_probe_ids, ())

    def test_one_wrong_scope_adapter_remains_missing(self):
        probes = list(managed_cloud_probes())
        probes = [
            scoped_probe(item.probe.adapter_kind, environment_ref=STAGING_ENV)
            if item.probe.adapter_kind is ExternalAdapterKind.SANDBOX_PROVIDER
            else item
            for item in probes
        ]
        session = trusted_session()
        entitlement = trusted_entitlement()
        decision = evaluate_managed_live_preflight(
            onboarding=managed_onboarding(session=session, entitlement=entitlement),
            session=session,
            entitlement=entitlement,
            scoped_probes=tuple(probes),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            environment_ref=PROD_ENV,
            deployment_ref=PROD_DEPLOYMENT,
            now=NOW,
        )
        self.assertFalse(decision.live_ready)
        self.assertEqual(
            decision.readiness.missing_or_untrusted_adapters,
            (ExternalAdapterKind.SANDBOX_PROVIDER,),
        )

    def test_fake_probe_stays_fail_closed_inside_exact_scope(self):
        probes = tuple(
            scoped_probe(
                kind,
                state=(
                    ExternalAdapterState.DETERMINISTIC_FAKE
                    if kind is ExternalAdapterKind.B14_MODEL_EXECUTION
                    else ExternalAdapterState.CONNECTED
                ),
            )
            for kind in (
                ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
                ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
                ExternalAdapterKind.B14_MODEL_EXECUTION,
                ExternalAdapterKind.SANDBOX_PROVIDER,
                ExternalAdapterKind.GITHUB_REPOSITORY_READ,
            )
        )
        session = trusted_session()
        entitlement = trusted_entitlement()
        decision = evaluate_managed_live_preflight(
            onboarding=managed_onboarding(session=session, entitlement=entitlement),
            session=session,
            entitlement=entitlement,
            scoped_probes=probes,
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            environment_ref=PROD_ENV,
            deployment_ref=PROD_DEPLOYMENT,
            now=NOW,
        )
        self.assertFalse(decision.live_ready)
        self.assertIn(
            ExternalAdapterKind.B14_MODEL_EXECUTION,
            decision.readiness.missing_or_untrusted_adapters,
        )

    def test_session_and_entitlement_are_rechecked_at_preflight_time(self):
        expired_session = trusted_session(expires_at=NOW)
        entitlement = trusted_entitlement()
        onboarding = ManagedClawOnboardingService().build(
            session=TrustedAccountSessionProjection(
                session_ref="session:1",
                account_ref="account:1",
                issued_at=NOW - timedelta(minutes=10),
                expires_at=NOW + timedelta(minutes=1),
                authority_ref="control-plane:identity",
            ),
            entitlement=entitlement,
            now=NOW - timedelta(seconds=1),
        )
        with self.assertRaisesRegex(ContractError, "session.*not currently active"):
            evaluate_managed_live_preflight(
                onboarding=onboarding,
                session=expired_session,
                entitlement=entitlement,
                scoped_probes=managed_cloud_probes(),
                capability=LiveCapability.MANAGED_CLOUD_RUN,
                environment_ref=PROD_ENV,
                deployment_ref=PROD_DEPLOYMENT,
                now=NOW,
            )

        session = trusted_session()
        expired_entitlement = trusted_entitlement(expires_at=NOW)
        with self.assertRaisesRegex(ContractError, "entitlement.*not currently active"):
            evaluate_managed_live_preflight(
                onboarding=managed_onboarding(session=session, entitlement=trusted_entitlement()),
                session=session,
                entitlement=expired_entitlement,
                scoped_probes=managed_cloud_probes(),
                capability=LiveCapability.MANAGED_CLOUD_RUN,
                environment_ref=PROD_ENV,
                deployment_ref=PROD_DEPLOYMENT,
                now=NOW,
            )

    def test_onboarding_correlation_drift_fails_closed(self):
        original_session = trusted_session()
        original_entitlement = trusted_entitlement()
        onboarding = managed_onboarding(
            session=original_session,
            entitlement=original_entitlement,
        )
        changed_session = TrustedAccountSessionProjection(
            session_ref="session:2",
            account_ref="account:1",
            issued_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=30),
            authority_ref="control-plane:identity",
        )
        with self.assertRaisesRegex(ContractError, "onboarding session correlation mismatch"):
            evaluate_managed_live_preflight(
                onboarding=onboarding,
                session=changed_session,
                entitlement=original_entitlement,
                scoped_probes=managed_cloud_probes(),
                capability=LiveCapability.MANAGED_CLOUD_RUN,
                environment_ref=PROD_ENV,
                deployment_ref=PROD_DEPLOYMENT,
                now=NOW,
            )

    def test_safe_projection_is_not_deployment_approval_or_security_certification(self):
        session = trusted_session()
        entitlement = trusted_entitlement()
        safe = evaluate_managed_live_preflight(
            onboarding=managed_onboarding(session=session, entitlement=entitlement),
            session=session,
            entitlement=entitlement,
            scoped_probes=managed_cloud_probes(),
            capability=LiveCapability.MANAGED_CLOUD_RUN,
            environment_ref=PROD_ENV,
            deployment_ref=PROD_DEPLOYMENT,
            now=NOW,
        ).safe_dict()
        self.assertTrue(PRODUCTION_READINESS_REQUIRES_SCOPED_PROBES)
        self.assertFalse(SECURITY_CERTIFICATION_FROM_PREFLIGHT)
        self.assertFalse(DEPLOYMENT_APPROVAL_FROM_PREFLIGHT)
        self.assertTrue(safe["environment_scoped"])
        self.assertFalse(safe["security_certification"])
        self.assertFalse(safe["deployment_approval"])
        self.assertIsNone(safe["endpoint"])
        self.assertIsNone(safe["credential"])


if __name__ == "__main__":
    unittest.main()
