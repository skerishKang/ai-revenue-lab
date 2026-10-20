"""#5223: the Claw P01 authority pin must accept every product tier's own route.

The P01 wire accepts the *implicit* product-tier authority: the model the
shared product-tier declaration resolves for the tier being dispatched. The
Claw side derived that allowlist from a hand-picked tier subset, so a tier the
shared contract declares executable could still be refused by the pin.

The refusal happened before the Engine was reached, so the whole tier's
Claw/P01 dispatch failed closed as a generic engine failure instead of
returning a model response. The shared contract is the single source of truth
for tier routes, and the consumer derives from it; it never restates a
subset of it.

Network-free: only the Engine bytes are faked. The shared declaration contract
and the derived allowlist are the real ones.
"""
from __future__ import annotations

import asyncio
import unittest

from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    active_route_for,
)

from kagent.contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from kagent.runs import ClawRun
from kagent.p01_adapter import (
    P01AdapterError,
    P01RequestFactory,
)
from kagent.p01_orchestration_client import (
    PADIEM_EXECUTABLE_MODEL_IDS,
    P01EngineOrchestrationClient,
)

from test_p01_orchestration_client import _client, _ok_transport, _public_result


def _contract_route_models() -> set[str]:
    """Every model the shared contract declares executable, per tier."""
    return {
        route.model_id
        for label in ProductTierLabel
        for route in [active_route_for(label)]
        if route is not None and route.model_id is not None
    }


def _tier_request(label: ProductTierLabel):
    """The exact request the P01 factory builds for one product tier."""
    intent = ClawTaskIntent(
        task_id="task_5223_tier_route",
        task="P01 등급 라우트를 검증해줘",
        repository_ref="skerishKang/example",
        execution_mode=ExecutionMode.LOCAL,
    )
    run = ClawRun.create("run_5223_tier_route", intent)
    bundle = P01RequestFactory(product_tier=label).build(run, product_tier=label)
    return run, bundle.orchestration_request


class TierRouteAuthorityPinTests(unittest.TestCase):
    def test_every_tier_route_is_in_the_claw_allowlist(self):
        """A tier the contract calls executable must be dispatchable by Claw."""
        for label in ProductTierLabel:
            route = active_route_for(label)
            if route is None or route.model_id is None:
                continue
            with self.subTest(tier=label.value):
                self.assertIn(route.model_id, PADIEM_EXECUTABLE_MODEL_IDS)

    def test_allowlist_adds_nothing_outside_the_contract(self):
        """The pin stays exactly the contract's executable routes."""
        self.assertEqual(set(PADIEM_EXECUTABLE_MODEL_IDS), _contract_route_models())

    def test_free_tier_dispatch_reaches_the_engine(self):
        """The Free tier's own route is dispatched, not refused before the Engine."""
        _, request = _tier_request(ProductTierLabel.FREE)
        transport = _ok_transport(_public_result(request))
        port = P01EngineOrchestrationClient(_client(transport))

        outcome = asyncio.run(port.run(request))

        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(outcome.execution_result.answer, "완료 답변")

    def test_free_tier_policy_is_not_refused_by_the_authority_pin(self):
        """The Free tier's own model policy passes the pin."""
        _, request = _tier_request(ProductTierLabel.FREE)
        transport = _ok_transport(_public_result(request))
        port = P01EngineOrchestrationClient(_client(transport))

        try:
            asyncio.run(port.run(request))
        except P01AdapterError as exc:  # pragma: no cover - the failure path
            self.fail(f"Free tier dispatch was refused: {exc.code}")

        self.assertEqual(len(transport.requests), 1)

    def test_max_tier_dispatch_reaches_the_engine(self):
        """Max keeps dispatching; the derivation covers every tier, not a subset."""
        _, request = _tier_request(ProductTierLabel.MAX)
        transport = _ok_transport(_public_result(request))
        port = P01EngineOrchestrationClient(_client(transport))

        asyncio.run(port.run(request))

        self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
