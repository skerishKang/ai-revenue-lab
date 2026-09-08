from __future__ import annotations

from pathlib import Path
import unittest


class ConnectionsCenterSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (Path(__file__).resolve().parents[1] / "site" / "connections.html").read_text(encoding="utf-8")

    def test_static_reference_is_explicitly_non_live_and_non_authoritative(self):
        self.assertIn("data-real-backend-wired=\"false\"", self.html)
        self.assertIn("data-ui-action-authority=\"false\"", self.html)
        self.assertIn("data-secret-value-visible=\"false\"", self.html)
        self.assertIn("SYNTHETIC STATIC REFERENCE", self.html)
        self.assertIn("실제 계정/장치 백엔드에 연결되지 않았습니다", self.html)

    def test_required_connector_states_and_scope_visibility_exist(self):
        self.assertIn("data-status=\"connected\"", self.html)
        self.assertIn("data-status=\"action_required\"", self.html)
        self.assertIn("READ + WRITE", self.html)
        self.assertIn("Scopes", self.html)
        self.assertIn("Last probe", self.html)
        self.assertIn("Last material action", self.html)
        self.assertIn("data-shared-account-warning", self.html)

    def test_local_device_roots_capabilities_and_actions_are_visible(self):
        self.assertIn("data-device-card", self.html)
        self.assertGreaterEqual(self.html.count("data-local-root"), 2)
        self.assertIn("filesystem.read · ALLOW", self.html)
        self.assertIn("filesystem.write · ASK", self.html)
        self.assertIn("git.network · DENY", self.html)
        self.assertIn("Disable", self.html)
        self.assertIn("Revoke", self.html)
        self.assertIn("Delete", self.html)

    def test_escalation_shows_current_requested_delta_and_cannot_apply_silently(self):
        self.assertIn("data-escalation-review", self.html)
        self.assertIn("data-widens-capability=\"true\"", self.html)
        self.assertIn("data-approval-required=\"true\"", self.html)
        self.assertIn("data-trusted-approval-present=\"false\"", self.html)
        self.assertIn("CURRENT SCOPE", self.html)
        self.assertIn("REQUESTED SCOPE", self.html)
        self.assertIn("+ files.update", self.html)
        self.assertIn("Silent widening", self.html)
        self.assertIn("PROHIBITED", self.html)

    def test_revocation_is_presented_in_one_place_and_actions_are_disabled(self):
        self.assertIn("data-revocation-center", self.html)
        self.assertGreaterEqual(self.html.count("disabled>"), 10)
        self.assertIn("연결·장치 해지", self.html)

    def test_no_external_runtime_assets_or_forms(self):
        lowered = self.html.lower()
        self.assertNotIn("<script src=", lowered)
        self.assertNotIn("<link rel=\"stylesheet\"", lowered)
        self.assertNotIn("<form", lowered)
        self.assertNotIn("type=\"password\"", lowered)


if __name__ == "__main__":
    unittest.main()
