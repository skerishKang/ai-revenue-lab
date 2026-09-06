"""SenseNova Provider onboarding for Business 14 (#2003).

Owner-provisioned direct route: the Kilo free route showed intermittent
502/504 episodes, and the owner supplied a SenseNova plan key (registered
out-of-band as the Worker secret/env ``PADIEM_SENSENOVA_API_KEY`` — the
value never enters this repository). SenseNova's token endpoint is
OpenAI-compatible, so this provider reuses the generic platform adapter.

Contract points:
- model_id ``sensenova/sensenova-6.8-flash-lite``, upstream
  ``sensenova-6.8-flash-lite``, base origin ``https://token.sensenova.ai/v1``
  (measured live 2026-09-06: 200 with completion).
- Bearer auth from env only. Missing key -> explicit not-ready
  (fail-closed): unlike the keyless Kilo free tier, anonymous SenseNova
  requests are NEVER sent.
- Error normalization at the adapter boundary (see
  ``platform._raise_upstream_error``): a provider 429 whose body carries
  ``rate_limit_error`` / "Server is busy" is transient capacity pressure,
  not an hourly quota, so it maps to the retryable class
  ``upstream_rate_limited`` (retryable=True, UpstreamTimeout-equivalent)
  and #1988's same-route retry absorbs it.
- Pricing: cost is borne by the owner's SenseNova plan; no per-token price
  is fabricated (prices stay None -> price_is_known False).
- The Kilo entries remain registered as the secondary route (#1952).
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

SENSENOVA_PROVIDER_ID = "sensenova"
SENSENOVA_BASE_ORIGIN = "https://token.sensenova.ai/v1"
SENSENOVA_ALLOWED_HOST = "token.sensenova.ai"
SENSENOVA_CREDENTIAL_BINDING = "PADIEM_SENSENOVA_API_KEY"

SENSENOVA_MODEL_ID = "sensenova/sensenova-6.8-flash-lite"
SENSENOVA_UPSTREAM_MODEL = "sensenova-6.8-flash-lite"
SENSENOVA_SOURCE_CHECKED_AT = "2026-09-06"

# Transient capacity-pressure markers observed from the SenseNova gateway.
# A 429 carrying any of these is retryable ("Server is busy" episodes were
# measured on 2026-09-06 and absorbed by a retry). Matched case-insensitively
# against the provider error body's type/code/message fields.
SENSENOVA_TRANSIENT_429_MARKERS = (
    "server is busy",
    "rate_limit_error",
)


def is_transient_busy_429(body_text: str) -> bool:
    """Return True when a 429 body indicates transient capacity pressure."""
    lowered = body_text.lower()
    return any(marker in lowered for marker in SENSENOVA_TRANSIENT_429_MARKERS)


def register_sensenova_provider() -> None:
    """Idempotently register the owner-provisioned SenseNova direct route.

    The credential source is PLATFORM_SECRET with the env binding name only;
    the key value lives in the Worker secret store and is resolved at
    request time by the platform adapter.
    """

    if get_platform_provider(SENSENOVA_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=SENSENOVA_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=SENSENOVA_CREDENTIAL_BINDING,
                base_origin=SENSENOVA_BASE_ORIGIN,
                allowed_hosts=(SENSENOVA_ALLOWED_HOST,),
                enabled=True,
            )
        )

    if SENSENOVA_MODEL_ID in CATALOG_BY_ID:
        return

    model = CatalogModel(
        model_id=SENSENOVA_MODEL_ID,
        upstream_model=SENSENOVA_UPSTREAM_MODEL,
        display_name="SenseNova: 6.8 Flash Lite (owner plan)",
        provider="SenseNova",
        provider_type="platform",
        # Owner-plan cost: no per-token price is fabricated.
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=256_000,
        korean_score=0,
        latency_ms=0,
        capabilities=frozenset({"chat", "coding"}),
        region="외부",
        sort_order=85,
        credential_source="platform_secret",
        platform_provider_id=SENSENOVA_PROVIDER_ID,
        source="sensenova_token_api_measured",
        source_checked_at=SENSENOVA_SOURCE_CHECKED_AT,
        snapshot_state="configured_snapshot",
    )

    # Manual-pin capable: registered in the exact-ID lookup table only.
    # Not appended to CATALOG_MODELS, so b14/auto and the legacy public
    # summary surface are untouched; the owner pins this route explicitly.
    CATALOG_BY_ID[model.model_id] = model


register_sensenova_provider()
