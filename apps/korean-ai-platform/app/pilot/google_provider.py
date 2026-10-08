"""Google AI Studio provider onboarding for Business 14 (#3554, 2026-10-08).

Owner selection 2026-10-08 named four Google models in the Padiem Plus set:
``gemini-3.1-flash-lite``, ``gemini-3.5-flash-lite``, ``gemma-4-26b-a4b-it``
and ``gemma-4-31b-it``. All four were confirmed present in the live
``generativelanguage.googleapis.com/v1beta/models`` catalog on 2026-10-08
(62 models total) before any registration.

Google's documented OpenAI-compatible origin is
https://generativelanguage.googleapis.com/v1beta/openai. The existing
Business 14 OpenAI-compatible client uses Authorization: Bearer with the
Google AI Studio key, NOT native x-goog-api-key and generateContent. The owner-approved credential binding name is
``PADIEM_GEMINI_API_KEY`` (name only; the value is never read, printed, or
committed here).

Measured on 2026-10-08 against the repo-owned synthetic Korean quotation
fixture at each provider's documented defaults:

* gemini-3.5-flash-lite  text 7/7 facts 1.12s, image 5/5 facts 1.28s
* gemini-3.1-flash-lite  text 7/7 facts 0.92s, image 5/5 facts 1.37s
* gemma-4-26b-a4b-it     text 7/7 facts 13.0s, image 5/5 facts 28.1s
* gemma-4-31b-it         text 7/7 facts 49.0s; image blocked by provider capacity

Gemma 4 31B is registered as text-only because its image capability was not
measurable, and its 49.0s latency exceeds the B14 20.0s default dispatch
budget. Registration states exactly that rather than a capability nobody proved.

Registration is explicit/manual-pin only: each model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Prices are the provider's published per-million-token rates; the
API returns no dollar field, so no measured-cost claim is made here.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

GOOGLE_PROVIDER_ID = "google"
GOOGLE_BASE_ORIGIN = "https://generativelanguage.googleapis.com/v1beta/openai"
GOOGLE_ALLOWED_HOST = "generativelanguage.googleapis.com"
GOOGLE_CREDENTIAL_BINDING = "PADIEM_GEMINI_API_KEY"

# Authority date of the catalog read and the measurements this registration cites.
GOOGLE_SOURCE_CHECKED_AT = "2026-10-08"

# model_id, upstream model, display name, context window, USD per 1M in/out,
# capabilities, sort order.
_GOOGLE_MODELS: tuple[tuple[str, str, str, int, float, float, frozenset[str], int], ...] = (
    (
        "google/gemini-3.5-flash-lite",
        "gemini-3.5-flash-lite",
        "Google: Gemini 3.5 Flash Lite",
        1_048_576,
        0.30,
        2.50,
        frozenset({"chat", "image", "coding"}),
        70,
    ),
    (
        "google/gemini-3.1-flash-lite",
        "gemini-3.1-flash-lite",
        "Google: Gemini 3.1 Flash Lite",
        1_048_576,
        0.25,
        1.50,
        frozenset({"chat", "image", "coding"}),
        71,
    ),
    (
        "google/gemma-4-26b-a4b-it",
        "gemma-4-26b-a4b-it",
        "Google: Gemma 4 26B",
        262_144,
        0.09,
        0.30,
        frozenset({"chat", "image"}),
        72,
    ),
    (
        "google/gemma-4-31b-it",
        "gemma-4-31b-it",
        "Google: Gemma 4 31B",
        262_144,
        0.09,
        0.34,
        # text-only: the image measurement was blocked by provider capacity.
        frozenset({"chat"}),
        73,
    ),
)


def register_google_provider() -> None:
    """Idempotently register Google AI Studio and the four owner-selected routes."""

    if get_platform_provider(GOOGLE_PROVIDER_ID) is None:
        register_platform_provider(
            PlatformProviderSpec(
                provider_id=GOOGLE_PROVIDER_ID,
                credential_source=CredentialSource.PLATFORM_SECRET,
                credential_binding_name=GOOGLE_CREDENTIAL_BINDING,
                base_origin=GOOGLE_BASE_ORIGIN,
                allowed_hosts=(GOOGLE_ALLOWED_HOST,),
                enabled=True,
            )
        )

    for (
        model_id,
        upstream_model,
        display_name,
        context_window,
        input_price,
        output_price,
        capabilities,
        sort_order,
    ) in _GOOGLE_MODELS:
        if model_id in CATALOG_BY_ID:
            continue
        model = CatalogModel(
            model_id=model_id,
            upstream_model=upstream_model,
            display_name=display_name,
            provider="Google AI Studio",
            provider_type="platform",
            input_price_usd_per_1m=input_price,
            output_price_usd_per_1m=output_price,
            currency="usd",
            context_window=context_window,
            korean_score=0,
            latency_ms=0,
            capabilities=capabilities,
            region="외부",
            sort_order=sort_order,
            credential_source="platform_secret",
            platform_provider_id=GOOGLE_PROVIDER_ID,
            source="google_ai_studio_official_catalog (2026-10-08 read)",
            source_checked_at=GOOGLE_SOURCE_CHECKED_AT,
            snapshot_state="configured_snapshot",
        )
        # Manual-pin capable: exact-ID lookup table only. Do not append to
        # CATALOG_MODELS (the legacy public/b14-auto routing surface).
        CATALOG_BY_ID[model.model_id] = model
