"""Atria Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

ATRIA_PROVIDER_ID = "atria"
ATRIA_BASE_ORIGIN = "https://api.atria-asi.ai/v1"
ATRIA_ALLOWED_HOST = "api.atria-asi.ai"
ATRIA_CREDENTIAL_BINDING = "PADIEM_ATRIA_API_KEY"
ATRIA_MODEL_ID = "atria/Atria-Dawn-Preview"
ATRIA_UPSTREAM_MODEL = "Atria-Dawn-Preview"
ATRIA_SOURCE_CHECKED_AT = "2026-09-18"


def register_atria_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
