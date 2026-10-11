"""Experiential Labs Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

EXPERIENTIAL_PROVIDER_ID = "experiential"
EXPERIENTIAL_BASE_ORIGIN = "https://api.experientiallabs.ai/v1"
EXPERIENTIAL_ALLOWED_HOST = "api.experientiallabs.ai"
EXPERIENTIAL_CREDENTIAL_BINDING = "PADIEM_EXLAB_API_KEY"
EXPERIENTIAL_MODEL_ID = "experiential/gpt-5.6-luna"
EXPERIENTIAL_UPSTREAM_MODEL = "gpt-5.6-luna"
EXPERIENTIAL_SOURCE_CHECKED_AT = "2026-09-18"


def register_experiential_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
