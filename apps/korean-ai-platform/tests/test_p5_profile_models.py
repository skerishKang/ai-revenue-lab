from __future__ import annotations

from app.pilot.catalog import CATALOG_BY_ID
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.poolside_provider import (
    POOLSIDE_BASE_ORIGIN,
    POOLSIDE_CREDENTIAL_BINDING,
    POOLSIDE_MODEL_ID,
    POOLSIDE_PROVIDER_ID,
    POOLSIDE_XS_MODEL_ID,
    register_poolside_provider,
)


def test_p5_poolside_low_and_medium_share_fixed_provider_boundary():
    register_poolside_provider()
    spec = get_platform_provider(POOLSIDE_PROVIDER_ID)
    assert spec is not None
    assert spec.base_origin == POOLSIDE_BASE_ORIGIN == "https://inference.poolside.ai/v1"
    assert spec.allowed_hosts == ("inference.poolside.ai",)
    assert spec.credential_binding_name == POOLSIDE_CREDENTIAL_BINDING == "POOLSIDE_API_KEY"

    low = CATALOG_BY_ID[POOLSIDE_XS_MODEL_ID]
    medium = CATALOG_BY_ID[POOLSIDE_MODEL_ID]
    assert low.model_id == "poolside/laguna-xs-2.1"
    assert medium.model_id == "poolside/laguna-s-2.1"
    assert low.platform_provider_id == medium.platform_provider_id == POOLSIDE_PROVIDER_ID
    assert low.credential_source == medium.credential_source == "platform_secret"
    assert low.context_window == 256_000
    assert medium.context_window == 1_000_000
    assert "chat" in low.capabilities and "chat" in medium.capabilities
    assert "free" not in low.capabilities and "free" not in medium.capabilities
