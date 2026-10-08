"""Test-only synthetic Plus route for the P01 execution contracts (#3767).

Why this exists
---------------
The canonical declaration (``padiem_control_plane.product_tier_routes``) holds
every product tier, so ``kagent.p01_adapter._agent_profile()`` refuses to build a
profile and a group of P01 execution contracts were *skipped* instead of
executed (20 skips in ``test_p01_adapter.py`` alone). Skipping them left the
dispatch / approval / continuation / error boundaries unverified.

What it does
------------
Installs the same kind of bounded, test-only route the B62 Chat suite already
uses (``apps/padiem-chat/tests/conftest.py::_synthetic_plus_route_for_non_policy_contracts``):

* the synthetic route reuses the product HOLD identity as its ``model_id``, so it
  can never masquerade as a provider lane, and it is never registered in the
  canonical declaration or in any B14 catalog;
* nothing in production source changes: ``active_route_for`` is patched on the
  declaration module and on the runtime modules that imported it by value, and
  the patch is removed again afterwards;
* every transport these tests use is a fake, so no provider is ever called.

Boundary
--------
Tests that assert the *production* HOLD posture must not use this fixture.
:class:`SyntheticPlusRouteBoundaryTests` in ``test_p01_adapter.py`` proves the
patch is installed and removed, and that the production declaration is back to
HOLD when it is gone.
"""

from __future__ import annotations

import contextlib
import functools
import importlib
import inspect
import unittest
from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

from padiem_control_plane import product_tier_routes as tier_routes

SYNTHETIC_ROUTE_ID = "test.plus.synthetic.v1"
SYNTHETIC_PROVIDER_ID = "test"

# Runtime modules that imported the canonical resolver by value at import time.
_ROUTE_RESOLVER_MODULES = (
    "kagent.p01_adapter",
    "kagent.p01_orchestration_client",
    "kagent.p01_approval_continuation",
)


def synthetic_plus_route() -> tier_routes.ProductTierRoute:
    """Return the synthetic Plus route (a legal shape that is never registered)."""

    return tier_routes.ProductTierRoute(
        route_id=SYNTHETIC_ROUTE_ID,
        status=tier_routes.ProductRouteStatus.EXECUTABLE,
        model_family="test",
        provider_id=SYNTHETIC_PROVIDER_ID,
        model_id=tier_routes.PLUS_HOLD_MODEL_ID,
        evidence="test-only synthetic Plus route (#3767); never registered in the declaration",
    )


def synthetic_model_id() -> str:
    """The model id the synthetic route resolves to (the product HOLD identity)."""

    return tier_routes.PLUS_HOLD_MODEL_ID


def canonical_plus_route_model() -> str | None:
    """The model id the untouched canonical declaration resolves Plus to.

    ``None`` while the product keeps Plus on HOLD, which is the state the
    synthetic route stands in for.
    """

    route = tier_routes.active_route_for(tier_routes.ProductTierLabel.PLUS)
    if route is None or not route.model_id:
        return None
    return route.model_id


def contract_model_id() -> str:
    """The model id the execution contract under test resolves Plus to.

    Equal to what :func:`plus_route_for_test` yields and to
    ``SyntheticPlusRouteTestCase.plus_route_model``: the route an owner actually
    declared when one exists, otherwise the test-only synthetic identity. A test
    module can therefore bind its expectation at import time without freezing the
    current all-HOLD state, and without a model-gated ``SkipTest``.
    """

    declared = canonical_plus_route_model()
    return declared if declared is not None else synthetic_model_id()


def _resolver(route: tier_routes.ProductTierRoute):
    def _active_route_for(label: tier_routes.ProductTierLabel):
        return route if label is tier_routes.ProductTierLabel.PLUS else None

    return _active_route_for


@contextlib.contextmanager
def synthetic_plus_route_installed(
    *,
    extra_module_names: tuple[str, ...] = (),
) -> Iterator[str]:
    """Install the synthetic Plus route for the duration of the block.

    Yields the model id the declaration resolves Plus to while installed.
    Everything the patch touched is restored on exit, including module-level
    constants that were computed at import time. ``extra_module_names`` names the
    calling test module, whose own ``from ... import active_route_for`` binding
    would otherwise keep answering from the untouched declaration.
    """

    route = synthetic_plus_route()
    resolver = _resolver(route)
    patchers: list[Any] = [mock.patch.object(tier_routes, "active_route_for", resolver)]
    for module_name in (*_ROUTE_RESOLVER_MODULES, *extra_module_names):
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - optional runtime module
            continue
        if hasattr(module, "active_route_for"):
            patchers.append(mock.patch.object(module, "active_route_for", resolver))
        if hasattr(module, "PADIEM_EXECUTABLE_MODEL_IDS"):
            patchers.append(
                mock.patch.object(
                    module,
                    "PADIEM_EXECUTABLE_MODEL_IDS",
                    frozenset({route.model_id}),
                )
            )

    for patcher in patchers:
        patcher.start()
    try:
        yield route.model_id
    finally:
        for patcher in reversed(patchers):
            patcher.stop()


@contextlib.contextmanager
def plus_route_for_test(
    *,
    extra_module_names: tuple[str, ...] = (),
) -> Iterator[str]:
    """Yield the Plus model id a test should assert against.

    An owner-selected route is used exactly as declared; only while the
    declaration holds the tier does the bounded synthetic route stand in.
    """

    declared = canonical_plus_route_model()
    if declared is not None:
        yield declared
        return
    with synthetic_plus_route_installed(extra_module_names=extra_module_names) as model_id:
        yield model_id


def with_synthetic_plus_route(func: Callable[..., Any]) -> Callable[..., Any]:
    """Run one test method (sync or async) against the Plus route under test.

    Also exposes the resolved id as ``self.plus_route_model`` so the test body
    can assert the exact identity without freezing it in the source.
    """

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            with plus_route_for_test(extra_module_names=(func.__module__,)) as model_id:
                self.plus_route_model = model_id
                return await func(self, *args, **kwargs)

        return async_wrapper

    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with plus_route_for_test(extra_module_names=(func.__module__,)) as model_id:
            self.plus_route_model = model_id
            return func(self, *args, **kwargs)

    return wrapper


class SyntheticPlusRouteTestCase(unittest.TestCase):
    """Base class for tests that exercise the P01 execution path.

    ``plus_route_model`` is the model id the canonical resolver answers with
    while the class runs: the declared route when an owner has selected one, and
    the test-only synthetic route otherwise. The tests therefore never assert a
    frozen model identity, and they never hardcode a provider lane.
    """

    plus_route_model: str | None = None
    synthetic_route_installed: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if canonical_plus_route_model() is not None:
            # An owner-selected route exists, so the real declaration is what
            # these contracts should exercise. Nothing is installed.
            declared = canonical_plus_route_model()
            cls.plus_route_model = declared
            return
        cls.synthetic_route_installed = True
        stack = contextlib.ExitStack()
        cls.addClassCleanup(stack.close)
        cls.plus_route_model = stack.enter_context(
            synthetic_plus_route_installed(extra_module_names=(cls.__module__,))
        )
