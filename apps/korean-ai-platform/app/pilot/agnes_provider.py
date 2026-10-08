"""Agnes AI Provider onboarding for Business 14 (#2133).

Owner decision (#2126 5584200820) re-approved Agnes as an explicit Plus-pool
candidate after the #1933 S2-b retirement of the first Agnes integration.
ACT-0 authority for this route is the repository intake record
``docs/providers/AGNES_AI_V1.md`` (research snapshot 2026-08-27): OpenAI-
compatible fixed origin ``https://apihub.agnes-ai.com/v1``, Bearer auth,
 advertised streaming, model ``agnes-3.0-flash``. The owner-approved credential
binding name is ``PADIEM_AGNES_API_KEY`` (names only; the value is never read,
printed, or committed here).

Registration is explicit/manual-pin only: the model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Pricing: the intake records a Credits-denominated free/default
tier, not USD rates — no price or free claim is fabricated here.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

AGNES_PROVIDER_ID = "agnes-ai"
AGNES_BASE_ORIGIN = "https://apihub.agnes-ai.com/v1"
AGNES_ALLOWED_HOST = "apihub.agnes-ai.com"
AGNES_CREDENTIAL_BINDING = "PADIEM_AGNES_API_KEY"

AGNES_MODEL_ID = "agnes-ai/agnes-3.0-flash"
AGNES_UPSTREAM_MODEL = "agnes-3.0-flash"
# Authority date of the intake record facts this registration reuses (#2133 ACT-0).
AGNES_SOURCE_CHECKED_AT = "2026-08-27"


def register_agnes_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
