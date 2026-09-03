from __future__ import annotations

from dataclasses import fields
import json

import pytest

from app.pilot.registry_v2_execution import (
    CanonicalRouteExecutionTarget,
    RegistryV2ExecutionError,
    resolve_legacy_v2_route_execution_target,
)
from app.pilot.registry_v2_legacy import legacy_registry_json_to_v2


def _legacy_payload() -> list[dict[str, object]]:
    return [
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://api.provider-a.example.com/v1",
            "timeout_seconds": 25,
            "models": [
                {
                    "model_id": "model-a",
                    "upstream_model": "upstream/a",
                    "display_name": "Model A",
                    "enabled": True,
                },
                {
                    "model_id": "model-disabled",
                    "upstream_model": "upstream/disabled",
                    "display_name": "Disabled Model",
                    "enabled": False,
                },
            ],
        },
        {
            "provider_id": "provider-b",
            "display_name": "Provider B",
            "base_url": "https://api.provider-b.example.com/v1",
            "timeout_seconds": 40,
            "models": [
                {
                    "model_id": "model-b",
                    "upstream_model": "upstream/b",
                    "display_name": "Model B",
                    "enabled": True,
                }
            ],
        },
    ]


def _raw(payload: list[dict[str, object]] | None = None) -> str:
    return json.dumps(payload or _legacy_payload())


def _route_id(model_id: str) -> str:
    registry = legacy_registry_json_to_v2(_raw())
    routes = [route for route in registry.routes if route.model_id == model_id]
    assert len(routes) == 1
    return routes[0].route_id


def test_resolves_canonical_route_id_to_trusted_transport_target() -> None:
    target = resolve_legacy_v2_route_execution_target(_raw(), _route_id("model-a"))

    assert target == CanonicalRouteExecutionTarget(
        route_id=_route_id("model-a"),
        provider_id="provider-a",
        provider_name="Provider A",
        model_id="model-a",
        upstream_model="upstream/a",
        base_url="https://api.provider-a.example.com/v1",
        timeout_seconds=25,
    )


def test_resolution_is_deterministic_for_same_source_and_route() -> None:
    route_id = _route_id("model-b")
    first = resolve_legacy_v2_route_execution_target(_raw(), route_id)
    second = resolve_legacy_v2_route_execution_target(_raw(), route_id)
    assert first == second


def test_unknown_route_id_fails_closed() -> None:
    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target(_raw(), "legacy:provider-a:deadbeef")
    assert exc_info.value.code == "route_not_found"


def test_empty_route_id_fails_closed_before_resolution() -> None:
    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target(_raw(), "")
    assert exc_info.value.code == "invalid_route_id"


def test_disabled_route_fails_closed() -> None:
    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target(
            _raw(),
            _route_id("model-disabled"),
        )
    assert exc_info.value.code == "route_disabled"


def test_invalid_legacy_registry_remains_fail_closed() -> None:
    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target("{}", "any-route")
    assert exc_info.value.code == "invalid_legacy_registry"


def test_secret_or_account_extension_never_crosses_execution_seam() -> None:
    payload = _legacy_payload()
    payload[0]["api_key"] = "must-not-cross"
    raw = json.dumps(payload)

    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target(raw, "any-route")
    assert exc_info.value.code == "unsafe_legacy_registry_extension"


def test_execution_target_contract_has_no_secret_account_or_entitlement_fields() -> None:
    field_names = {item.name for item in fields(CanonicalRouteExecutionTarget)}
    assert field_names == {
        "route_id",
        "provider_id",
        "provider_name",
        "model_id",
        "upstream_model",
        "base_url",
        "timeout_seconds",
    }
    assert not any(
        token in name
        for name in field_names
        for token in ("key", "secret", "credential", "account", "entitlement", "billing")
    )


def test_public_model_id_is_not_accepted_as_route_selector() -> None:
    with pytest.raises(RegistryV2ExecutionError) as exc_info:
        resolve_legacy_v2_route_execution_target(_raw(), "model-a")
    assert exc_info.value.code == "route_not_found"


def test_default_provider_display_name_and_timeout_are_preserved_from_legacy_contract() -> None:
    payload = [
        {
            "provider_id": "provider-c",
            "base_url": "https://api.provider-c.example.com/v1",
            "models": [
                {
                    "model_id": "model-c",
                    "upstream_model": "upstream/c",
                    "enabled": True,
                }
            ],
        }
    ]
    raw = json.dumps(payload)
    registry = legacy_registry_json_to_v2(raw)
    route_id = registry.routes[0].route_id

    target = resolve_legacy_v2_route_execution_target(raw, route_id)
    assert target.provider_name == "provider-c"
    assert target.timeout_seconds == 30
