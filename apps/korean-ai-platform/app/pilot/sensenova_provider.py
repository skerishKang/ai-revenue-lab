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
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
