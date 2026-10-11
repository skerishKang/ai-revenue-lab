"""Infron Provider onboarding for Business 14.

This is an explicit/manual-pin candidate only. Registration stores non-secret
metadata and performs no upstream or credential-value reads. The generic
platform adapter owns the fixed-origin, platform-secret, mock, and fail-closed
execution behavior.
"""

from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID, CatalogModel
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
    register_platform_provider,
)

INFRON_PROVIDER_ID = "infron"
INFRON_BASE_ORIGIN = "https://llm.onerouter.pro/v1"
INFRON_ALLOWED_HOST = "llm.onerouter.pro"
INFRON_CREDENTIAL_BINDING = "PADIEM_INFRON_API_KEY"
INFRON_MODEL_ID = "infron/motif/motif-3"
INFRON_UPSTREAM_MODEL = "motif/motif-3"
INFRON_SOURCE_CHECKED_AT = "2026-09-18"


def register_infron_provider() -> None:
    """Historic API kept only to fail closed; models are installed from b14_models.json."""
    raise RuntimeError("legacy provider registration disabled: edit b14_models.json")



# No import-time registration: canonical b14_models.json owns runtime models.
