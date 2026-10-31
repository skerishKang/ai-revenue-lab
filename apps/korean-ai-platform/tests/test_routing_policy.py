"""The b14/auto fixed chain is retired (B7): no chain module, no auto route mode.

The former owner-designated chain (agnes → poolside) and its ``fixed_chain_v1``
policy surface are gone. The retired ``b14/auto`` id resolves to no route, and
no external-fallback knob exists on the manual router or the secret preparer.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.pilot.errors import NoSafeRoute
from app.pilot.router_core import RouteMode, resolve_route, resolve_manual_route


def _app_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return "\n".join(
        p.read_text(encoding="utf-8") for p in (root / "app").rglob("*.py")
    )


def test_fixed_chain_module_does_not_exist():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "app" / "pilot" / "routing_policy.py").exists()
    with pytest.raises(ModuleNotFoundError):
        import app.pilot.routing_policy  # noqa: F401


def test_fixed_chain_surface_is_gone():
    src = _app_source()
    assert "fixed_chain_v1" not in src
    assert "B14_AUTO_CHAIN" not in src
    assert "resolve_chain_route" not in src


def test_auto_route_modes_are_gone():
    assert not hasattr(RouteMode, "AUTO")
    assert not hasattr(RouteMode, "AUTO_FALLBACK")


def test_retired_auto_id_resolves_to_no_route():
    with pytest.raises(NoSafeRoute) as exc_info:
        resolve_route("b14/auto")
    assert exc_info.value.reason_code == "model_not_in_catalog"
    assert exc_info.value.upstream_called is False


def test_no_external_fallback_knob_exists():
    assert "allow_external_fallback" not in inspect.signature(resolve_manual_route).parameters
    # B5 grace: the retired name is tolerated on the wire only to be logged and
    # dropped — the validator never returns it, so routing can never see it.
    from app.pilot.gateway import _validate_b14_options

    for value in (True, False):
        assert "allow_external_fallback" not in _validate_b14_options(
            {"allow_external_fallback": value}
        )
    from app.pilot import platform_secrets

    assert (
        "allow_external_fallback"
        not in inspect.signature(platform_secrets.ensure_route_secrets).parameters
    )
