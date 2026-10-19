"""B14 model catalog data types, with entries loaded exclusively from b14_models.json."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.pilot.cost_evidence import ConfiguredCostEvidence

_CURRENCY_USD = "usd"

_KRW_PER_USD_CONFIGURED = 1380.0

KILO_SOURCE_CHECKED_AT = "2026-09-06"
SNAPSHOT_STATE_CONFIGURED = "configured_snapshot"

@dataclass(frozen=True)
class CatalogModel:
    model_id: str
    upstream_model: str
    display_name: str
    provider: str
    provider_type: str
    input_price_usd_per_1m: float | None
    output_price_usd_per_1m: float | None
    currency: str = _CURRENCY_USD
    context_window: int = 0
    korean_score: int = 0
    latency_ms: int = 0
    capabilities: frozenset = field(default_factory=frozenset)
    region: str = "외부"
    sort_order: int = 0
    enabled: bool = True
    credential_source: str = "platform_secret"
    platform_provider_id: str = "kilo"
    source: str = "kilo_official_gateway_models"
    source_checked_at: str = KILO_SOURCE_CHECKED_AT
    snapshot_state: str = SNAPSHOT_STATE_CONFIGURED

    @property
    def price_is_known(self) -> bool:
        return (
            self.input_price_usd_per_1m is not None
            and self.output_price_usd_per_1m is not None
        )

    def cost_usd_per_1k(self) -> float | None:
        """Return the configured combined price proxy per 1K tokens.

        This is the configured input+output snapshot rate scaled from per-1M
        to per-1K for legacy ranking/display consumers. It is not a measured
        request cost or invoice amount. Unknown/partial pricing remains None.
        """
        combined = ConfiguredCostEvidence(
            self.input_price_usd_per_1m,
            self.output_price_usd_per_1m,
            snapshot_state=self.snapshot_state,
            currency=self.currency,
        ).combined_rate_usd_per_1m()
        if combined is None:
            return None
        return combined / 1_000.0

    def estimate_cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        """Estimated cost from the configured price snapshot.

        Returns ``None`` when the price is unknown (not configured).
        Returns ``0.0`` when the price is known to be zero (free route).
        This is a snapshot estimate, never a live invoice amount.
        """
        if not self.price_is_known:
            return None
        in_cost = (prompt_tokens / 1_000_000) * self.input_price_usd_per_1m
        out_cost = (completion_tokens / 1_000_000) * self.output_price_usd_per_1m
        return round(in_cost + out_cost, 6)

    def estimate_cost_krw(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        usd = self.estimate_cost_usd(prompt_tokens, completion_tokens)
        if usd is None:
            return None
        return round(usd * _KRW_PER_USD_CONFIGURED, 1)


# The canonical B14 model registry installs entries from b14_models.json here.
# The catalog supports multiple providers; availability and rate limits are
# route/provider-specific, not a universal 200-requests-per-hour catalog rule.
CATALOG_MODELS: list[CatalogModel] = []


def ensure_free_tag_requires_known_zero_price(model: CatalogModel) -> None:
    """Reject a ``free`` capability tag on any model without a known zero price.

    Unknown-price models must never be implicitly classified as free:
    only entries with an explicit 0/0 price snapshot may carry ``free``.
    """
    if "free" in model.capabilities and (
        not model.price_is_known
        or model.input_price_usd_per_1m != 0.0
        or model.output_price_usd_per_1m != 0.0
    ):
        raise RuntimeError(
            f"catalog model {model.model_id} cannot be tagged free without known zero pricing"
        )


def is_evidenced_free(model: CatalogModel) -> bool:
    """Return True if the model carries the 'free' capability tag and evidenced 0/0 pricing."""
    return (
        "free" in model.capabilities
        and model.price_is_known
        and model.input_price_usd_per_1m == 0.0
        and model.output_price_usd_per_1m == 0.0
    )


for _catalog_model in CATALOG_MODELS:
    ensure_free_tag_requires_known_zero_price(_catalog_model)

CATALOG_BY_ID: dict[str, CatalogModel] = {}

# Canonical JSON is loaded once before consumers resolve routes or provider metadata.
from .model_registry_file import install_models as _install_models
_install_models()



def get_catalog_models() -> list[CatalogModel]:
    """Return all enabled catalog models."""
    return [m for m in CATALOG_MODELS if m.enabled]


def get_catalog_by_id(model_id: str) -> CatalogModel | None:
    """Look up a catalog model by its Business 14 model ID."""
    return CATALOG_BY_ID.get(model_id)


def get_catalog_upstream(model_id: str) -> str | None:
    """Return the upstream model ID for a catalog entry."""
    m = get_catalog_by_id(model_id)
    return m.upstream_model if m else None


def list_catalog_summaries() -> list[dict]:
    """Return catalog models as dicts for API/UI display."""
    return [
        {
            "model_id": m.model_id,
            "upstream_model": m.upstream_model,
            "name": m.display_name,
            "provider": m.provider,
            "provider_type": m.provider_type,
            "input_price_usd_per_1m": m.input_price_usd_per_1m,
            "output_price_usd_per_1m": m.output_price_usd_per_1m,
            "price_is_known": m.price_is_known,
            "context_window": m.context_window,
            "korean_score": m.korean_score,
            "latency_ms": m.latency_ms,
            "capabilities": sorted(m.capabilities),
            "region": m.region,
            "source": m.source,
            "source_checked_at": m.source_checked_at,
            "snapshot_state": m.snapshot_state,
        }
        for m in get_catalog_models()
    ]
