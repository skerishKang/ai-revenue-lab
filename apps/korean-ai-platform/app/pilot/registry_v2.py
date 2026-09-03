"""Canonical Business 14 public-model / Provider-route registry v2.

This module is an additive Phase 5 contract.  It deliberately separates the
public model identity exposed by Business 14 from the Provider route used to
execute that model:

    one public model_id -> one or more globally unique route_id values

It does not select a route, resolve credentials, or replace the legacy Pilot
registry.  Those integrations are separate reviewed slices.

Security / evidence boundaries:
- Provider credentials and secret binding values are not fields in this schema;
- unknown context/output limits remain ``None``;
- configured registry metadata is not measured availability/cost/latency truth;
- invalid or dangling references fail closed during construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
from typing import Any, Mapping, Sequence

REGISTRY_V2_SCHEMA = "b14.registry.v2"
MAX_PROVIDERS = 128
MAX_PUBLIC_MODELS = 512
MAX_PROVIDER_ROUTES = 2048

_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REGION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


class RegistryV2Error(ValueError):
    """Bounded validation failure for canonical registry-v2 input."""

    def __init__(self, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


class RouteClass(str, Enum):
    LOCAL = "local"
    DOMESTIC = "domestic"
    EXTERNAL = "external"


def _strict_object(
    name: str,
    value: Any,
    *,
    allowed: frozenset[str],
    required: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RegistryV2Error("invalid_registry_v2", f"{name} must be an object")
    keys = frozenset(value)
    unknown = keys - allowed
    if unknown:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} contains unsupported fields",
        )
    missing = required - keys
    if missing:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} is missing required fields",
        )
    return value


def _provider_id(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _PROVIDER_ID_RE.fullmatch(value):
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must be a bounded Provider identifier",
        )
    return value


def _reference(name: str, value: Any) -> str:
    if not isinstance(value, str) or not _REFERENCE_RE.fullmatch(value):
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must be a bounded safe reference",
        )
    return value


def _display_name(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise RegistryV2Error("invalid_registry_v2", f"{name} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must contain 1..128 characters",
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in normalized):
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must not contain control characters",
        )
    return normalized


def _region(value: Any) -> str:
    if not isinstance(value, str) or not _REGION_RE.fullmatch(value):
        raise RegistryV2Error(
            "invalid_registry_v2",
            "region must be a bounded configured region identifier",
        )
    return value


def _optional_positive_limit(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must be a positive integer or null",
        )
    return value


def _bounded_sequence(name: str, value: Any, *, maximum: int) -> Sequence[Any]:
    if not isinstance(value, list) or not value:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} must be a non-empty array",
        )
    if len(value) > maximum:
        raise RegistryV2Error(
            "invalid_registry_v2",
            f"{name} exceeds the bounded entry limit",
        )
    return value


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    provider_id: str
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", _provider_id("provider_id", self.provider_id))
        object.__setattr__(self, "display_name", _display_name("display_name", self.display_name))

    def to_public_dict(self) -> dict[str, str]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
        }


@dataclass(frozen=True, slots=True)
class PublicModelDefinition:
    """Stable Business 14 model identity independent of an execution route."""

    model_id: str
    display_name: str
    context_window: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_id", _reference("model_id", self.model_id))
        object.__setattr__(self, "display_name", _display_name("display_name", self.display_name))
        object.__setattr__(
            self,
            "context_window",
            _optional_positive_limit("context_window", self.context_window),
        )
        object.__setattr__(
            self,
            "max_output_tokens",
            _optional_positive_limit("max_output_tokens", self.max_output_tokens),
        )

    def to_public_dict(self) -> dict[str, str | int | None]:
        return {
            "model_id": self.model_id,
            "display_name": self.display_name,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
        }


@dataclass(frozen=True, slots=True)
class ProviderRouteDefinition:
    """One concrete Provider execution route for a public model."""

    route_id: str
    model_id: str
    provider_id: str
    upstream_model: str
    enabled: bool
    route_class: RouteClass
    region: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "route_id", _reference("route_id", self.route_id))
        object.__setattr__(self, "model_id", _reference("model_id", self.model_id))
        object.__setattr__(self, "provider_id", _provider_id("provider_id", self.provider_id))
        object.__setattr__(
            self,
            "upstream_model",
            _reference("upstream_model", self.upstream_model),
        )
        if not isinstance(self.enabled, bool):
            raise RegistryV2Error(
                "invalid_registry_v2",
                "enabled must be boolean",
            )
        if not isinstance(self.route_class, RouteClass):
            raise RegistryV2Error(
                "invalid_registry_v2",
                "route_class must be local, domestic, or external",
            )
        object.__setattr__(self, "region", _region(self.region))

    def to_public_dict(self) -> dict[str, str | bool]:
        return {
            "route_id": self.route_id,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "upstream_model": self.upstream_model,
            "enabled": self.enabled,
            "route_class": self.route_class.value,
            "region": self.region,
        }


@dataclass(frozen=True, slots=True)
class CanonicalRegistryV2:
    providers: tuple[ProviderDefinition, ...]
    models: tuple[PublicModelDefinition, ...]
    routes: tuple[ProviderRouteDefinition, ...]
    schema_version: str = REGISTRY_V2_SCHEMA

    def __post_init__(self) -> None:
        if self.schema_version != REGISTRY_V2_SCHEMA:
            raise RegistryV2Error(
                "unsupported_registry_version",
                "registry schema_version is not supported",
            )

        providers = tuple(self.providers)
        models = tuple(self.models)
        routes = tuple(self.routes)
        if not providers or len(providers) > MAX_PROVIDERS:
            raise RegistryV2Error(
                "invalid_registry_v2",
                "registry must contain a bounded non-empty Provider set",
            )
        if not models or len(models) > MAX_PUBLIC_MODELS:
            raise RegistryV2Error(
                "invalid_registry_v2",
                "registry must contain a bounded non-empty public-model set",
            )
        if not routes or len(routes) > MAX_PROVIDER_ROUTES:
            raise RegistryV2Error(
                "invalid_registry_v2",
                "registry must contain a bounded non-empty route set",
            )
        if any(not isinstance(item, ProviderDefinition) for item in providers):
            raise RegistryV2Error("invalid_registry_v2", "providers contain invalid entries")
        if any(not isinstance(item, PublicModelDefinition) for item in models):
            raise RegistryV2Error("invalid_registry_v2", "models contain invalid entries")
        if any(not isinstance(item, ProviderRouteDefinition) for item in routes):
            raise RegistryV2Error("invalid_registry_v2", "routes contain invalid entries")

        provider_ids = tuple(item.provider_id for item in providers)
        model_ids = tuple(item.model_id for item in models)
        route_ids = tuple(item.route_id for item in routes)
        if len(provider_ids) != len(set(provider_ids)):
            raise RegistryV2Error("duplicate_provider_id", "provider_id values must be unique")
        if len(model_ids) != len(set(model_ids)):
            raise RegistryV2Error("duplicate_model_id", "public model_id values must be unique")
        if len(route_ids) != len(set(route_ids)):
            raise RegistryV2Error("duplicate_route_id", "route_id values must be globally unique")

        provider_set = set(provider_ids)
        model_set = set(model_ids)
        for route in routes:
            if route.provider_id not in provider_set:
                raise RegistryV2Error(
                    "dangling_provider_reference",
                    "route references an unknown Provider",
                )
            if route.model_id not in model_set:
                raise RegistryV2Error(
                    "dangling_model_reference",
                    "route references an unknown public model",
                )
        if not any(route.enabled for route in routes):
            raise RegistryV2Error(
                "invalid_registry_v2",
                "registry must contain at least one enabled route",
            )

        object.__setattr__(self, "providers", providers)
        object.__setattr__(self, "models", models)
        object.__setattr__(self, "routes", routes)

    def get_model(self, model_id: str) -> PublicModelDefinition | None:
        safe_model_id = _reference("model_id", model_id)
        return next((item for item in self.models if item.model_id == safe_model_id), None)

    def get_route(self, route_id: str) -> ProviderRouteDefinition | None:
        safe_route_id = _reference("route_id", route_id)
        return next((item for item in self.routes if item.route_id == safe_route_id), None)

    def routes_for_model(
        self,
        model_id: str,
        *,
        enabled_only: bool = True,
    ) -> tuple[ProviderRouteDefinition, ...]:
        safe_model_id = _reference("model_id", model_id)
        return tuple(
            route
            for route in self.routes
            if route.model_id == safe_model_id and (route.enabled or not enabled_only)
        )

    def routes_for_provider(
        self,
        provider_id: str,
        *,
        enabled_only: bool = True,
    ) -> tuple[ProviderRouteDefinition, ...]:
        safe_provider_id = _provider_id("provider_id", provider_id)
        return tuple(
            route
            for route in self.routes
            if route.provider_id == safe_provider_id and (route.enabled or not enabled_only)
        )

    def to_public_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "providers": [item.to_public_dict() for item in self.providers],
            "models": [item.to_public_dict() for item in self.models],
            "routes": [item.to_public_dict() for item in self.routes],
        }


def registry_v2_from_dict(payload: Mapping[str, Any]) -> CanonicalRegistryV2:
    data = _strict_object(
        "registry",
        payload,
        allowed=frozenset({"schema_version", "providers", "models", "routes"}),
        required=frozenset({"schema_version", "providers", "models", "routes"}),
    )
    schema_version = data["schema_version"]
    if schema_version != REGISTRY_V2_SCHEMA:
        raise RegistryV2Error(
            "unsupported_registry_version",
            "registry schema_version is not supported",
        )

    raw_providers = _bounded_sequence("providers", data["providers"], maximum=MAX_PROVIDERS)
    raw_models = _bounded_sequence("models", data["models"], maximum=MAX_PUBLIC_MODELS)
    raw_routes = _bounded_sequence("routes", data["routes"], maximum=MAX_PROVIDER_ROUTES)

    providers: list[ProviderDefinition] = []
    for index, raw in enumerate(raw_providers):
        item = _strict_object(
            f"provider[{index}]",
            raw,
            allowed=frozenset({"provider_id", "display_name"}),
            required=frozenset({"provider_id", "display_name"}),
        )
        providers.append(
            ProviderDefinition(
                provider_id=item["provider_id"],
                display_name=item["display_name"],
            )
        )

    models: list[PublicModelDefinition] = []
    for index, raw in enumerate(raw_models):
        item = _strict_object(
            f"model[{index}]",
            raw,
            allowed=frozenset(
                {"model_id", "display_name", "context_window", "max_output_tokens"}
            ),
            required=frozenset({"model_id", "display_name"}),
        )
        models.append(
            PublicModelDefinition(
                model_id=item["model_id"],
                display_name=item["display_name"],
                context_window=item.get("context_window"),
                max_output_tokens=item.get("max_output_tokens"),
            )
        )

    routes: list[ProviderRouteDefinition] = []
    for index, raw in enumerate(raw_routes):
        item = _strict_object(
            f"route[{index}]",
            raw,
            allowed=frozenset(
                {
                    "route_id",
                    "model_id",
                    "provider_id",
                    "upstream_model",
                    "enabled",
                    "route_class",
                    "region",
                }
            ),
            required=frozenset(
                {
                    "route_id",
                    "model_id",
                    "provider_id",
                    "upstream_model",
                    "enabled",
                    "route_class",
                    "region",
                }
            ),
        )
        try:
            route_class = RouteClass(item["route_class"])
        except (TypeError, ValueError) as exc:
            raise RegistryV2Error(
                "invalid_registry_v2",
                "route_class must be local, domestic, or external",
            ) from exc
        routes.append(
            ProviderRouteDefinition(
                route_id=item["route_id"],
                model_id=item["model_id"],
                provider_id=item["provider_id"],
                upstream_model=item["upstream_model"],
                enabled=item["enabled"],
                route_class=route_class,
                region=item["region"],
            )
        )

    return CanonicalRegistryV2(
        providers=tuple(providers),
        models=tuple(models),
        routes=tuple(routes),
        schema_version=schema_version,
    )


def parse_registry_v2(raw_json: str) -> CanonicalRegistryV2:
    if not isinstance(raw_json, str) or not raw_json.strip():
        raise RegistryV2Error("invalid_registry_v2", "registry JSON must be non-empty text")
    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RegistryV2Error("invalid_registry_v2", "registry JSON is malformed") from exc
    if not isinstance(payload, dict):
        raise RegistryV2Error("invalid_registry_v2", "registry JSON must contain an object")
    return registry_v2_from_dict(payload)
