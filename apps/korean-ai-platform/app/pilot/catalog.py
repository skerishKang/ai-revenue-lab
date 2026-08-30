"""Model catalog for Business 14 Alpha on OpenRouter.

Defines a curated set of OpenRouter models with pricing, capabilities,
and Korean-language suitability metadata for the Router Core.

Source of truth
---------------
Model IDs, display names, context lengths, and per-token prices are a
**configured snapshot** taken from the public OpenRouter Models API
(`GET https://openrouter.ai/api/v1/models`) at
`CATALOG_SOURCE_CHECKED_AT`. Prices are snapshot metadata, NOT a live
invoice — actual billing is between the owner and OpenRouter. A price of
``0.0`` means "known free at snapshot time"; ``None`` means "unknown".

The CLI entry point `python -m app.pilot.catalog validate-model-catalog`
re-checks the snapshot against the live Models API and reports availability
and price drift.

Authentication
--------------
Models API의 현재 인증 요구는 upstream 정책에 따르며,
키 없이 anonymous 검사를 시도할 수 있으나 성공을 보장하지 않는다.
If OPENROUTER_API_KEY is set, the Authorization Bearer header is used.
If no key is present, an anonymous request is attempted.
HTTP 401/403 is reported as `authentication_required`, not `network_skipped`.
Network errors are reported as `network_skipped`.
The catalog is only `checked=true` when the live check succeeds.

Free Models Router
------------------
``openrouter/free`` maps to upstream model ``openrouter/free`` — the
OpenRouter Free Models Router itself. The request body sends exactly
``"model": "openrouter/free"``; the concrete free model OpenRouter picks
is returned in the response ``model`` field and preserved separately as
``actual_response_model`` metadata.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.pilot.cost_evidence import ConfiguredCostEvidence
from app.pilot.openrouter_config import openrouter_config

_CURRENCY_USD = "usd"

_KRW_PER_USD_CONFIGURED = 1380.0

CATALOG_SOURCE = "openrouter_models_api"
CATALOG_SOURCE_URL = "https://openrouter.ai/api/v1/models"
CATALOG_SOURCE_CHECKED_AT = "2026-08-02T09:55:02Z"
OX_ALPHA_SOURCE_CHECKED_AT = "2026-08-26"
SNAPSHOT_STATE_CONFIGURED = "configured_snapshot"

TASK_TYPE_REQUIRED_CAPABILITIES: dict[str, frozenset] = {
    "general": frozenset({"chat"}),
    "korean": frozenset({"chat"}),
    "coding": frozenset({"chat", "coding"}),
    "document": frozenset({"chat", "long_context"}),
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
    credential_source: str = "openrouter"
    platform_provider_id: str = ""
    source: str = CATALOG_SOURCE
    source_checked_at: str = CATALOG_SOURCE_CHECKED_AT
    snapshot_state: str = SNAPSHOT_STATE_CONFIGURED

    @property
    def price_is_known(self) -> bool:
        return (
            self.input_price_usd_per_1m is not None
            and self.output_price_usd_per_1m is not None
        )

    def cost_usd_per_1k(self) -> float | None:
        if not self.price_is_known:
            return None
        return None

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


CATALOG_MODELS: list[CatalogModel] = [
    CatalogModel(
        model_id="stealth/ox-alpha",
        upstream_model="stealth/ox-alpha",
        display_name="Ox Alpha",
        provider="Stealth",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1048576,
        korean_score=4,
        latency_ms=2000,
        capabilities=frozenset({"chat", "image", "long_context", "coding", "free"}),
        region="외부",
        sort_order=60,
        source_checked_at=OX_ALPHA_SOURCE_CHECKED_AT,
    ),
    CatalogModel(
        model_id="openrouter/free",
        upstream_model="openrouter/free",
        display_name="Free Models Router (무료 라우터)",
        provider="OpenRouter (free router)",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=200000,
        korean_score=3,
        latency_ms=700,
        capabilities=frozenset({"chat", "free"}),
        region="외부",
        sort_order=50,
    ),
    CatalogModel(
        model_id="google/gemini-2.5-flash",
        upstream_model="google/gemini-2.5-flash",
        display_name="Google: Gemini 2.5 Flash",
        provider="Google",
        provider_type="external",
        input_price_usd_per_1m=0.30,
        output_price_usd_per_1m=2.50,
        currency="usd",
        context_window=1048576,
        korean_score=5,
        latency_ms=750,
        capabilities=frozenset({"chat", "image", "long_context", "coding"}),
        region="외부",
        sort_order=10,
    ),
    CatalogModel(
        model_id="deepseek/deepseek-chat",
        upstream_model="deepseek/deepseek-chat",
        display_name="DeepSeek: DeepSeek V3",
        provider="DeepSeek",
        provider_type="external",
        input_price_usd_per_1m=0.2574,
        output_price_usd_per_1m=1.0287,
        currency="usd",
        context_window=163840,
        korean_score=3,
        latency_ms=500,
        capabilities=frozenset({"chat", "coding"}),
        region="외부",
        sort_order=30,
    ),
    CatalogModel(
        model_id="mistralai/mistral-small-3.2-24b-instruct",
        upstream_model="mistralai/mistral-small-3.2-24b-instruct",
        display_name="Mistral: Mistral Small 3.2 24B",
        provider="Mistral",
        provider_type="external",
        input_price_usd_per_1m=0.075,
        output_price_usd_per_1m=0.20,
        currency="usd",
        context_window=256000,
        korean_score=3,
        latency_ms=450,
        capabilities=frozenset({"chat", "long_context"}),
        region="외부",
        sort_order=35,
    ),
    CatalogModel(
        model_id="anthropic/claude-sonnet-4.5",
        upstream_model="anthropic/claude-sonnet-4.5",
        display_name="Anthropic: Claude Sonnet 4.5",
        provider="Anthropic",
        provider_type="external",
        input_price_usd_per_1m=3.00,
        output_price_usd_per_1m=15.00,
        currency="usd",
        context_window=1000000,
        korean_score=5,
        latency_ms=1100,
        capabilities=frozenset({"chat", "coding", "long_context"}),
        region="외부",
        sort_order=5,
    ),
    CatalogModel(
        model_id="agnes-ai/agnes-2.5-flash",
        upstream_model="agnes-2.5-flash",
        display_name="Agnes AI: Agnes 2.5 Flash",
        provider="Agnes AI",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=200000,
        korean_score=4,
        latency_ms=900,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=70,
        credential_source="platform_secret",
        platform_provider_id="agnes-ai",
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
            *_configured_cost_ranking_key(m),
            m.sort_order,
            m.model_id,
        ),
        "latency": lambda m: (m.latency_ms, m.sort_order, m.model_id),
        "korean": lambda m: (-m.korean_score, m.sort_order, m.model_id),
        "balanced": lambda m: (
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
        base_key = lambda m: (-m.korean_score, *inner(m))  # noqa: E731

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_live_models(transport=None) -> dict:
    """Fetch the OpenRouter Models API with proper auth handling.

    Models API의 현재 인증 요구는 upstream 정책에 따르며,
    키 없이 anonymous 검사를 시도할 수 있으나 성공을 보장하지 않는다.

    If OPENROUTER_API_KEY is set, the Authorization Bearer header is used.
    If no key is present, an anonymous request is attempted.

    Args:
        transport: Optional httpx transport for testing (MockTransport).

    Returns ``{"ok": True, "checked_at": ..., "models_by_id": {...}}`` on
    success, ``{"ok": False, "reason": "authentication_required"}`` on
    HTTP 401/403, or ``{"ok": False, "reason": "network_skipped: ..."}``
    on network errors.
    """
    import httpx

    base_url = openrouter_config.base_url.rstrip("/")
    try:
        openrouter_config.validate_base_url()
    except ValueError as e:
        return {"ok": False, "reason": f"invalid base URL: {e}"}

    headers: dict[str, str] = {"Accept": "application/json"}
    if openrouter_config.has_key:
        headers["Authorization"] = f"Bearer {openrouter_config.api_key}"

    client_kwargs: dict = {
        "timeout": httpx.Timeout(None, connect=10.0, read=30.0, write=10.0, pool=10.0),
    }
    if transport is not None:
        client_kwargs["transport"] = transport

    try:
        with httpx.Client(**client_kwargs) as client:
            resp = client.get(
                f"{base_url}/models",
                headers=headers,
                follow_redirects=False,
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        return {"ok": False, "reason": f"network_skipped: {type(e).__name__}"}

    if resp.status_code in (401, 403):
        return {"ok": False, "reason": "authentication_required"}

    if resp.status_code != 200:
        return {"ok": False, "reason": f"upstream returned HTTP {resp.status_code}"}

    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return {"ok": False, "reason": "upstream returned non-JSON"}

    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        return {"ok": False, "reason": "upstream response shape unexpected"}

    models_by_id: dict[str, dict] = {}
    for item in data["data"]:
        if isinstance(item, dict) and item.get("id"):
            models_by_id[item["id"]] = item

    return {"ok": True, "checked_at": _utc_now_iso(), "models_by_id": models_by_id}


def _live_price_per_1m(item: dict, field_name: str) -> float | None:
    pricing = item.get("pricing")
    if not isinstance(pricing, dict):
        return None
    raw = pricing.get(field_name)
    try:
        return float(raw) * 1_000_000
    except (TypeError, ValueError):
        return None


def validate_catalog_ids_live(transport=None) -> dict:
    """Check the configured catalog snapshot against the live Models API.

    Models API의 현재 인증 요구는 upstream 정책에 따르며,
    키 없이 anonymous 검사를 시도할 수 있으나 성공을 보장하지 않는다.

    If OPENROUTER_API_KEY is set, the Authorization Bearer header is used.
    If no key is present, an anonymous request is attempted.

    HTTP 401/403 is reported as `authentication_required` (not `network_skipped`).
    Network errors are reported as `network_skipped`.
    The catalog is only `checked=true` when the live check succeeds.

    Args:
        transport: Optional httpx transport for testing (MockTransport).

    Returns a dict with:
        - checked: bool (live check actually ran and succeeded)
        - skipped: bool (network/config/auth prevented the check)
        - reason: str (when skipped: "authentication_required", "network_skipped: ...", etc.)
        - checked_at: str (UTC, when the live check ran)
        - source: str
        - unavailable: list[str] (catalog model_ids not found upstream)
        - available: list[str]
        - price_drift: list[dict] (snapshot vs live per-1M price differences)
    """
    result: dict = {
        "checked": False,
        "skipped": False,
        "reason": "",
        "checked_at": "",
        "source": CATALOG_SOURCE,
        "source_url": CATALOG_SOURCE_URL,
        "unavailable": [],
        "available": [],
        "price_drift": [],
    }

    live = fetch_live_models(transport=transport)
    if not live["ok"]:
        result["skipped"] = True
        result["reason"] = live["reason"]
        return result

    result["checked"] = True
    result["checked_at"] = live["checked_at"]
    models_by_id = live["models_by_id"]

    for cm in CATALOG_MODELS:
        item = models_by_id.get(cm.upstream_model)
        if item is None:
            result["unavailable"].append(cm.model_id)
            continue
        result["available"].append(cm.model_id)

        live_in = _live_price_per_1m(item, "prompt")
        live_out = _live_price_per_1m(item, "completion")
        if (
            live_in is not None
            and live_out is not None
            and cm.input_price_usd_per_1m is not None
            and cm.output_price_usd_per_1m is not None
            and (
                abs(live_in - cm.input_price_usd_per_1m) > 1e-9
                or abs(live_out - cm.output_price_usd_per_1m) > 1e-9
            )
        ):
            result["price_drift"].append({
                "model_id": cm.model_id,
                "snapshot_input_per_1m": cm.input_price_usd_per_1m,
                "snapshot_output_per_1m": cm.output_price_usd_per_1m,
                "live_input_per_1m": round(live_in, 6),
                "live_output_per_1m": round(live_out, 6),
            })

    return result


def _cli_validate_model_catalog() -> int:
    """CLI entry point: validate the model catalog against live OpenRouter.

    Usage:
        python -m app.pilot.catalog validate-model-catalog
    """
    print("=== Business 14 Model Catalog Validation ===")
    print(f"Source: {CATALOG_SOURCE} ({CATALOG_SOURCE_URL})")
    print(f"Configured snapshot checked_at: {CATALOG_SOURCE_CHECKED_AT}")
    print(f"Snapshot state: {SNAPSHOT_STATE_CONFIGURED} (not a live invoice)")
    print(f"Provider mode: {openrouter_config.provider_mode}")
    print()

    for cm in CATALOG_MODELS:
        price = (
            f"input: ${cm.input_price_usd_per_1m}/1M | output: ${cm.output_price_usd_per_1m}/1M"
            if cm.price_is_known
            else "price: unknown (null)"
        )
        print(f"  {cm.model_id}")
        print(f"    upstream: {cm.upstream_model}")
        print(f"    display: {cm.display_name}")
        print(f"    provider: {cm.provider}")
        print(f"    {price}")
        print(f"    context: {cm.context_window}")
        print(f"    capabilities: {sorted(cm.capabilities)}")
        print(f"    korean_score: {cm.korean_score} | latency: {cm.latency_ms}ms")
        print()

    result = validate_catalog_ids_live()
    print("=== Live validation (public Models API) ===")
    if result["skipped"]:
        reason = result["reason"]
        if reason == "authentication_required":
            print("AUTHENTICATION_REQUIRED: The upstream Models API returned HTTP 401/403.")
            print("An OPENROUTER_API_KEY may be required for this endpoint.")
        elif reason.startswith("network_skipped:"):
            print(f"NETWORK_SKIPPED: {reason}")
        else:
            print(f"SKIPPED: {reason}")
        print()
        print("Catalog model IDs/prices remain a configured snapshot.")
        print("Re-run with network access and/or a valid API key to check against the live Models API.")
        return 0

    print(f"checked_at: {result['checked_at']}")
    if result["available"]:
        print(f"Available upstream models: {result['available']}")
    if result["unavailable"]:
        print(f"UNAVAILABLE upstream models: {result['unavailable']}")
        print("These catalog entries map to upstream IDs not found on OpenRouter.")
        print("Edit app/pilot/catalog.py to update upstream_model mappings.")
    if result["price_drift"]:
        print("PRICE DRIFT between configured snapshot and live metadata:")
        for d in result["price_drift"]:
            print(
                f"  {d['model_id']}: snapshot ${d['snapshot_input_per_1m']}/${d['snapshot_output_per_1m']}"
                f" -> live ${d['live_input_per_1m']}/${d['live_output_per_1m']} (per 1M)"
            )
        print("Update the catalog snapshot (prices + source_checked_at) before relying on estimates.")
    if not result["unavailable"] and not result["price_drift"]:
        print("All catalog upstream models verified; snapshot prices match live metadata.")
    return 1 if result["unavailable"] else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "validate-model-catalog":
        sys.exit(_cli_validate_model_catalog())
    print(f"Unknown command '{mode}'. Use: validate-model-catalog")
    sys.exit(2)