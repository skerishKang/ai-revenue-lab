"""#5485 — the connection route that carries the device to the standby.

The controller owns the claim. The route owns the device. These tests pin the
part that is easy to get wrong: **a route is not a permission**. The device
has to arrive before a target may execute, in both directions.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kagent.contracts import ContractError
from kagent.local_agent_mesh_connection_route import (
    DEFAULT_AGENT_URL,
    EVENT_ROUTE_TO_COM2,
    EVENT_ROUTE_TO_ORACLE,
    TARGET_COM2,
    TARGET_ORACLE,
    ConnectionRoute,
    MeshConnectionRouter,
    com2_route,
    oracle_route,
)

COM2 = com2_route(
    tunnel_host="192.168.0.101",
    tunnel_user="user",
    tunnel_key="C:/Users/limone/.ssh/id_rsa",
)
ORACLE = oracle_route(
    tunnel_host="168.138.200.12",
    tunnel_user="ubuntu",
    tunnel_key="C:/Users/limone/.ssh-oracle-only/id_oracle",
)


class ConnectionRouteTests(unittest.TestCase):
    """The route description and the forward it produces."""

    def test_both_routes_use_the_same_local_address(self):
        self.assertEqual(COM2.local_host, ORACLE.local_host)
        self.assertEqual(COM2.local_port, ORACLE.local_port)
        self.assertEqual(COM2.agent_url, ORACLE.agent_url)
        self.assertEqual(COM2.agent_url, DEFAULT_AGENT_URL)

    def test_the_routes_differ_only_in_their_destination(self):
        self.assertNotEqual(COM2.identity(), ORACLE.identity())
        self.assertEqual(COM2.tunnel_host, "192.168.0.101")
        self.assertEqual(ORACLE.tunnel_host, "168.138.200.12")

    def test_the_forward_arguments_carry_the_destination_and_the_key(self):
        arguments = ORACLE.tunnel_arguments()
        forward = arguments[arguments.index("-L") + 1]
        self.assertEqual(forward, "127.0.0.1:4443:127.0.0.1:443")
        self.assertIn("ubuntu@168.138.200.12", arguments)
        self.assertIn("C:/Users/limone/.ssh-oracle-only/id_oracle", arguments)
        # The forward never carries a password.
        self.assertNotIn("pass", " ".join(arguments).lower())

    def test_a_route_rejects_nonsense(self):
        with self.assertRaises(ContractError):
            ConnectionRoute(
                target="nowhere",
                tunnel_host="h",
                tunnel_port=443,
                tunnel_user="u",
                tunnel_key="k",
            )
        with self.assertRaises(ContractError):
            com2_route(tunnel_host="", tunnel_user="u", tunnel_key="k")
        with self.assertRaises(ContractError):
            oracle_route(tunnel_host="h", tunnel_user="u", tunnel_key="k", tunnel_port=0)


class MeshConnectionRouterTests(unittest.TestCase):
    """The route and claim decisions."""

    def _router(self, initial: str = TARGET_COM2) -> MeshConnectionRouter:
        return MeshConnectionRouter(com2=COM2, oracle=ORACLE, initial_target=initial)

    def test_while_com2_is_healthy_the_route_stays_on_com2(self):
        router = self._router()
        decision = router.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
        )
        self.assertEqual(decision.route_target, TARGET_COM2)
        self.assertFalse(decision.route_changed)
        self.assertEqual(decision.route_events, ())
        self.assertEqual(decision.claim_target, TARGET_COM2)

    def test_a_com2_fault_moves_the_route_to_oracle(self):
        router = self._router()
        decision = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
        )
        self.assertEqual(decision.route_target, TARGET_ORACLE)
        self.assertTrue(decision.route_changed)
        self.assertEqual(decision.route_events, (EVENT_ROUTE_TO_ORACLE,))

    def test_a_route_is_not_a_permission(self):
        """Nobody may execute while the device is in neither place."""
        router = self._router()
        decision = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
        )
        self.assertEqual(decision.route_target, TARGET_ORACLE)
        self.assertIsNone(decision.claim_target)
        self.assertFalse(decision.claim_allowed())
        self.assertIn("not connected anywhere yet", decision.claim_blocked_reason)

    def test_oracle_takes_the_claim_once_the_device_arrives(self):
        router = self._router()
        travelling = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
        )
        self.assertIsNone(travelling.claim_target)
        arrived = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        self.assertEqual(arrived.claim_target, TARGET_ORACLE)
        self.assertTrue(arrived.claim_allowed())
        # The device arriving is not a route change: the route was already
        # pointing there, the device is now following it.
        self.assertFalse(arrived.route_changed)
        self.assertEqual(arrived.route_events, ())

    def test_a_recovery_signal_alone_does_not_return_the_claim(self):
        """COM2 says it is back, but the device has not travelled back yet."""
        router = self._router()
        router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        # The route comes back on the signal.
        restored = router.evaluate(
            com2_restored=True,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        self.assertEqual(restored.route_target, TARGET_COM2)
        self.assertEqual(restored.route_events, (EVENT_ROUTE_TO_COM2,))
        # But the device is still at Oracle, so Oracle keeps the claim.
        self.assertEqual(restored.claim_target, TARGET_ORACLE)
        self.assertIn("still at the other server", restored.claim_blocked_reason)

    def test_the_claim_returns_once_com2_has_the_device_back(self):
        router = self._router()
        router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        waiting = router.evaluate(
            com2_restored=True,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        self.assertEqual(waiting.claim_target, TARGET_ORACLE)
        back = router.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
        )
        self.assertEqual(back.claim_target, TARGET_COM2)
        self.assertTrue(back.claim_allowed())
        self.assertEqual(back.route_events, ())

    def test_the_route_event_fires_once_per_switch(self):
        router = self._router()
        first = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
        )
        self.assertEqual(first.route_events, (EVENT_ROUTE_TO_ORACLE,))
        second = router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=False,
        )
        self.assertEqual(second.route_events, ())
        third = router.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
        )
        self.assertEqual(third.route_events, (EVENT_ROUTE_TO_COM2,))
        fourth = router.evaluate(
            com2_restored=True,
            com2_device_connected=True,
            oracle_device_connected=False,
        )
        self.assertEqual(fourth.route_events, ())

    def test_oracle_keeps_the_claim_while_com2_stays_down(self):
        """Oracle has to keep serving for as long as COM2 is down."""
        router = self._router()
        router.evaluate(
            com2_restored=False,
            com2_device_connected=False,
            oracle_device_connected=True,
        )
        for _ in range(200):
            decision = router.evaluate(
                com2_restored=False,
                com2_device_connected=False,
                oracle_device_connected=True,
            )
            self.assertEqual(decision.claim_target, TARGET_ORACLE)
            self.assertEqual(decision.route_target, TARGET_ORACLE)
            self.assertFalse(decision.route_changed)

    def test_the_router_rejects_nonsense(self):
        router = self._router()
        with self.assertRaises(ContractError):
            router.evaluate(
                com2_restored="yes",
                com2_device_connected=True,
                oracle_device_connected=False,
            )
        with self.assertRaises(ContractError):
            router.evaluate(
                com2_restored=True,
                com2_device_connected=False,
                oracle_device_connected="no",
            )
        with self.assertRaises(ContractError):
            MeshConnectionRouter(com2=ORACLE, oracle=COM2)
        with self.assertRaises(ContractError):
            MeshConnectionRouter(com2=COM2, oracle=ORACLE, initial_target="nowhere")


if __name__ == "__main__":
    unittest.main()
