"""Inception Provider onboarding for Business 14."""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

INCEPTION_PROVIDER_ID = "inception"
INCEPTION_BASE_ORIGIN = "https://api.inceptionlabs.ai/v1"
INCEPTION_ALLOWED_HOST = "api.inceptionlabs.ai"
INCEPTION_CREDENTIAL_BINDING = "PADIEM_INCEPTION_MERCURY_API_KEY"
INCEPTION_MODEL_ID = "inception/mercury-2.5"
INCEPTION_UPSTREAM_MODEL = "mercury-2.5"
INCEPTION_SOURCE_CHECKED_AT = "2026-09-18"


def register_inception_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
