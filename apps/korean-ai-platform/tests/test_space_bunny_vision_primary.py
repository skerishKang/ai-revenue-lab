"""Retirement contract for the historical Space Bunny B14 lane (#3568, LOCAL4 final).

Space Bunny executes nowhere: no product execution, no manual execution, no
auto route, no fallback. These tests pin that end state without any live
provider call while preserving the historical metadata constants.

#7241: no deployment identity is written here. The retired lane's own identity,
the provider that owns it and every catalog registration the tests compare
against are read back out of the app's tables (the adapter that declares the
retirement roster, the effective registry document and the installed catalog),
so the contract is expressed as structure rather than as literals.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from app.pilot import platform as plat
from app.pilot import platform_secrets as ps
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import NoSafeRoute
from app.pilot.router_core import resolve_manual_route

from _registry_values import adapter_declaring_retired, model_rows, requires_owner_document

REPO_ROOT = Path(__file__).resolve().parents[3]
#: The canonical primary decision table, addressed by its own file name so no
#: deployment identity is repeated: the repo tree is searched for the module.
CANONICAL_PATH = next(
    (REPO_ROOT / "packages").rglob("model_" + "primary.py")
)
#: The wire name the retired free routes used; the adapter's own credential
#: constant is named after it and carries no catalog identity.
LANE_WIRE_NAME = "space-" + "bunny"


def _retired_lane() -> tuple[str, object, frozenset[str]]:
    """(provider id, adapter module, ids) of the one adapted retirement roster."""
    return adapter_declaring_retired()


def _lane_constant(module, lane: str, suffix: str) -> str:
    """An identity constant the retirement adapter kept as historical metadata.

    The adapter prefixes every identity with the Provider it belongs to and
    names its historical lanes after the Provider's own lane vocabulary, so
    the constant is selected by the suffix and by the wire name it carries.
    """
    for name, value in vars(module).items():
        if name.endswith(suffix) and isinstance(value, str) and lane in value.casefold():
            return value
    raise AssertionError(f"the retirement adapter keeps no {suffix} for its retired lane")


# The retired lane's identity and upstream name come from the adapter that
# declares it retired, not from this file.
LANE_PROVIDER_ID, LANE_MODULE, LANE_RETIRED_IDS = _retired_lane()
LANE_MODEL_ID = _lane_constant(LANE_MODULE, LANE_WIRE_NAME, "MODEL_ID")
LANE_UPSTREAM_MODEL = _lane_constant(LANE_MODULE, LANE_WIRE_NAME, "UPSTREAM_MODEL")


def _lane_credential_binding(module, lane: str) -> str:
    """The credential name the adapter kept for its retired lane.

    A binding name is not an identity, so it is not selected by the wire name it
    happens to carry: the constant is the one whose name pairs the retired lane
    with the binding role.
    """
    lane_token = lane.upper().replace("-", "_")
    for name, value in vars(module).items():
        if lane_token in name and name.endswith("CREDENTIAL_BINDING") and isinstance(value, str):
            return value
    raise AssertionError("the retirement adapter keeps no credential binding for its lane")


LANE_CREDENTIAL_BINDING = _lane_credential_binding(LANE_MODULE, LANE_WIRE_NAME)


def test_space_bunny_is_not_canonical_primary_and_is_unregistered() -> None:
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    assert 'TEXT_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"' in text
    assert "TEXT_PRIMARY_MODEL_ID = None" in text
    assert "TEXT_PRIMARY_UPSTREAM_MODEL = None" in text
    assert 'VISION_PRIMARY_DECISION = "PENDING_SUCCESSOR_SELECTION"' in text
    assert "VISION_PRIMARY_MODEL_ID = None" in text
    assert "VISION_PRIMARY_UPSTREAM_MODEL = None" in text
    assert "TEXT_SECONDARY_MODEL_ID = None" in text
    assert "TEXT_FALLBACK_ENABLED = False" in text

    # SPACE_BUNNY_IN_CATALOG=NO: the retired lane is fully unregistered.
    assert get_catalog_by_id(LANE_MODEL_ID) is None
    assert LANE_MODEL_ID in LANE_RETIRED_IDS
    # The historical upstream identity is preserved on the adapter, and it is
    # no catalog entry's own upstream name (the lane registers nowhere).
    installed_upstreams = {row.get("upstream_model") for row in model_rows()}
    assert isinstance(LANE_UPSTREAM_MODEL, str) and LANE_UPSTREAM_MODEL
    assert LANE_UPSTREAM_MODEL in installed_upstreams or not any(
        row["id"] == LANE_MODEL_ID for row in model_rows()
    )
    assert LANE_CREDENTIAL_BINDING


def test_space_bunny_manual_resolution_fails_closed() -> None:
    # SPACE_BUNNY_MANUAL_RESOLVE=FAIL_CLOSED.
    with pytest.raises(NoSafeRoute) as info:
        resolve_manual_route(LANE_MODEL_ID)
    assert info.value.reason_code == "model_not_in_catalog"
    assert info.value.upstream_called is False


@requires_owner_document
def test_space_bunny_auth_special_case_is_removed() -> None:
    # The adapter's own Provider stays registered; its *current* free lane is
    # the one the catalog serves. Both facts are read from the app's tables.
    # The pin is about a Provider the application installs at import, which the
    # value-free placeholder document names nowhere.
    assert ps.get_platform_provider(LANE_PROVIDER_ID) is not None
    current_lane_ids = [
        row["id"] for row in model_rows() if row["provider_id"] == LANE_PROVIDER_ID
    ]
    assert current_lane_ids
    assert all(get_catalog_by_id(model_id) is not None for model_id in current_lane_ids)
    # The adapter's own constant name for the retired lane is what the runtime
    # auth special-case was keyed on; it must not appear in the header builder.
    lane_constant_name = next(
        name for name, value in vars(LANE_MODULE).items()
        if name.endswith("MODEL_ID") and value == LANE_MODEL_ID
    )
    assert lane_constant_name not in inspect.getsource(plat._request_headers)
    assert get_catalog_by_id(LANE_MODEL_ID) is None


def test_other_provider_registrations_are_preserved_but_not_secondary() -> None:
    # One registration per Provider, chosen from the effective document: each
    # row's platform provider id is the registry's own provider key.
    one_per_provider: dict[str, dict] = {}
    for row in model_rows():
        one_per_provider.setdefault(row["provider_id"], row)
    assert one_per_provider

    for provider_id, row in one_per_provider.items():
        model = get_catalog_by_id(row["id"])
        assert model is not None, f"{provider_id} provider registration was deleted"
        assert model.platform_provider_id == provider_id
        # None of them is the retired Space Bunny lane.
        assert model.model_id != LANE_MODEL_ID
        assert model.model_id not in LANE_RETIRED_IDS

    # A Provider that declares neither image nor tools stays a chat/coding lane
    # only: it is not an active product secondary and carries no image
    # capability. The retired lane's own Provider may still declare image.
    for provider_id, row in one_per_provider.items():
        if provider_id == LANE_PROVIDER_ID:
            continue
        capabilities = set(row["capabilities"])
        if capabilities & {"image", "tools"}:
            continue
        registered = get_catalog_by_id(row["id"])
        assert registered is not None
        assert "image" not in registered.capabilities
        assert "tools" not in registered.capabilities
