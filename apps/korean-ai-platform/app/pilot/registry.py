"""Multi-provider registry for BYOK Gateway Pilot (Phase 2).

Parses JSON from BUSINESS14_PROVIDER_REGISTRY_JSON environment variable.
Validates provider/model configuration and provides accessors.

Legacy single-provider fallback via BUSINESS14_PILOT_* env vars is supported
when registry is not configured.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.pilot.config import pilot_settings

logger = logging.getLogger("korean-ai-platform.pilot")


@dataclass(frozen=True)
class RouteTarget:
    """Resolved routing target for a single provider call."""

    provider_id: str
    provider_name: str
    model_id: str
    upstream_model: str
    base_url: str
    timeout_seconds: int


@dataclass(frozen=True)
class ProviderConfig:
    """A configured upstream provider."""

    provider_id: str
    display_name: str
    base_url: str
    timeout_seconds: int
    models: tuple["ModelConfig", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ModelConfig:
    """A model that belongs to a specific provider."""

    model_id: str
    upstream_model: str
    display_name: str
    provider_id: str
    enabled: bool = True


class RegistryInvalidError(ValueError):
    """Raised when the provider registry JSON is malformed or invalid."""


class RegistryNotConfiguredError(RuntimeError):
    """Raised when neither registry nor legacy settings are configured."""


def _validate_url(url: str) -> None:
    """Validate a provider base URL (SSRF prevention)."""
    from urllib.parse import urlparse
    import ipaddress

    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise RegistryInvalidError(f"Provider URL must use https: {url}")
    if parsed.username or parsed.password:
        raise RegistryInvalidError("Provider URL must not contain credentials")
    if parsed.fragment:
        raise RegistryInvalidError("Provider URL must not contain a fragment")
    host = parsed.hostname
    if not host:
        raise RegistryInvalidError("Provider URL must have a hostname")
    host_lower = host.lower()
    if host_lower in ("localhost", "localhost.localdomain", "local", "broadcasthost"):
        raise RegistryInvalidError("Provider URL must not point to localhost")
    try:
        addr = ipaddress.ip_address(host_lower)
    except ValueError:
        return
    if addr.is_loopback or addr.is_private or addr.is_link_local or addr.is_unspecified or addr.is_multicast or addr.is_reserved:
        raise RegistryInvalidError(f"Provider URL points to non-routable address: {host}")


class ProviderRegistry:
    """Parsed and validated provider registry.

    Provides:
    - get_model(model_id: str) -> RouteTarget | None
    - list_models() -> list[dict]
    - provider_summary() -> list[dict]
    - configured: bool
    - provider_count: int
    - model_count: int
    - disabled_model_count: int
    - parse_error: str | None
    """

    def __init__(self, raw_json: str = "") -> None:
        self._providers: list[ProviderConfig] = []
        self._model_map: dict[str, RouteTarget] = {}
        self._disabled_model_ids: set[str] = set()
        self._providers_map: dict[str, ProviderConfig] = {}
        self._parse_error: str | None = None

        if not raw_json:
            raw_json = pilot_settings.provider_registry_json

        if not raw_json:
            return  # not configured

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError as e:
            self._parse_error = f"Invalid registry JSON: {e}"
            return

        if not isinstance(data, list):
            self._parse_error = "Registry must be a JSON array of providers"
            return

        if len(data) == 0:
            self._parse_error = "Registry must contain at least one provider"
            return

        seen_provider_ids: set[str] = set()
        seen_model_ids: set[str] = set()
        providers: list[ProviderConfig] = []
        total_enabled_count = 0

        for idx, entry in enumerate(data):
            if not isinstance(entry, dict):
                self._parse_error = f"Provider entry {idx} must be an object"
                return

            provider_id = (entry.get("provider_id") or "").strip()
            if not provider_id:
                self._parse_error = f"Provider entry {idx} has empty provider_id"
                return
            if provider_id in seen_provider_ids:
                self._parse_error = f"Duplicate provider_id: {provider_id}"
                return
            seen_provider_ids.add(provider_id)

            display_name = (entry.get("display_name") or provider_id).strip()
            base_url = (entry.get("base_url") or "").strip()
            if not base_url:
                self._parse_error = f"Provider '{provider_id}' has empty base_url"
                return
            try:
                _validate_url(base_url)
            except RegistryInvalidError as e:
                self._parse_error = str(e)
                return

            timeout = entry.get("timeout_seconds", 30)
            if not isinstance(timeout, int) or timeout < 1 or timeout > 120:
                self._parse_error = f"Provider '{provider_id}' has invalid timeout_seconds: {timeout}"
                return

            raw_models = entry.get("models")
            if not isinstance(raw_models, list) or not raw_models:
                self._parse_error = f"Provider '{provider_id}' has no models"
                return

            models: list[ModelConfig] = []
            for midx, mentry in enumerate(raw_models):
                if not isinstance(mentry, dict):
                    self._parse_error = f"Provider '{provider_id}' model {midx} must be an object"
                    return

                model_id = (mentry.get("model_id") or "").strip()
                if not model_id:
                    self._parse_error = f"Provider '{provider_id}' model {midx} has empty model_id"
                    return
                if model_id in seen_model_ids:
                    self._parse_error = f"Duplicate model_id across providers: {model_id}"
                    return
                seen_model_ids.add(model_id)

                upstream = (mentry.get("upstream_model") or "").strip()
                if not upstream:
                    self._parse_error = f"Provider '{provider_id}' model '{model_id}' has empty upstream_model"
                    return

                model_name = (mentry.get("display_name") or model_id).strip()
                enabled_raw = mentry.get("enabled", True)
                if not isinstance(enabled_raw, bool):
                    self._parse_error = f"Provider '{provider_id}' model '{model_id}' enabled must be a boolean"
                    return

                models.append(ModelConfig(
                    model_id=model_id,
                    upstream_model=upstream,
                    display_name=model_name,
                    provider_id=provider_id,
                    enabled=enabled_raw,
                ))

                if enabled_raw:
                    total_enabled_count += 1
                else:
                    self._disabled_model_ids.add(model_id)

            provider_models = tuple(models)
            providers.append(ProviderConfig(
                provider_id=provider_id,
                display_name=display_name,
                base_url=base_url,
                timeout_seconds=timeout,
                models=provider_models,
            ))

        # Check that at least one model is enabled across the registry
        if total_enabled_count == 0:
            self._parse_error = "Registry must have at least one enabled model"
            return

        self._providers = providers
        self._providers_map = {p.provider_id: p for p in providers}

        # Build model map (enabled only)
        for provider in providers:
            for model in provider.models:
                if not model.enabled:
                    continue
                self._model_map[model.model_id] = RouteTarget(
                    provider_id=provider.provider_id,
                    provider_name=provider.display_name,
                    model_id=model.model_id,
                    upstream_model=model.upstream_model,
                    base_url=provider.base_url,
                    timeout_seconds=provider.timeout_seconds,
                )

    @property
    def parse_error(self) -> str | None:
        return self._parse_error

    @property
    def configured(self) -> bool:
        return len(self._providers) > 0

    @property
    def provider_count(self) -> int:
        return len(self._providers)

    @property
    def model_count(self) -> int:
        return len(self._model_map)

    @property
    def disabled_model_count(self) -> int:
        return len(self._disabled_model_ids)

    def get_model(self, model_id: str) -> RouteTarget | None:
        """Resolve a model ID to its RouteTarget (None if disabled or unknown)."""
        return self._model_map.get(model_id)

    def is_model_disabled(self, model_id: str) -> bool:
        """Check if a model ID exists but is disabled."""
        return model_id in self._disabled_model_ids

    def list_models(self) -> list[dict]:
        """Return a list of model dicts for API/UI display."""
        result: list[dict] = []
        for provider in self._providers:
            for model in provider.models:
                if not model.enabled:
                    continue
                result.append({
                    "id": model.model_id,
                    "name": model.display_name,
                    "provider_id": provider.provider_id,
                    "provider_name": provider.display_name,
                    "pilot_available": True,
                    "input_krw_per_1k": None,
                    "output_krw_per_1k": None,
                    "tags": ["pilot", "byok", "multi-provider"],
                })
        return result

    def provider_summary(self) -> list[dict]:
        """Return provider summary for health endpoint."""
        return [
            {
                "provider_id": p.provider_id,
                "configured": True,
                "model_count": sum(1 for m in p.models if m.enabled),
            }
            for p in self._providers
        ]

    def get_legacy_target(self) -> RouteTarget | None:
        """Build a RouteTarget from Phase 1 single-provider env vars."""
        if not pilot_settings.pilot_base_url or not pilot_settings.pilot_model_id:
            return None
        upstream = pilot_settings.pilot_upstream_model or pilot_settings.pilot_model_id
        return RouteTarget(
            provider_id=pilot_settings.pilot_provider_id,
            provider_name=pilot_settings.pilot_provider_id.replace("-", " ").title(),
            model_id=pilot_settings.pilot_model_id,
            upstream_model=upstream,
            base_url=pilot_settings.pilot_base_url,
            timeout_seconds=pilot_settings.pilot_timeout_seconds,
        )


# Singleton registry, lazily initialized
_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    """Get or initialize the provider registry singleton."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the registry (for testing)."""
    global _registry
    _registry = None
