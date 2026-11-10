"""Owner-retired variants must never register or dispatch."""
import pytest
from app.pilot.catalog import CATALOG_BY_ID, get_catalog_by_id
from app.pilot.platform_secrets import get_platform_provider
from app.pilot.router_core import resolve_manual_route
from app.pilot.errors import NoSafeRoute

from _registry_values import (
    adapter_declaring_retired, model_rows, provider_row, registry,
    require_owner_document, requires_owner_document,
)

# The one route this Provider kept after its retirement is an owner-document row.
# The placeholder fixture serves placeholder Providers only, so the module skips
# on a host that reads no owner document (#7241 3b).
require_owner_document()

# The retired roster is the adapter's own retirement metadata: the ids its
# frozenset retires plus every id its constants retain as retirement metadata.
# The adapter is selected from the package (#7241: the module name and the
# provider id are both deployment identities, so neither is written here).
_PROVIDER_ID, _ADAPTER, RETIRED_MODEL_IDS = adapter_declaring_retired()
provider_id = _PROVIDER_ID


@pytest.mark.parametrize("model_id", sorted(RETIRED_MODEL_IDS))
def test_retired_route_never_registered_or_dispatched(model_id):
    assert get_catalog_by_id(model_id) is None
    assert model_id not in CATALOG_BY_ID
    with pytest.raises(NoSafeRoute) as exc:
        resolve_manual_route(model_id)
    assert exc.value.upstream_called is False


@requires_owner_document
def test_retired_provider_reonboarded_for_one_route_only():
    # The owner kept exactly one route on this provider, and the registry row is
    # the authority for its origin and credential slot.
    kept = [row for row in model_rows() if row["provider_id"] == provider_id]
    assert len(kept) == 1
    spec = get_platform_provider(provider_id)
    assert spec is not None
    row = provider_row(provider_id)
    assert spec.base_origin == row["base_origin"]
    assert spec.credential_binding_name == row["credential_binding_name"]
    assert get_catalog_by_id(kept[0]["id"]) is not None
    # The other provider whose route was onboarded alongside it keeps its own
    # registration too: the kept provider did not absorb a second name.
    other_providers = [
        row["provider_id"] for row in model_rows()
        if row["provider_id"] != provider_id
        and row["upstream_model"].split("/", 1)[0] == row["provider_id"]
    ]
    assert other_providers
    for other_provider_id in set(other_providers):
        assert get_platform_provider(other_provider_id) is not None
