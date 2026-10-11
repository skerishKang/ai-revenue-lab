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
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")
