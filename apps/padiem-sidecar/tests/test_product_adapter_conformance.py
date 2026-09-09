"""B53 product-adapter conformance tests.

Proves the ownership boundary: every adapter surface delegates to the
IP-SIDECAR primitive (identical projection for identical input) and B53
carries no duplicated validation/state/authority.
"""

import json
import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "packages" / "padiem-embedded-runtime"))

from app.product_adapter import (  # noqa: E402
    ProductAdapter,
    SidecarProductConfig,
    StubControlPlaneContextPort,
)
from padiem_embedded_runtime.approval_presentation import (  # noqa: E402
    present_approval_proposals,
    present_approval_state,
    present_confirmation_intent,
)
from padiem_embedded_runtime.attachment_input import (  # noqa: E402
    present_attachment_ref,
    present_selections,
)
from padiem_embedded_runtime.bootstrap import BootstrapConfig  # noqa: E402
from padiem_embedded_runtime.bridge import intake_host_payload  # noqa: E402
from padiem_embedded_runtime.engine_port import DeterministicFakeEnginePort  # noqa: E402
from padiem_embedded_runtime.errors import SidecarContractError  # noqa: E402
from padiem_embedded_runtime.evidence import present_citations  # noqa: E402
from padiem_embedded_runtime.lifecycle import EmbeddedShell  # noqa: E402
from padiem_embedded_runtime.streaming_lifecycle import (  # noqa: E402
    present_public_error,
    present_retry_affordance,
    present_stream_lifecycle,
)

FIXTURE = json.loads(
    (_APP_ROOT / "fixtures" / "local_conformance.json").read_text(encoding="utf-8")
)


def make_config() -> SidecarProductConfig:
    return SidecarProductConfig(
        product_id="padiem-sidecar",
        product_name="Padiem Sidecar",
        install_mode="embed",
        theme="dark",
        brand="B53",
        locale="ko",
    )


class ProductConfigBoundaryTests(unittest.TestCase):
    def test_bounded_product_metadata_accepted(self):
        config = make_config()
        public = config.to_public_dict()
        self.assertEqual(public["product_id"], "padiem-sidecar")
        json.dumps(public)

    def test_foreign_product_id_rejected(self):
        with self.assertRaises(SidecarContractError):
            SidecarProductConfig("other-product", "X", "embed", "dark", "B53")

    def test_unallowlisted_install_mode_rejected(self):
        with self.assertRaises(SidecarContractError):
            SidecarProductConfig("padiem-sidecar", "X", "daemon", "dark", "B53")

    def test_overlong_theme_and_brand_rejected(self):
        with self.assertRaises(SidecarContractError):
            SidecarProductConfig("padiem-sidecar", "X", "embed", "t" * 33, "B53")
        with self.assertRaises(SidecarContractError):
            SidecarProductConfig("padiem-sidecar", "X", "embed", "dark", "b" * 65)


class AdapterDelegationTests(unittest.TestCase):
    """Adapter output must be byte-identical to the direct IP-SIDECAR primitive."""

    def setUp(self):
        self.adapter = ProductAdapter(make_config())

    def test_intake_delegates_to_bridge(self):
        direct = intake_host_payload(
            FIXTURE["bootstrap"],
            FIXTURE["context_valid"],
            EmbeddedShell(
                BootstrapConfig(host_id="b53-host", shell_version="1.0.0", locale="ko")
            ),
        )
        delegated = self.adapter.intake(
            FIXTURE["bootstrap"], FIXTURE["context_valid"]
        )
        self.assertEqual(direct.to_public_dict(), delegated.to_public_dict())

    def test_stream_lifecycle_delegates(self):
        for event in FIXTURE["streaming_flow"]:
            self.assertEqual(
                self.adapter.stream_event(event).to_public_dict(),
                present_stream_lifecycle(event).to_public_dict(),
            )
        malformed = FIXTURE["streaming_malformed"]
        self.assertEqual(
            self.adapter.stream_event(malformed).to_public_dict(),
            present_stream_lifecycle(malformed).to_public_dict(),
        )
        self.assertTrue(self.adapter.stream_event(malformed).degraded)

    def test_error_and_affordance_delegate(self):
        for item in FIXTURE["error_flow"]:
            self.assertEqual(
                self.adapter.public_error(item).to_public_dict(),
                present_public_error(item).to_public_dict(),
            )
        for item in FIXTURE["affordance_flow"]:
            self.assertEqual(
                self.adapter.retry_affordance(item).to_public_dict(),
                present_retry_affordance(item).to_public_dict(),
            )

    def test_evidence_and_attachment_delegate(self):
        for key in ("citations_normal", "citations_degraded"):
            self.assertEqual(
                self.adapter.citations(FIXTURE[key]).to_public_dict(),
                present_citations(FIXTURE[key]).to_public_dict(),
            )
        for key in ("selections_normal", "selections_degraded"):
            self.assertEqual(
                self.adapter.selections(FIXTURE[key]).to_public_dict(),
                present_selections(FIXTURE[key]).to_public_dict(),
            )
        for key in ("attachment_ref_valid", "attachment_ref_invalid"):
            self.assertEqual(
                self.adapter.attachment_ref(FIXTURE[key]).to_public_dict(),
                present_attachment_ref(FIXTURE[key]).to_public_dict(),
            )

    def test_approval_delegate(self):
        self.assertEqual(
            self.adapter.approval_proposals(
                FIXTURE["approval_proposals_normal"]
            ).to_public_dict(),
            present_approval_proposals(FIXTURE["approval_proposals_normal"]).to_public_dict(),
        )
        for item in FIXTURE["approval_intent_flow"]:
            self.assertEqual(
                self.adapter.confirmation_intent(item).to_public_dict(),
                present_confirmation_intent(item).to_public_dict(),
            )
        for item in FIXTURE["approval_state_flow"]:
            self.assertEqual(
                self.adapter.approval_state(item).to_public_dict(),
                present_approval_state(item).to_public_dict(),
            )


class HandoffPortTests(unittest.TestCase):
    def test_engine_port_is_deterministic_fake_only(self):
        adapter = ProductAdapter(make_config())
        self.assertIsInstance(adapter.engine_port, DeterministicFakeEnginePort)
        response = adapter.engine_port.invoke_capability("notice.render", {"text": "hi"})
        self.assertEqual(response, {"ok": True})
        with self.assertRaises(SidecarContractError):
            adapter.engine_port.invoke_capability("engine.transport", {})

    def test_control_plane_stub_carries_no_authority(self):
        adapter = ProductAdapter(
            make_config(),
            control_plane_port=StubControlPlaneContextPort({"workspace": "settlement"}),
        )
        view = adapter.control_plane_context()
        self.assertEqual(view["status"], "stub")
        self.assertIs(view["tenant_authority"], False)
        self.assertIs(view["transport"], False)
        json.dumps(view)

    def test_control_plane_stub_rejects_non_text_and_oversize(self):
        with self.assertRaises(SidecarContractError):
            StubControlPlaneContextPort({"n": 3})
        with self.assertRaises(SidecarContractError):
            StubControlPlaneContextPort({"k": {"nested": True}})
        with self.assertRaises(SidecarContractError):
            StubControlPlaneContextPort({f"k{i}": "v" for i in range(9)})


class NoAuthorityDuplicationTests(unittest.TestCase):
    def test_reserved_authority_keys_never_promoted(self):
        adapter = ProductAdapter(make_config())
        outcome = adapter.intake(FIXTURE["bootstrap"], FIXTURE["context_valid"])
        projection = outcome.to_public_dict()["projection"]
        self.assertEqual(projection["trust_level"], "untrusted")
        self.assertNotIn("tenant_id", projection["context_fields"])
        self.assertNotIn("role", projection["context_fields"])
        self.assertEqual(sorted(projection["dropped_reserved"]), ["role", "tenant_id"])

    def test_adapter_exposes_no_authority_surface(self):
        adapter = ProductAdapter(make_config())
        public_names = {name for name in dir(adapter) if not name.startswith("_")}
        self.assertFalse(
            any(
                marker in name
                for name in public_names
                for marker in ("tenant", "grant", "token", "mint", "credential", "secret")
            ),
            public_names,
        )

    def test_disable_is_host_safe_from_any_state(self):
        adapter = ProductAdapter(make_config())
        result = adapter.disable("conformance complete")
        self.assertTrue(result.ok)
        self.assertEqual(adapter.shell.state, "disabled")
        again = adapter.disable("again")
        self.assertTrue(again.ok)


if __name__ == "__main__":
    unittest.main()
