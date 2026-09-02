from __future__ import annotations

import unittest

from kagent.ops_workflow import QuoteToOrderCoordinator


class OpsApprovalAuthorityBoundaryTests(unittest.TestCase):
    def test_product_coordinator_does_not_expose_approval_minting_helper(self) -> None:
        self.assertFalse(hasattr(QuoteToOrderCoordinator, "approved_projection"))
        self.assertTrue(hasattr(QuoteToOrderCoordinator, "record_approval_projection"))


if __name__ == "__main__":
    unittest.main()
