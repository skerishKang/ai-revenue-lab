"""Owner-retired Kilo variants must never register or dispatch."""
import pytest
from app.pilot.catalog import CATALOG_BY_ID, get_catalog_by_id
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import NoSafeRoute

@pytest.mark.parametrize("model_id",[
    "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
    "kilo/poolside-laguna-s-2.1-free",
    "kilo/stealth-space-bunny-alpha",
    "kilo/minimax-minimax-m3-free",
    "kilo/tencent-hy3-free"
])
def test_retired_kilo_never_registered_or_dispatched(model_id):
    assert get_catalog_by_id(model_id) is None
    assert model_id not in CATALOG_BY_ID
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(model_id)
    assert exc.value.upstream_called is False

def test_kilo_provider_reonboarded_for_crouton_only():
    spec = get_platform_provider("kilo")
    assert spec is not None
    assert spec.base_origin == "https://api.kilo.ai/api/gateway/v1"
    assert spec.credential_binding_name == "PADIEM_B14_CREDENTIAL_08"
    assert get_catalog_by_id("kilo/stealth/crouton-alpha") is not None
    assert get_catalog_by_id("poolside/laguna-s-2.1") is not None
    assert get_platform_provider("poolside") is not None
