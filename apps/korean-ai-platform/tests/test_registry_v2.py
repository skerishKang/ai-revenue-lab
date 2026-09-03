from __future__ import annotations

import json

import pytest

from app.pilot.registry_v2 import (
    CanonicalRegistryV2,
    ProviderDefinition,
    ProviderRouteDefinition,
    PublicModelDefinition,
    REGISTRY_V2_SCHEMA,
    RegistryV2Error,
    RouteClass,
    parse_registry_v2,
    registry_v2_from_dict,
)


def payload() -> dict:
    return {
        "schema_version": REGISTRY_V2_SCHEMA,
        "providers": [
            {"provider_id": "provider-a", "display_name": "Provider A"},
            {"provider_id": "provider-b", "display_name": "Provider B"},
        ],
        "models": [
            {
                "model_id": "padiem/model-x",
                "display_name": "Model X",
                "context_window": 128000,
                "max_output_tokens": 8192,
            },
            {
                "model_id": "padiem/model-y",
                "display_name": "Model Y",
                "context_window": None,
                "max_output_tokens": None,
            },
        ],
        "routes": [
            {
                "route_id": "provider-a:model-x:kr",
                "model_id": "padiem/model-x",
                "provider_id": "provider-a",
                "upstream_model": "upstream/model-x",
                "enabled": True,
                "route_class": "domestic",
                "region": "KR",
            },
            {
                "route_id": "provider-b:model-x:global",
                "model_id": "padiem/model-x",
                "provider_id": "provider-b",
                "upstream_model": "vendor/model-x",
                "enabled": True,
                "route_class": "external",
                "region": "GLOBAL",
            },
            {
                "route_id": "provider-b:model-y:global",
                "model_id": "padiem/model-y",
                "provider_id": "provider-b",
                "upstream_model": "vendor/model-y",
                "enabled": False,
                "route_class": "external",
                "region": "GLOBAL",
            },
        ],
    }


def test_one_public_model_may_have_multiple_provider_routes_in_definition_order():
    registry = registry_v2_from_dict(payload())

    routes = registry.routes_for_model("padiem/model-x")

    assert [route.route_id for route in routes] == [
        "provider-a:model-x:kr",
        "provider-b:model-x:global",
    ]
    assert [route.provider_id for route in routes] == ["provider-a", "provider-b"]
    assert registry.get_model("padiem/model-x").display_name == "Model X"


def test_route_identity_is_independent_from_public_model_identity():
    registry = registry_v2_from_dict(payload())

    first = registry.get_route("provider-a:model-x:kr")
    second = registry.get_route("provider-b:model-x:global")

    assert first.model_id == second.model_id == "padiem/model-x"
    assert first.route_id != second.route_id
    assert first.upstream_model != second.upstream_model


def test_duplicate_route_id_fails_closed_even_for_different_public_models():
    data = payload()
    data["routes"][2]["route_id"] = data["routes"][0]["route_id"]

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "duplicate_route_id"


def test_duplicate_public_model_definition_fails_closed():
    data = payload()
    data["models"].append(
        {"model_id": "padiem/model-x", "display_name": "Duplicate Model X"}
    )

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "duplicate_model_id"


def test_duplicate_provider_definition_fails_closed():
    data = payload()
    data["providers"].append(
        {"provider_id": "provider-a", "display_name": "Duplicate Provider"}
    )

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "duplicate_provider_id"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("provider_id", "missing-provider", "dangling_provider_reference"),
        ("model_id", "missing/model", "dangling_model_reference"),
    ],
)
def test_dangling_route_references_fail_closed(field: str, value: str, code: str):
    data = payload()
    data["routes"][0][field] = value

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == code


def test_disabled_routes_are_preserved_but_excluded_from_default_lookup():
    registry = registry_v2_from_dict(payload())

    assert registry.routes_for_model("padiem/model-y") == ()
    all_routes = registry.routes_for_model("padiem/model-y", enabled_only=False)
    assert [route.route_id for route in all_routes] == ["provider-b:model-y:global"]


def test_routes_for_provider_preserve_registry_order_and_enabled_filter():
    registry = registry_v2_from_dict(payload())

    enabled = registry.routes_for_provider("provider-b")
    all_routes = registry.routes_for_provider("provider-b", enabled_only=False)

    assert [item.route_id for item in enabled] == ["provider-b:model-x:global"]
    assert [item.route_id for item in all_routes] == [
        "provider-b:model-x:global",
        "provider-b:model-y:global",
    ]


def test_unknown_limits_remain_none_and_are_not_fabricated():
    registry = registry_v2_from_dict(payload())
    model = registry.get_model("padiem/model-y")

    assert model.context_window is None
    assert model.max_output_tokens is None
    assert model.to_public_dict()["context_window"] is None
    assert model.to_public_dict()["max_output_tokens"] is None


@pytest.mark.parametrize("field", ["context_window", "max_output_tokens"])
@pytest.mark.parametrize("bad_value", [True, 0, -1, 1.5, "128000"])
def test_invalid_model_limits_fail_closed(field: str, bad_value):
    data = payload()
    data["models"][0][field] = bad_value

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"


def test_invalid_route_class_fails_closed():
    data = payload()
    data["routes"][0]["route_class"] = "unknown"

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"


def test_registry_requires_at_least_one_enabled_route():
    data = payload()
    for route in data["routes"]:
        route["enabled"] = False

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"


def test_provider_credentials_are_not_registry_fields():
    data = payload()
    data["providers"][0]["api_key"] = "should-never-be-a-registry-field"

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"
    assert "should-never-be-a-registry-field" not in exc.value.safe_message


def test_route_secret_binding_fields_are_rejected_instead_of_projected():
    data = payload()
    data["routes"][0]["credential_binding"] = "PROVIDER_A_KEY"

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"
    assert "PROVIDER_A_KEY" not in exc.value.safe_message


def test_unknown_top_level_fields_fail_closed():
    data = payload()
    data["account_plan"] = "pro"

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "invalid_registry_v2"
    assert "pro" not in exc.value.safe_message


def test_public_projection_contains_no_credential_or_account_fields():
    projection = registry_v2_from_dict(payload()).to_public_dict()
    serialized = json.dumps(projection, sort_keys=True)

    assert "credential" not in serialized
    assert "api_key" not in serialized
    assert "account" not in serialized
    assert projection["schema_version"] == REGISTRY_V2_SCHEMA


def test_json_parser_rejects_malformed_or_wrong_shape():
    with pytest.raises(RegistryV2Error) as malformed:
        parse_registry_v2("{broken")
    assert malformed.value.code == "invalid_registry_v2"

    with pytest.raises(RegistryV2Error) as wrong_shape:
        parse_registry_v2("[]")
    assert wrong_shape.value.code == "invalid_registry_v2"


def test_json_round_trip_preserves_canonical_registry_contract():
    original = payload()
    registry = parse_registry_v2(json.dumps(original))

    assert registry.to_public_dict() == original


def test_unsupported_schema_version_fails_closed():
    data = payload()
    data["schema_version"] = "b14.registry.v3"

    with pytest.raises(RegistryV2Error) as exc:
        registry_v2_from_dict(data)

    assert exc.value.code == "unsupported_registry_version"


def test_direct_dataclasses_enforce_same_identity_contract():
    registry = CanonicalRegistryV2(
        providers=(ProviderDefinition("provider-a", "Provider A"),),
        models=(PublicModelDefinition("padiem/model-x", "Model X"),),
        routes=(
            ProviderRouteDefinition(
                route_id="provider-a:model-x",
                model_id="padiem/model-x",
                provider_id="provider-a",
                upstream_model="vendor/model-x",
                enabled=True,
                route_class=RouteClass.EXTERNAL,
                region="GLOBAL",
            ),
        ),
    )

    assert registry.get_route("provider-a:model-x").model_id == "padiem/model-x"
