"""#5573 PR-4e: an administrator adopts a mapped PC into their own account.

The three properties the contract turns on are the three tests here: a caller
who is not a platform administrator is refused before the deployment map is read,
a device the map does not name cannot be adopted into existence, and adopting
twice returns the same link rather than a second or wider grant.
"""
from __future__ import annotations
from datetime import timedelta
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing          # noqa: E402
import test_5015_pc_read_dispatch as lane              # noqa: E402

from app import oracle_mesh_read_return_routes as routes  # noqa: E402
from app.pc_device_pairing_routes import PC_PAIRING_ADOPT_PATH  # noqa: E402
from app.platform_admin_authority import ROLE_SUPER_ADMIN  # noqa: E402

# The identity the deployment map names this device by. Adoption takes what the
# map calls a device, not a shape the caller invented.
MAP_NODE = lane.DEVICE
run = pairing.run


class _Roles:
    """The stored platform role the authority reads."""

    def __init__(self, role):
        self.role = role

    async def role_for(self, user_id):
        return self.role


def _app(role=ROLE_SUPER_ADMIN, *, store_value=None):
    app = pairing.app_with(pairing.store() if store_value is None else store_value)
    app.state.platform_admin_role_store = _Roles(role)
    app.state.oracle_mesh_return_source = routes.build_oracle_mesh_return_source(
        lane._mapping(), lane.CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )
    return app


def _adopt(app, device_id):
    async def once():
        async with pairing.client(app) as session:
            return await session.post(PC_PAIRING_ADOPT_PATH, json={"device_id": device_id})
    return run(once())


def test_a_non_administrator_is_refused_before_the_map_is_read():
    for role in (None,):
        response = _adopt(_app(role), MAP_NODE)
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "pc_pairing_not_admin"
        # Nothing about the device is disclosed to a caller who may not adopt.
        assert lane.ROOT not in response.text


def test_a_device_the_deployment_does_not_name_cannot_be_adopted():
    response = _adopt(_app(), "node/meshdomain/not-in-this-map-at-all")
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "pc_pairing_device_unmapped"


def test_adopting_grants_the_same_authority_as_a_claim_and_is_idempotent():
    store = pairing.store()
    app = _app(store_value=store)

    first = _adopt(app, MAP_NODE)
    second = _adopt(app, MAP_NODE)
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    link = first.json()["link"]
    assert second.json()["link"] == link
    assert link["state"] == "active"
    assert link["mesh_node_id"] == MAP_NODE
    # The folders the map already pinned travel with the adoption, so the
    # adopted PC is usable rather than merely listed.
    assert [root["path"] for root in link["roots"]] == [lane.ROOT]
    assert link["roots"][0]["label"] == lane.ROOT.rsplit("/", 1)[-1]
    # Exactly one link exists for the pair, and dispatch can already resolve it.
    live = run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MAP_NODE))
    assert live["link_id"] == link["link_id"]
    assert [row["path"] for row in live["roots"]] == [lane.ROOT]
    assert len(run(store.links_for_owner(user_id=pairing.OWNER))) == 1
    # An adoption is not a code: no pairing code was created or consumed.
    assert run(store.list_codes(user_id=pairing.OWNER, now=pairing._now())) == []


def test_a_second_adoption_later_in_time_writes_nothing():
    """Idempotence as a property of the store, not of a fast clock.

    The second call is given a clearly later receipt time. If it wrote anything,
    `updated_at` would move; the point of the short circuit is that a repeat
    adoption is a read.
    """
    store = pairing.store()
    _app(store_value=store)
    assert _adopt(_app(store_value=store), MAP_NODE).status_code == 200

    earlier = pairing._now()
    seen = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MAP_NODE, root_paths=[lane.ROOT], now=earlier,
    ))
    later = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MAP_NODE, root_paths=["C:/Windows/System32"],
        now=earlier + timedelta(minutes=5),
    ))
    assert seen["link_id"] == later["link_id"]
    assert seen["updated_at"] == later["updated_at"]
    # A repeat adoption cannot smuggle in a different folder either.
    assert [root["path"] for root in later["roots"] if root["state"] == "active"] == [lane.ROOT]


def test_a_folder_the_owner_revoked_does_not_come_back_on_re_adopt():
    store = pairing.store()
    _app(store_value=store)
    link = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MAP_NODE, root_paths=[lane.ROOT], now=pairing._now(),
    ))
    root_ref = link["roots"][0]["root_ref"]
    assert run(store.revoke_root(
        user_id=pairing.OWNER, link_id=link["link_id"], root_ref=root_ref, now=pairing._now(),
    )) is True
    assert run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MAP_NODE))["roots"] == []

    again = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MAP_NODE, root_paths=[lane.ROOT],
        now=pairing._now() + timedelta(minutes=3),
    ))
    assert again["link_id"] == link["link_id"]
    # Re-adoption is not a route back to a grant the owner withdrew.
    assert run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MAP_NODE))["roots"] == []
