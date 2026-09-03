from __future__ import annotations

import json

import pytest

from app.pilot.registry_v2 import RegistryV2Error, RouteClass
from app.pilot.registry_v2_legacy import (
    LEGACY_UNKNOWN_REGION,
    legacy_registry_json_to_v2,
)


def _legacy_payload() -> list[dict[str, object]]:
    return [
        {
            "provider_id": "provider-a",
            "display_name": "Provider A",
            "base_url": "https://provider-a.example.com/v1",
            "timeout_seconds": 30,
            "models": [
                {
                    "model_id": "public/model-a",
                    "upstream_model": "upstream-a",
                    "display_name": "Model A",
                    "enabled": True,
                },
                {
                    "model_id": "public/model-b",
                    "upstream_model": "upstream-b",
                    "display_name": "Model B",
                    "enabled": False,
                },
            ],
        },
        {
            "provider_id": "provider-b",
            "display_name": "Provider B",
            "base_url": "https://provider-b.example.com/v1",
            "models": [
                {
                    "model_id": "public/model-c",
                    "upstream_model": "upstream-c",
                    "enabled": True,
                }
            ],
        },
    ]


def _raw(payload: object) -> str:
    return json.dumps(payload, separators=(",", ":"))


def test_valid_legacy_registry_projects_without_inventing_unknown_metadata() -> None:
    registry = legacy_registry_json_to_v2(_raw(_legacy_payload()))

    assert [provider.provider_id for provider in registry.providers] == [
        "provider-a",
        "provider-b",
    ]
    assert [model.model_id for model in registry.models] == [
        "public/model-a",
        "public/model-b",
        "public/model-c",
    ]
    assert [route.model_id for route in registry.routes] == [
        "public/model-a",
        "public/model-b",
        "public/model-c",
    ]

    assert all(model.context_window is None for model in registry.models)
    assert all(model.max_output_tokens is None for model in registry.models)
    assert all(route.route_class is RouteClass.EXTERNAL for route in registry.routes)
    assert all(route.region == LEGACY_UNKNOWN_REGION for route in registry.routes)


def test_enabled_state_and_upstream_identity_are_preserved() -> None:
    registry = legacy_registry_json_to_v2(_raw(_legacy_payload()))

    route_a, route_b, route_c = registry.routes
    assert route_a.enabled is True
    assert route_b.enabled is False
    assert route_c.enabled is True
    assert route_a.upstream_model == "upstream-a"
    assert route_b.upstream_model == "upstream-b"
    assert route_c.upstream_model == "upstream-c"


def test_route_identity_is_deterministic_and_bounded() -> None:
    raw = _raw(_legacy_payload())

    first = legacy_registry_json_to_v2(raw)
    second = legacy_registry_json_to_v2(raw)

    first_ids = [route.route_id for route in first.routes]
    second_ids = [route.route_id for route in second.routes]
    assert first_ids == second_ids
    assert len(first_ids) == len(set(first_ids))
    assert all(route_id.startswith("legacy:provider-") for route_id in first_ids)
    assert all(len(route_id) <= 255 for route_id in first_ids)


def test_public_projection_does_not_emit_execution_transport_configuration() -> None:
    raw = _raw(_legacy_payload())
    public = legacy_registry_json_to_v2(raw).to_public_dict()
    encoded = json.dumps(public, sort_keys=True)

    assert "base_url" not in encoded
    assert "timeout_seconds" not in encoded
    assert "provider-a.example.com" not in encoded
    assert "provider-b.example.com" not in encoded


def test_unknown_provider_extension_fails_closed() -> None:
    payload = _legacy_payload()
    payload[0]["api_key"] = "must-not-cross-boundary"

    with pytest.raises(RegistryV2Error) as exc_info:
        legacy_registry_json_to_v2(_raw(payload))

    assert exc_info.value.code == "unsafe_legacy_registry_extension"
    assert "must-not-cross-boundary" not in exc_info.value.safe_message


def test_unknown_model_extension_fails_closed() -> None:
    payload = _legacy_payload()
    models = payload[0]["models"]
    assert isinstance(models, list)
    assert isinstance(models[0], dict)
    models[0]["credential_binding"] = "SECRET_BINDING"

    with pytest.raises(RegistryV2Error) as exc_info:
        legacy_registry_json_to_v2(_raw(payload))

    assert exc_info.value.code == "unsafe_legacy_registry_extension"
    assert "SECRET_BINDING" not in exc_info.value.safe_message


def test_invalid_legacy_registry_fails_with_bounded_error() -> None:
    payload = _legacy_payload()
    second_models = payload[1]["models"]
    assert isinstance(second_models, list)
    assert isinstance(second_models[0], dict)
    second_models[0]["model_id"] = "public/model-a"

    with pytest.raises(RegistryV2Error) as exc_info:
        legacy_registry_json_to_v2(_raw(payload))

    assert exc_info.value.code == "invalid_legacy_registry"
    assert "public/model-a" not in exc_info.value.safe_message


def test_empty_legacy_registry_is_not_treated_as_configured() -> None:
    with pytest.raises(RegistryV2Error) as exc_info:
        legacy_registry_json_to_v2("")

    assert exc_info.value.code == "legacy_registry_not_configured"
