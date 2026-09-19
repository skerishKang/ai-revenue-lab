"""#2800: the shared tier declaration must not be able to change without running Claw.

Claw owns no route literal: `p01_adapter` and `p01_orchestration_client` ask
`active_route_for()` what Plus and Pro resolve to, so a declaration edit alone moves Claw's
live behaviour. Before this child, `Validate B54 KAgent` listed only two broker modules under
`packages/padiem-control-plane`, so that edit ran no Claw test at all.

These assertions pin the trigger itself. Removing the path filter does not silently re-open
the hole: the workflow lists its own file in `pull_request.paths`, so the deletion trips the
suite that was supposed to have been avoided.

Stdlib only — this suite must not need a YAML parser that is not in the Claw lockfile.
"""

from __future__ import annotations

import re
from pathlib import Path
import unittest

from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    active_route_for,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/validate-b54-kagent.yml"
CONTRACT_PATH = "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py"
BROKER_PATHS = {
    "packages/padiem-control-plane/padiem_control_plane/local_agent_broker.py",
    "packages/padiem-control-plane/padiem_control_plane/local_agent_broker_rpc.py",
}


def _pull_request_path_filters(text: str) -> list[str]:
    """Return the literal entries of on.pull_request.paths, in file order."""
    lines = text.splitlines()
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if re.match(r"^  pull_request:\s*$", line)
        )
    except StopIteration:
        raise AssertionError("workflow has no pull_request trigger") from None
    try:
        paths_index = next(
            index
            for index in range(start + 1, len(lines))
            if re.match(r"^\s{4}paths:\s*$", lines[index])
        )
    except StopIteration:
        raise AssertionError("pull_request trigger has no paths filter") from None
    filters: list[str] = []
    for line in lines[paths_index + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = re.match(r"^\s{6}-\s*(.+?)\s*$", line)
        if entry is None:
            break
        filters.append(entry.group(1).strip("'\""))
    return filters


class TierRouteConsumerCoverageTests(unittest.TestCase):
    def test_claw_ci_runs_when_the_shared_tier_declaration_changes(self):
        filters = _pull_request_path_filters(WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn(
            CONTRACT_PATH,
            filters,
            "Claw derives its product-tier model policy from this file, so its suite must "
            "run when it changes; see #2800",
        )

    def test_trigger_stays_narrow_to_the_declaration_file(self):
        # Listing the whole package would run Claw on every control-plane edit and make the
        # signal meaningless; the two broker lanes already cover their own files.
        filters = set(_pull_request_path_filters(WORKFLOW.read_text(encoding="utf-8")))
        broad = [entry for entry in filters if entry.endswith("padiem-control-plane/**")]
        self.assertEqual(broad, [])
        claw_owned_inputs = BROKER_PATHS | {CONTRACT_PATH}
        self.assertEqual(filters & claw_owned_inputs, claw_owned_inputs)

    def test_claw_executable_set_is_derived_not_restated(self):
        # The point of the trigger: Claw's expectation comes from the contract, so there is
        # nothing here to update when an owner switches a tier route.
        from kagent.p01_orchestration_client import PADIEM_EXECUTABLE_MODEL_IDS

        expected = {
            route.model_id
            for label in (ProductTierLabel.PLUS, ProductTierLabel.PRO)
            for route in [active_route_for(label)]
            if route is not None and route.model_id is not None
        }
        self.assertEqual(set(PADIEM_EXECUTABLE_MODEL_IDS), expected)
        self.assertTrue(expected, "the contract must expose at least one executable tier route")

    def test_owner_policy_invariants_hold_while_consumers_derive(self):
        # Asserted rather than assumed, because this child makes Claw lean harder on them.
        from padiem_control_plane.product_tier_routes import (
            PRODUCT_TIER_ROUTES,
            ProductRouteStatus,
        )

        for tier in PRODUCT_TIER_ROUTES:
            self.assertFalse(tier.silent_fallback_allowed, tier.label.value)
            self.assertNotIn("auto", tier.label.value.lower())
            executable = [
                route for route in tier.routes if route.status is ProductRouteStatus.EXECUTABLE
            ]
            self.assertLessEqual(len(executable), 1, tier.label.value)
            if executable:
                self.assertIs(active_route_for(tier.label), executable[0])


if __name__ == "__main__":
    unittest.main()
