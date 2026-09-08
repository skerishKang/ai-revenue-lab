"""Focused contract tests: host-context boundary (S2)."""

import unittest

from padiem_embedded_runtime import SidecarContractError, envelop_host_context


class HostContextBoundaryTests(unittest.TestCase):
    def test_untrusted_by_default_and_authority_dropped(self):
        envelope = envelop_host_context(
            "ctx-host-01",
            {"theme": "dark", "role": "admin", "tenant_id": "t-9", "surface": "panel"},
        )
        self.assertEqual(envelope.trust_level, "untrusted")
        self.assertEqual(envelope.sanitized_view(), {"theme": "dark", "surface": "panel"})
        self.assertEqual(set(envelope.dropped_reserved), {"role", "tenant_id"})
        public = envelope.to_public_dict()
        self.assertNotIn("admin", str(public))
        self.assertNotIn("t-9", str(public))
        self.assertEqual(public["dropped_reserved_count"], 2)

    def test_rejects_non_text_and_oversize(self):
        with self.assertRaises(SidecarContractError):
            envelop_host_context("h", {"count": 3})
        with self.assertRaises(SidecarContractError):
            envelop_host_context("h", {"k": "x" * 513})
        with self.assertRaises(SidecarContractError):
            envelop_host_context("h", {f"k{i}": "v" for i in range(17)})
        with self.assertRaises(SidecarContractError):
            envelop_host_context("h", ["not-a-mapping"])


if __name__ == "__main__":
    unittest.main()
