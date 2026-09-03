from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.pilot.config import pilot_settings
from app.pilot.errors import (
    AmbiguousModelRoute,
    ModelDisabled,
    ModelNotFound,
    RegistryInvalid,
)
from app.pilot.registry import reset_registry
from app.pilot.registry_v2_execution import CanonicalRouteExecutionTarget
from app.pilot.registry_v2_legacy import legacy_registry_json_to_v2
from app.pilot.routing import RouteTarget, resolve_route


REGISTRY_JSON = json.dumps(
    [
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://provider-a.example/v1",
            "timeout_seconds": 37,
            "models": [
                {
                    "model_id": "public-model",
                    "upstream_model": "upstream/model-a",
                    "display_name": "Public Model",
                    "enabled": True,
                },
                {
                    "model_id": "disabled-model",
                    "upstream_model": "upstream/disabled",
                    "display_name": "Disabled Model",
                    "enabled": False,
                },
            ],
        }
    ]
)


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    reset_registry()
    yield
    reset_registry()


def _configure_registry(monkeypatch: pytest.MonkeyPatch, raw_json: str = REGISTRY_JSON) -> None:
    monkeypatch.setattr(pilot_settings, "provider_registry_json", raw_json)
    monkeypatch.setattr(pilot_settings, "pilot_base_url", "")
    monkeypatch.setattr(pilot_settings, "pilot_model_id", "")
    monkeypatch.setattr(pilot_settings, "pilot_upstream_model", "")


def test_valid_registry_resolves_transport_through_canonical_route_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_registry(monkeypatch)
    canonical = legacy_registry_json_to_v2(REGISTRY_JSON)
    expected_route_id = canonical.routes_for_model("public-model")[0].route_id
    captured: dict[str, str] = {}

    def fake_execution_target(raw_json: str, route_id: str) -> CanonicalRouteExecutionTarget:
        captured["raw_json"] = raw_json
        captured["route_id"] = route_id
        return CanonicalRouteExecutionTarget(
            route_id=route_id,
            provider_id="provider-a",
            provider_name="Provider A",
            model_id="public-model",
            upstream_model="upstream/model-a",
            base_url="https://provider-a.example/v1",
            timeout_seconds=37,
        )

    monkeypatch.setattr(
        "app.pilot.registry_v2_execution.resolve_legacy_v2_route_execution_target",
        fake_execution_target,
    )

    target = resolve_route("public-model")

    assert captured == {
        "raw_json": REGISTRY_JSON,
        "route_id": expected_route_id,
    }
    assert target == RouteTarget(
        provider_id="provider-a",
        provider_name="Provider A",
        model_id="public-model",
        upstream_model="upstream/model-a",
        base_url="https://provider-a.example/v1",
        timeout_seconds=37,
    )


def test_real_canonical_execution_join_preserves_existing_route_target_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_registry(monkeypatch)

    assert resolve_route("public-model") == RouteTarget(
        provider_id="provider-a",
        provider_name="Provider A",
        model_id="public-model",
        upstream_model="upstream/model-a",
        base_url="https://provider-a.example/v1",
        timeout_seconds=37,
    )


def test_disabled_model_preserves_existing_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_registry(monkeypatch)

    with pytest.raises(ModelDisabled) as exc_info:
        resolve_route("disabled-model")
    assert exc_info.value.code == "model_disabled"


def test_unknown_model_preserves_existing_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_registry(monkeypatch)

    with pytest.raises(ModelNotFound) as exc_info:
        resolve_route("missing-model")
    assert exc_info.value.code == "model_not_found"


def test_ambiguous_canonical_route_fails_closed_before_transport_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_registry(monkeypatch)

    fake_registry = SimpleNamespace(
        get_model=lambda model_id: SimpleNamespace(model_id=model_id),
        routes_for_model=lambda model_id, enabled_only=False: (
            SimpleNamespace(route_id="route-a", enabled=True),
            SimpleNamespace(route_id="route-b", enabled=True),
        ),
    )
    monkeypatch.setattr(
        "app.pilot.registry_v2_legacy.legacy_registry_json_to_v2",
        lambda raw_json: fake_registry,
    )

    called = False

    def fail_if_called(raw_json: str, route_id: str) -> CanonicalRouteExecutionTarget:
        nonlocal called
        called = True
        raise AssertionError("transport resolution must not run for ambiguous routes")

    monkeypatch.setattr(
        "app.pilot.registry_v2_execution.resolve_legacy_v2_route_execution_target",
        fail_if_called,
    )

    with pytest.raises(AmbiguousModelRoute) as exc_info:
        resolve_route("public-model")
    assert exc_info.value.code == "ambiguous_model_route"
    assert called is False


def test_legacy_registry_extension_rejected_by_canonical_execution_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(REGISTRY_JSON)
    payload[0]["credential_ref"] = "must-not-cross-boundary"
    _configure_registry(monkeypatch, json.dumps(payload))

    # The Phase-2 parser historically ignores extra fields.  The active
    # canonical route boundary is intentionally stricter and must fail closed.
    with pytest.raises(RegistryInvalid) as exc_info:
        resolve_route("public-model")
    assert exc_info.value.code == "registry_invalid"


def test_legacy_single_provider_mode_remains_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pilot_settings, "provider_registry_json", "")
    monkeypatch.setattr(pilot_settings, "pilot_provider_id", "legacy-provider")
    monkeypatch.setattr(pilot_settings, "pilot_base_url", "https://legacy.example/v1")
    monkeypatch.setattr(pilot_settings, "pilot_model_id", "legacy-model")
    monkeypatch.setattr(pilot_settings, "pilot_upstream_model", "legacy/upstream")
    monkeypatch.setattr(pilot_settings, "pilot_timeout_seconds", 29)

    assert resolve_route("legacy-model") == RouteTarget(
        provider_id="legacy-provider",
        provider_name="Legacy Provider",
        model_id="legacy-model",
        upstream_model="legacy/upstream",
        base_url="https://legacy.example/v1",
        timeout_seconds=29,
    )
