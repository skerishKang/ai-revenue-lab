"""B53 install/embed distribution local conformance tests.

Proves the install/bootstrap, site registration, onboarding, and
integration health surfaces are deterministic, repo-local, and require
no real Engine transport or Control Plane authority.
"""

import json
import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "packages" / "padiem-embedded-runtime"))

from app.install_bootstrap import (
    InstallBootstrap,
    parse_install_bootstrap,
    B53_PRODUCT_ID,
    B53_RUNTIME_VERSION,
)
from app.site_registration import (
    SiteRegistration,
    parse_site_registration,
)
from app.onboarding_flow import (
    OnboardingFlow,
    REGISTER,
    CONFIGURE,
    PREVIEW,
    READY_FOR_EXTERNAL_ACTIVATION,
    COMPLETED,
)
from app.integration_health import (
    build_integration_health,
    STATUS_HEALTHY,
    STATUS_DEGRADED,
    REASON_ALL_OK,
    REASON_FAKE_ENGINE_PORT_ONLY,
    REASON_LOCAL_CONFORMANCE_ONLY,
)
from padiem_embedded_runtime.engine_port import DeterministicFakeEnginePort
from padiem_embedded_runtime.errors import SidecarContractError

FIXTURE = json.loads(
    (_APP_ROOT / "fixtures" / "install_conformance.json").read_text(encoding="utf-8")
)


class InstallBootstrapTests(unittest.TestCase):
    def test_versioned_and_public_safe(self):
        bootstrap = parse_install_bootstrap(FIXTURE["install_bootstrap"])
        self.assertEqual(bootstrap.product_id, B53_PRODUCT_ID)
        self.assertEqual(bootstrap.runtime_version, B53_RUNTIME_VERSION)
        public = bootstrap.to_public_dict()
        json.dumps(public)
        self.assertEqual(public["install_mode"], "embed")

    def test_unknown_or_malformed_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            parse_install_bootstrap(FIXTURE["malformed_install_bootstrap"])

    def test_product_id_must_be_b53(self):
        with self.assertRaises(SidecarContractError):
            InstallBootstrap(
                product_id="other-product",
                host_id="h1",
                runtime_version="1.0.0",
                install_mode="embed",
            )

    def test_runtime_version_major_mismatch_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            InstallBootstrap(
                product_id=B53_PRODUCT_ID,
                host_id="h1",
                runtime_version="99.0.0",
                install_mode="embed",
            )

    def test_secret_like_value_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            parse_install_bootstrap(
                {**FIXTURE["install_bootstrap"], "host_name": "secret-token-here"}
            )


class SiteRegistrationTests(unittest.TestCase):
    def test_site_registration_does_not_mint_tenant_truth(self):
        reg = parse_site_registration(FIXTURE["site_registration"])
        public = reg.to_public_dict()
        self.assertNotIn("tenant_id", public)
        self.assertNotIn("account_id", public)
        self.assertNotIn("entitlement", public)
        json.dumps(public)

    def test_caller_asserted_tenant_is_not_authority(self):
        with self.assertRaises(SidecarContractError):
            parse_site_registration(
                {**FIXTURE["site_registration"], "tenant_id": "caller-asserted"}
            )

    def test_malformed_registration_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            parse_site_registration(FIXTURE["malformed_site_registration"])

    def test_adapter_version_must_be_allowlisted(self):
        with self.assertRaises(SidecarContractError):
            SiteRegistration(
                product_id=B53_PRODUCT_ID,
                site_name="test",
                host_origin="https://test.example.com",
                adapter_id="b53-adapter",
                adapter_version="99.0.0",
                environment="dev",
                config_version="1.0.0",
            )


class OnboardingFlowTests(unittest.TestCase):
    def test_happy_path_reaches_local_ready_state(self):
        flow = OnboardingFlow(
            site_name="settlement-dashboard",
            brand="B53",
            theme="dark",
            locale="ko",
            adapter_id="b53-adapter",
            environment="dev",
        )
        self.assertEqual(flow.state, REGISTER)
        flow.configure(brand="B53-Pro", theme="light")
        self.assertEqual(flow.state, CONFIGURE)
        flow.preview()
        self.assertEqual(flow.state, PREVIEW)
        flow.activate()
        self.assertEqual(flow.state, READY_FOR_EXTERNAL_ACTIVATION)

    def test_out_of_order_transition_fails_closed(self):
        flow = OnboardingFlow(
            site_name="test",
            brand="B53",
            theme="dark",
            locale="ko",
            adapter_id="b53-adapter",
            environment="dev",
        )
        with self.assertRaises(SidecarContractError):
            flow.preview()

    def test_brand_theme_roundtrip_is_bounded(self):
        flow = OnboardingFlow(
            site_name="test",
            brand="B53",
            theme="dark",
            locale="ko",
            adapter_id="b53-adapter",
            environment="dev",
        )
        result = flow.configure(brand="B53-Pro", theme="light")
        self.assertEqual(result.brand, "B53-Pro")
        self.assertEqual(result.theme, "light")

    def test_complete_transition(self):
        flow = OnboardingFlow(
            site_name="test",
            brand="B53",
            theme="dark",
            locale="ko",
            adapter_id="b53-adapter",
            environment="dev",
        )
        flow.configure()
        flow.preview()
        flow.activate()
        result = flow.complete()
        self.assertEqual(result.state, COMPLETED)

    def test_invalid_transition_fails_closed(self):
        flow = OnboardingFlow(
            site_name="test",
            brand="B53",
            theme="dark",
            locale="ko",
            adapter_id="b53-adapter",
            environment="dev",
        )
        with self.assertRaises(SidecarContractError):
            flow.activate()


class IntegrationHealthTests(unittest.TestCase):
    def test_reports_local_conformance_truthfully(self):
        health = build_integration_health(
            site_name="settlement-dashboard",
            bootstrap_version="1.0.0",
            adapter_id="b53-adapter",
            environment="dev",
        )
        self.assertEqual(health.status, STATUS_HEALTHY)
        self.assertEqual(health.reason_code, REASON_ALL_OK)
        self.assertTrue(health.local_conformance)
        public = health.to_public_dict()
        json.dumps(public)

    def test_exposes_no_secret_or_machine_binding(self):
        health = build_integration_health(
            site_name="settlement-dashboard",
            bootstrap_version="1.0.0",
            adapter_id="b53-adapter",
            environment="dev",
        )
        public = health.to_public_dict()
        self.assertNotIn("secret", public)
        self.assertNotIn("credential", public)
        self.assertNotIn("token", public)
        self.assertNotIn("binding", public)
        self.assertNotIn("machine_auth", public)

    def test_fake_engine_port_is_sufficient_for_local_conformance(self):
        port = DeterministicFakeEnginePort({"context.project": {"ok": True}})
        response = port.invoke_capability("context.project", {"text": "hi"})
        self.assertEqual(response, {"ok": True})

    def test_real_engine_transport_not_required(self):
        health = build_integration_health(
            site_name="settlement-dashboard",
            bootstrap_version="1.0.0",
            adapter_id="b53-adapter",
            environment="dev",
            fake_engine_port_available=True,
            reason_code=REASON_FAKE_ENGINE_PORT_ONLY,
        )
        self.assertEqual(health.status, STATUS_DEGRADED)
        self.assertEqual(health.reason_code, REASON_FAKE_ENGINE_PORT_ONLY)

    def test_control_plane_not_required_for_local_conformance(self):
        health = build_integration_health(
            site_name="settlement-dashboard",
            bootstrap_version="1.0.0",
            adapter_id="b53-adapter",
            environment="dev",
            local_conformance=True,
            reason_code=REASON_LOCAL_CONFORMANCE_ONLY,
        )
        self.assertTrue(health.local_conformance)
        self.assertEqual(health.reason_code, REASON_LOCAL_CONFORMANCE_ONLY)

    def test_no_real_cdn_domain_package_identity_claim(self):
        health = build_integration_health(
            site_name="settlement-dashboard",
            bootstrap_version="1.0.0",
            adapter_id="b53-adapter",
            environment="dev",
        )
        public = health.to_public_dict()
        self.assertNotIn("cdn_url", public)
        self.assertNotIn("package_registry", public)
        self.assertNotIn("domain", public)

    def test_malformed_health_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            build_integration_health(
                site_name="",
                bootstrap_version="1.0.0",
                adapter_id="b53-adapter",
                environment="dev",
            )


if __name__ == "__main__":
    unittest.main()