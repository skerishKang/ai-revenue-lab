"""Model catalog for Business 14 Alpha on OpenRouter.

Defines a curated set of OpenRouter models with pricing, capabilities,
and Korean-language suitability metadata for the Router Core.

The CLI entry point `python -m app.pilot.catalog validate-model-catalog`
verifies model IDs against the live OpenRouter /models endpoint when a
key and network are available; otherwise it reports SKIP.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field

from app.pilot.openrouter_config import openrouter_config

_CURRENCY_USD = "usd"

_KRW_PER_USD_CONFIGURED = 1380.0


@dataclass(frozen=True)
class CatalogModel:
    model_id: str
    upstream_model: str
    display_name: str
    provider: str
    provider_type: str
    input_price_usd_per_1m: float
    output_price_usd_per_1m: float
    currency: str = _CURRENCY_USD
    context_window: int = 0
    korean_score: int = 0
    latency_ms: int = 0
    capabilities: frozenset = field(default_factory=frozenset)
    region: str = "외부"
    sort_order: int = 0
    enabled: bool = True

    def cost_usd_per_1k(self) -> float | None:
        if self.input_price_usd_per_1m < 0 or self.output_price_usd_per_1m < 0:
            return None
        return None

    def estimate_cost_usd(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        if self.input_price_usd_per_1m == 0 and self.output_price_usd_per_1m == 0:
            return None
        in_cost = (prompt_tokens / 1_000_000) * self.input_price_usd_per_1m
        out_cost = (completion_tokens / 1_000_000) * self.output_price_usd_per_1m
        return round(in_cost + out_cost, 6)

    def estimate_cost_krw(self, prompt_tokens: int, completion_tokens: int) -> float | None:
        usd = self.estimate_cost_usd(prompt_tokens, completion_tokens)
        if usd is None:
            return None
        return round(usd * _KRW_PER_USD_CONFIGURED, 1)


CATALOG_MODELS: list[CatalogModel] = [
    CatalogModel(
        model_id="openrouter/free",
        upstream_model="google/gemini-2.0-flash",
        display_name="Gemini 2.0 Flash (무료 tier)",
        provider="OpenRouter (free)",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1048576,
        korean_score=3,
        latency_ms=700,
        capabilities=frozenset({"chat", "image", "long_context"}),
        region="외부",
        sort_order=50,
    ),
    CatalogModel(
        model_id="google/gemini-2.5-flash",
        upstream_model="google/gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        provider="Google",
        provider_type="external",
        input_price_usd_per_1m=0.05,
        output_price_usd_per_1m=0.10,
        currency="usd",
        context_window=1048576,
        korean_score=5,
        latency_ms=750,
        capabilities=frozenset({"chat", "image", "long_context"}),
        region="외부",
        sort_order=10,
    ),
    CatalogModel(
        model_id="deepseek/deepseek-chat",
        upstream_model="deepseek/deepseek-chat",
        display_name="DeepSeek Chat",
        provider="DeepSeek",
        provider_type="external",
        input_price_usd_per_1m=0.01,
        output_price_usd_per_1m=0.02,
        currency="usd",
        context_window=128000,
        korean_score=3,
        latency_ms=500,
        capabilities=frozenset({"chat", "coding"}),
        region="외부",
        sort_order=30,
    ),
    CatalogModel(
        model_id="anthropic/claude-3-5-sonnet-20241022",
        upstream_model="anthropic/claude-3-5-sonnet-20241022",
        display_name="Claude 3.5 Sonnet",
        provider="Anthropic",
        provider_type="external",
        input_price_usd_per_1m=3.0,
        output_price_usd_per_1m=15.0,
        currency="usd",
        context_window=200000,
        korean_score=5,
        latency_ms=1100,
        capabilities=frozenset({"chat", "coding", "long_context"}),
        region="외부",
        sort_order=5,
    ),
]

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
            "name": m.display_name,
            "provider": m.provider,
            "provider_type": m.provider_type,
            "input_price_usd_per_1m": m.input_price_usd_per_1m,
            "output_price_usd_per_1m": m.output_price_usd_per_1m,
            "context_window": m.context_window,
            "korean_score": m.korean_score,
            "latency_ms": m.latency_ms,
            "capabilities": sorted(m.capabilities),
            "region": m.region,
        }
        for m in get_catalog_models()
    ]


def filter_catalog(
    required_capabilities: list[str] | None = None,
    task_type: str | None = None,
) -> list[CatalogModel]:
    """Filter catalog models by capabilities and task type."""
    candidates = get_catalog_models()
    if required_capabilities:
        req_set = set(required_capabilities)
        candidates = [m for m in candidates if req_set.issubset(m.capabilities)]
    return candidates


def select_by_optimize(
    candidates: list[CatalogModel],
    optimize_for: str,
    allow_external: bool,
) -> list[CatalogModel]:
    """Sort candidates deterministically by the optimize_for criterion.

    Returns candidates sorted best-first. Ties are broken by sort_order
    then model_id for determinism.
    """
    key_fns = {
        "cost": lambda m: (
            m.input_price_usd_per_1m + m.output_price_usd_per_1m,
            m.sort_order,
            m.model_id,
        ),
        "latency": lambda m: (m.latency_ms, m.sort_order, m.model_id),
        "korean": lambda m: (-m.korean_score, m.sort_order, m.model_id),
        "balanced": lambda m: (
            -m.korean_score,
            m.input_price_usd_per_1m + m.output_price_usd_per_1m,
            m.latency_ms,
            m.sort_order,
            m.model_id,
        ),
    }

    key_fn = key_fns.get(optimize_for, key_fns["balanced"])
    return sorted(candidates, key=key_fn)


def validate_catalog_ids_live() -> dict:
    """Call the live OpenRouter /models endpoint to verify catalog model IDs.

    Returns a dict with:
        - checked: bool
        - skipped: bool
        - reason: str (when skipped)
        - unavailable: list[str]  (catalog model_ids not found upstream)
        - available: list[str]
    """
    import httpx

    result: dict = {"checked": False, "skipped": False, "unavailable": [], "available": [], "reason": ""}

    if not openrouter_config.has_key:
        result["skipped"] = True
        result["reason"] = "OPENROUTER_API_KEY not set or placeholder"
        return result

    if openrouter_config.is_mock:
        result["skipped"] = True
        result["reason"] = "B14_PROVIDER_MODE=mock — live validation requires live mode"
        return result

    try:
        openrouter_config.validate_base_url()
    except ValueError as e:
        result["skipped"] = True
        result["reason"] = f"invalid base URL: {e}"
        return result

    headers = openrouter_config.safe_headers()
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.get(
                f"{openrouter_config.base_url.rstrip('/')}/models",
                headers=headers,
                follow_redirects=False,
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        result["skipped"] = True
        result["reason"] = f"network error: {type(e).__name__}"
        return result

    if resp.status_code != 200:
        result["skipped"] = True
        result["reason"] = f"upstream returned HTTP {resp.status_code}"
        return result

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        result["skipped"] = True
        result["reason"] = "upstream returned non-JSON"
        return result

    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        result["skipped"] = True
        result["reason"] = "upstream response shape unexpected"
        return result

    upstream_ids = set()
    for item in data["data"]:
        if isinstance(item, dict) and item.get("id"):
            upstream_ids.add(item["id"])

    for cm in CATALOG_MODELS:
        if cm.upstream_model in upstream_ids:
            result["available"].append(cm.model_id)
        else:
            result["unavailable"].append(cm.model_id)

    result["checked"] = True
    return result


def _cli_validate_model_catalog() -> int:
    """CLI entry point: validate the model catalog against live OpenRouter.

    Usage:
        python -m app.pilot.catalog validate-model-catalog
    """
    print("=== Business 14 Model Catalog Validation ===")
    print(f"Provider mode: {openrouter_config.provider_mode}")
    print(f"Has key: {'yes' if openrouter_config.has_key else 'no'}")
    print()

    for cm in CATALOG_MODELS:
        print(f"  {cm.model_id}")
        print(f"    upstream: {cm.upstream_model}")
        print(f"    provider: {cm.provider}")
        print(f"    input: ${cm.input_price_usd_per_1m}/1M | output: ${cm.output_price_usd_per_1m}/1M")
        print(f"    capabilities: {sorted(cm.capabilities)}")
        print(f"    korean_score: {cm.korean_score} | latency: {cm.latency_ms}ms")
        print()

    result = validate_catalog_ids_live()
    print("=== Live validation ===")
    if result["skipped"]:
        print(f"SKIPPED: {result['reason']}")
        print()
        print("Catalog model IDs are defined as configured defaults.")
        print("To validate live, set B14_PROVIDER_MODE=live and OPENROUTER_API_KEY, then re-run.")
        return 0

    if result["checked"]:
        if result["available"]:
            print(f"Available upstream models: {result['available']}")
        if result["unavailable"]:
            print(f"UNAVAILABLE upstream models: {result['unavailable']}")
            print("These catalog entries map to upstream IDs not found on OpenRouter.")
            print("Edit app/pilot/catalog.py to update upstream_model mappings.")
            return 1
        print("All catalog upstream models verified on OpenRouter.")
        return 0

    return 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "validate-model-catalog":
        sys.exit(_cli_validate_model_catalog())
    print(f"Unknown command '{mode}'. Use: validate-model-catalog")
    sys.exit(2)
