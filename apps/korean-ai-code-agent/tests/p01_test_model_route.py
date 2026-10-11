from __future__ import annotations

from unittest import mock

from kagent import p01_adapter as p01_adapter_module
from kagent import p01_orchestration_client as p01_client_module
from padiem_control_plane import product_tier_routes as tier_routes


SYNTHETIC_PLUS_MODEL_ID = "test/plus-synthetic"


def _active_route_for(label: tier_routes.ProductTierLabel):
    if label is tier_routes.ProductTierLabel.PLUS:
        return tier_routes.ProductTierRoute(
            route_id="test.plus.synthetic.v1",
            status=tier_routes.ProductRouteStatus.EXECUTABLE,
            model_family="test",
            provider_id="test",
            model_id=SYNTHETIC_PLUS_MODEL_ID,
            evidence="test-only synthetic Plus route",
        )
    return None


class SyntheticPlusRouteMixin:
    def setUp(self) -> None:
        super().setUp()
        executable = frozenset({SYNTHETIC_PLUS_MODEL_ID})
        patchers = [
            mock.patch.object(p01_adapter_module, "active_route_for", _active_route_for),
            mock.patch.object(p01_client_module, "active_route_for", _active_route_for),
            mock.patch.object(
                p01_client_module,
                "PADIEM_EXECUTABLE_MODEL_IDS",
                executable,
            ),
        ]
        try:
            from kagent import p01_approval_continuation as approval_module
        except ImportError:
            approval_module = None
        if approval_module is not None:
            patchers.append(
                mock.patch.object(
                    approval_module,
                    "PADIEM_EXECUTABLE_MODEL_IDS",
                    executable,
                )
            )

        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
