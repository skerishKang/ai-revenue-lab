"""Focused contract tests: Engine port abstraction + deterministic fake (S2)."""

import unittest

from padiem_embedded_runtime import (
    DeterministicFakeEnginePort,
    EnginePort,
    SidecarContractError,
)


class EnginePortTests(unittest.TestCase):
    def test_interface_has_no_transport(self):
        with self.assertRaises((NotImplementedError, TypeError)):
            EnginePort().invoke_capability("notice.render", {})

    def test_fake_is_deterministic_and_bounded(self):
        port = DeterministicFakeEnginePort({"notice.render": {"ok": True}})
        first = port.invoke_capability("notice.render", {"host_id": "h"})
        second = port.invoke_capability("notice.render", {"host_id": "h"})
        self.assertEqual(first, second)
        self.assertEqual(len(port.calls), 2)
        first["ok"] = "mutated"
        self.assertEqual(port.invoke_capability("notice.render", {})["ok"], True)

    def test_fake_rejects_unreviewed_capabilities(self):
        with self.assertRaises(SidecarContractError):
            DeterministicFakeEnginePort({"provider.call": {}})
        port = DeterministicFakeEnginePort({})
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("provider.call", {})


if __name__ == "__main__":
    unittest.main()
