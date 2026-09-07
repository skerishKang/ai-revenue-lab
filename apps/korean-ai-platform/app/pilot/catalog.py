"""Model catalog for Business 14.

Defines the single Kilo Gateway free route model under owner decision #1933.

Source of truth
---------------
The entire legacy OpenRouter catalog has been wiped per owner decision #1933.
Business 14 connects exclusively to the Kilo Gateway free route:
- Model ID: ``kilo/nvidia-nemotron-3-ultra-550b-a55b-free``
- Upstream: ``nvidia/nemotron-3-ultra-550b-a55b:free``
- Provider: Kilo Gateway / NVIDIA
- Price: $0 / $0 (evidenced free)
- Rate Limit: 200 requests/hour (fails closed with 429 when exhausted)

Authentication
--------------
Authentication follows the platform_secret slot (KILO_API_KEY). If unset,
anonymous requests are permitted for the free tier per Kilo Gateway policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.pilot.cost_evidence import ConfiguredCostEvidence

_CURRENCY_USD = "usd"

_KRW_PER_USD_CONFIGURED = 1380.0

KILO_SOURCE_CHECKED_AT = "2026-09-06"
SNAPSHOT_STATE_CONFIGURED = "configured_snapshot"

TASK_TYPE_REQUIRED_CAPABILITIES: dict[str, frozenset] = {
    "general": frozenset({"chat"}),
    "korean": frozenset({"chat"}),
    "coding": frozenset({"chat", "coding"}),
    "document": frozenset({"chat"}),
    "batch": frozenset({"chat"}),
}


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


# Single provider & route under owner decision #1933: Kilo Gateway free route.
# Rate limit: 200 requests/hour. Fails closed with 429 when exhausted.
CATALOG_MODELS: list[CatalogModel] = [
    CatalogModel(
        model_id="kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        upstream_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        display_name="Kilo: NVIDIA Nemotron 3 Ultra (free)",
        provider="Kilo Gateway / NVIDIA",
        provider_type="platform",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1000000,
        korean_score=4,
        latency_ms=1500,
        capabilities=frozenset({"chat", "coding", "free"}),
        region="외부",
        sort_order=10,
        credential_source="platform_secret",
        platform_provider_id="kilo",
        source="kilo_official_gateway_models",
        source_checked_at=KILO_SOURCE_CHECKED_AT,
        snapshot_state=SNAPSHOT_STATE_CONFIGURED,
    ),
]

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

CATALOG_BY_ID: dict[str, CatalogModel] = {m.model_id: m for m in CATALOG_MODELS}


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


def filter_catalog(
    required_capabilities: list[str] | None = None,
    task_type: str | None = None,
) -> list[CatalogModel]:
    """Filter catalog models by capabilities and task type.

    ``task_type`` is enforced as a hard capability filter via
    ``TASK_TYPE_REQUIRED_CAPABILITIES`` (e.g. ``coding`` requires the
    ``coding`` capability, ``document`` requires ``long_context``).
    """
    candidates = get_catalog_models()
    req_set: set[str] = set(required_capabilities or [])
    if task_type and task_type in TASK_TYPE_REQUIRED_CAPABILITIES:
        req_set |= set(TASK_TYPE_REQUIRED_CAPABILITIES[task_type])
    if req_set:
        candidates = [m for m in candidates if req_set.issubset(m.capabilities)]
    return candidates


def _configured_cost_ranking_key(model: CatalogModel) -> tuple[int, float]:
    """Return the frozen configured-cost evidence ordering for one model.

    Known configured prices sort before unknown/partial prices. In particular,
    unknown must never collapse to the same key as an explicitly evidenced
    zero-price route.
    """
    return ConfiguredCostEvidence(
        model.input_price_usd_per_1m,
        model.output_price_usd_per_1m,
        snapshot_state=model.snapshot_state,
        currency=model.currency,
    ).ranking_key()


def select_by_optimize(
    candidates: list[CatalogModel],
    optimize_for: str,
    allow_external: bool,
    provider_order: list[str] | None = None,
    task_type: str | None = None,
) -> list[CatalogModel]:
    """Sort candidates deterministically, best-first.

    Enforced options:
    - ``provider_order``: providers listed first win (deterministic priority);
      unlisted providers keep their optimize_for order after listed ones.
    - ``task_type == "korean"``: korean_score becomes the leading scoring key.

    Ties are broken by sort_order then model_id for determinism.
    """
    key_fns = {
        "cost": lambda m: (
            0 if is_evidenced_free(m) else 1,
            *_configured_cost_ranking_key(m),
            m.sort_order,
            m.model_id,
        ),
        "latency": lambda m: (
            0 if is_evidenced_free(m) else 1,
            m.latency_ms,
            m.sort_order,
            m.model_id,
        ),
        "korean": lambda m: (
            0 if is_evidenced_free(m) else 1,
            -m.korean_score,
            m.sort_order,
            m.model_id,
        ),
        "balanced": lambda m: (
            0 if is_evidenced_free(m) else 1,
            -m.korean_score,
            *_configured_cost_ranking_key(m),
            m.latency_ms,
            m.sort_order,
            m.model_id,
        ),
    }

    base_key = key_fns.get(optimize_for, key_fns["balanced"])

    if task_type == "korean" and optimize_for != "korean":
        inner = base_key
        base_key = lambda m: (0 if is_evidenced_free(m) else 1, -m.korean_score, *inner(m))  # noqa: E731

    order = list(provider_order or [])
    if order:
        def _provider_rank(m: CatalogModel) -> int:
            try:
                return order.index(m.provider)
            except ValueError:
                return len(order)

        key_fn = lambda m: (_provider_rank(m), *base_key(m))  # noqa: E731
    else:
        key_fn = base_key

    return sorted(candidates, key=key_fn)
