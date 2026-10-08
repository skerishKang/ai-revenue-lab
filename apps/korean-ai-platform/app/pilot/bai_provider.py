"""B.AI Provider onboarding for Business 14 (#2133).

Owner decision (#2126 5584200820) approved B.AI as a Padiem Pro candidate
provider with the credential name ``PADIEM_B_AI_API_KEY`` (name only; the
value never enters this repository).

ACT-0 authority — official B.AI docs (docs.b.ai), checked 2026-09-08:

- Production Base URL: ``https://api.b.ai/v1``;
- OpenAI-compatible ``POST /v1/chat/completions`` plus Responses/Messages
  protocols; Bearer authentication; streaming over SSE;
- ``qwen3.8-flash`` appears as the hosted production model ID (official code
  span and body text: "qwen3.8-flash is the hosted production model").

GLM-5.3-Flash is the owner's second named candidate, but every official page
uses the display name "GLM-5.3-Flash" and never publishes the exact ``model``
API string for it (the lowercase "glm-5-3-flash" tokens are URL slugs; the
"Supported Model IDs" guide table lists only ``glm-5.1`` for the GLM line).
#2133 forbids deriving an upstream ID from a display name, so this slice
registers ONLY ``qwen3.8-flash``. The GLM-5.3-Flash route stays blocked with
``MODEL_ID_AUTHORITY=UNKNOWN`` until the provider documents the exact ID (or
an authorized ACT-1 read of ``GET /v1/models`` proves it). No route is
fabricated in the meantime.

Registration is explicit/manual-pin only: the model lives in the exact-ID
``CATALOG_BY_ID`` table and is NOT appended to ``CATALOG_MODELS``, so
``b14/auto`` and the legacy public summary surface are untouched. Missing
credential fails closed with zero upstream calls (generic platform adapter
contract). Pricing is Credits-denominated — no USD or free claim is
fabricated.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

BAI_PROVIDER_ID = "b-ai"
BAI_BASE_ORIGIN = "https://api.b.ai/v1"
BAI_ALLOWED_HOST = "api.b.ai"
BAI_CREDENTIAL_BINDING = "PADIEM_B_AI_API_KEY"

BAI_QWEN_MODEL_ID = "b-ai/qwen3.8-flash"
BAI_QWEN_UPSTREAM_MODEL = "qwen3.8-flash"
# Official docs.b.ai contract checked for #2133 ACT-0.
BAI_SOURCE_CHECKED_AT = "2026-09-08"


def register_bai_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
