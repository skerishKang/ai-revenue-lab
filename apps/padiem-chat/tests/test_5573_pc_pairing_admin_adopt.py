"""#5573 PR-4e and its follow-up: adopt a real PC onto a named account.

The contract turns on these properties, one test each:

  * only a platform administrator may adopt, and the guard runs before any
    device or account read, so a refused call learns nothing;
  * the device is verified by what the Mesh lane actually reported
    (`mesh_device_presence`), not by a deployment ownership map — a machine that
    never reported cannot be adopted into existence, and one that did needs no
    map entry;
  * `target` names the account the PC is attached to, by the id this deployment
    already uses or by the address that account signs in with, and it has to be a
    real account. Without `target` it is the caller's own account, as before;
  * the scope is #5981's default: the whole fixed drives the PC itself reported,
    reused for every account attached to that machine;
  * adoption is idempotent, and one machine may serve several accounts.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing          # noqa: E402
import test_5015_pc_read_dispatch as lane              # noqa: E402

from app.pc_device_pairing_routes import PC_PAIRING_ADOPT_PATH  # noqa: E402
from app.platform_admin_authority import ROLE_SUPER_ADMIN       # noqa: E402

#: A node identity the Mesh lane can address. Adoption takes that, not a shape
#: the caller invented.
MESH_NODE = "node/meshdomain/adopted-pc-01"
OTHER_MESH_NODE = "node/meshdomain/adopted-pc-02"
CUSTOMER_ID = "usr_" + "c" * 32
CUSTOMER_EMAIL = "Customer.Example@Example.test"
DRIVES = ["C:", "D:"]
run = pairing.run


class _Roles:
    """The stored platform role the authority reads."""

    def __init__(self, role):
        self.role = role

    async def role_for(self, user_id):
        return self.role


class _Presence:
    """The executor's own receipts: the record adoption asks now, instead of a map."""

    def __init__(self, seen):
        self.seen = set(seen)
        self.reads: list[str] = []

    async def load(self, *, device_id):
        self.reads.append(device_id)
        if device_id not in self.seen:
            return None
        return {
            "device_id": device_id,
            "connected": 1,
            "received_at": "2026-10-28T00:00:00.000Z",
            "credential_generation": None,
            "source": "mesh",
        }


def _store_with_users():
    """A pairing store over a database that also holds the account table."""
    conn = pairing.database()
    moment = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
        "picture_url, created_at, updated_at) VALUES (?, 'google', ?, ?, '', '', ?, ?)",
        (CUSTOMER_ID, "subject-customer-1", CUSTOMER_EMAIL, moment, moment),
    )
    return pairing.D1PcPairingStore(pairing.RealSQLiteD1(conn)), conn


def _app(role=ROLE_SUPER_ADMIN, *, store_value=None, seen=(MESH_NODE,), presence=True):
    app = pairing.app_with(pairing.store() if store_value is None else store_value)
    app.state.platform_admin_role_store = _Roles(role)
    app.state.mesh_device_presence_store = _Presence(seen) if presence else None
    return app


def _adopt(app, payload):
    async def once():
        async with pairing.client(app) as session:
            return await session.post(PC_PAIRING_ADOPT_PATH, json=payload)
    return run(once())


def _scope(link_body):
    return [root["path"] for root in link_body["roots"]]


def test_a_non_administrator_is_refused_before_the_device_is_read():
    app = _app(None)
    response = _adopt(app, {"device_id": MESH_NODE, "drives": DRIVES})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "pc_pairing_not_admin"
    # Nothing about the device is disclosed to a caller who may not adopt: the
    # presence directory was never asked.
    assert app.state.mesh_device_presence_store.reads == []


def test_a_device_the_mesh_lane_never_reported_cannot_be_adopted():
    response = _adopt(_app(seen=()), {
        "device_id": "node/meshdomain/never-installed-anything", "drives": DRIVES,
    })
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "pc_pairing_device_unseen"


def test_a_reported_device_needs_no_map_entry_and_grants_the_pc_own_drives():
    """The old refusal here was "this deployment's map does not name it"."""
    store = pairing.store()
    app = _app(store_value=store)
    response = _adopt(app, {"device_id": MESH_NODE, "drives": DRIVES})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["drives_status"] == "seeded"
    assert _scope(body["link"]) == DRIVES
    assert body["link"]["state"] == "active"
    assert body["link"]["mesh_node_id"] == MESH_NODE
    # The link is already usable by the file lane, and no pairing code was spent.
    live = run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MESH_NODE))
    assert [row["path"] for row in live["roots"]] == DRIVES
    assert run(store.list_codes(user_id=pairing.OWNER, now=pairing._now())) == []


def test_adoption_is_idempotent_for_the_same_account_and_device():
    store = pairing.store()
    app = _app(store_value=store)
    first = _adopt(app, {"device_id": MESH_NODE, "drives": DRIVES})
    second = _adopt(app, {"device_id": MESH_NODE, "drives": DRIVES})
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert second.json()["link"] == first.json()["link"]
    assert len(run(store.links_for_owner(user_id=pairing.OWNER))) == 1


def test_a_second_adoption_later_in_time_writes_nothing():
    """Idempotence as a property of the store, not of a fast clock.

    The second call is given a clearly later receipt time. If it wrote anything,
    `updated_at` would move; the point of the short circuit is that a repeat
    adoption is a read.
    """
    store = pairing.store()
    _app(store_value=store)
    assert _adopt(_app(store_value=store), {
        "device_id": MESH_NODE, "drives": DRIVES,
    }).status_code == 200

    earlier = pairing._now()
    seen = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MESH_NODE, root_paths=[],
        now=earlier, drives=DRIVES,
    ))
    later = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MESH_NODE, root_paths=["C:/Windows/System32"],
        now=earlier + timedelta(minutes=5), drives=["E:"],
    ))
    assert seen["link_id"] == later["link_id"]
    assert seen["updated_at"] == later["updated_at"]
    # A repeat adoption cannot smuggle in a different folder or a wider drive set.
    assert [root["path"] for root in later["roots"] if root["state"] == "active"] == DRIVES


def test_a_folder_the_owner_revoked_does_not_come_back_on_re_adopt():
    store = pairing.store()
    _app(store_value=store)
    link = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MESH_NODE, root_paths=[lane.ROOT], now=pairing._now(),
    ))
    root_ref = link["roots"][0]["root_ref"]
    assert run(store.revoke_root(
        user_id=pairing.OWNER, link_id=link["link_id"], root_ref=root_ref, now=pairing._now(),
    )) is True
    assert run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MESH_NODE))["roots"] == []

    again = run(store.adopt_link(
        user_id=pairing.OWNER, mesh_node_id=MESH_NODE, root_paths=[lane.ROOT],
        now=pairing._now() + timedelta(minutes=3),
    ))
    assert again["link_id"] == link["link_id"]
    # Re-adoption is not a route back to a grant the owner withdrew.
    assert run(store.link_for(user_id=pairing.OWNER, mesh_node_id=MESH_NODE))["roots"] == []


def test_a_target_account_can_be_named_by_id_or_by_email():
    store, conn = _store_with_users()
    app = _app(store_value=store, seen=(MESH_NODE, OTHER_MESH_NODE))
    try:
        by_id = _adopt(app, {"device_id": MESH_NODE, "target": CUSTOMER_ID, "drives": DRIVES})
        assert by_id.status_code == 200, by_id.text
        named = by_id.json()["link"]
        assert named["user_id"] == CUSTOMER_ID
        assert run(store.links_for_owner(user_id=CUSTOMER_ID))[0]["link_id"] == named["link_id"]
        # The administrator who adopted is not the account the PC belongs to.
        assert run(store.links_for_owner(user_id=pairing.OWNER)) == []

        # The same address, differently spelled, is the same account.
        other = _adopt(app, {
            "device_id": OTHER_MESH_NODE, "target": CUSTOMER_EMAIL.upper(), "drives": DRIVES,
        })
        assert other.status_code == 200, other.text
        assert other.json()["link"]["user_id"] == CUSTOMER_ID
    finally:
        conn.close()


def test_an_unknown_target_account_is_refused_and_creates_no_link():
    store, conn = _store_with_users()
    app = _app(store_value=store)
    try:
        response = _adopt(app, {
            "device_id": MESH_NODE, "target": "nobody@nowhere.invalid", "drives": DRIVES,
        })
        assert response.status_code == 404, response.text
        assert response.json()["error"]["code"] == "pc_pairing_target_unknown"
        assert run(store.links_for_owner(user_id=pairing.OWNER)) == []
    finally:
        conn.close()


def test_one_device_can_serve_two_accounts_and_the_scope_is_reused():
    """The Owner's link and the customer's link are two links on one machine."""
    store, conn = _store_with_users()
    app = _app(store_value=store)
    try:
        owner_side = _adopt(app, {"device_id": MESH_NODE, "drives": DRIVES})
        assert owner_side.status_code == 200, owner_side.text
        customer_side = _adopt(app, {
            "device_id": MESH_NODE, "target": CUSTOMER_ID, "drives": DRIVES,
        })
        assert customer_side.status_code == 200, customer_side.text
        assert customer_side.json()["link"]["link_id"] != owner_side.json()["link"]["link_id"]

        # A later adoption that names no drives inherits the letters the PC itself
        # reported: adoption reads the node, not a map entry.
        same_target = _adopt(_app(store_value=store), {
            "device_id": MESH_NODE, "target": CUSTOMER_ID,
        })
        assert same_target.status_code == 200, same_target.text
        assert _scope(same_target.json()["link"]) == DRIVES
        assert len(run(store.links_for_owner(user_id=pairing.OWNER))) == 1
        assert len(run(store.links_for_owner(user_id=CUSTOMER_ID))) == 1
        assert run(store.device_scope(device_id=MESH_NODE))["account_refs"] == sorted(
            [pairing.OWNER, CUSTOMER_ID]
        )
    finally:
        conn.close()


def test_a_reported_device_nobody_has_reported_drives_for_is_refused():
    """A link with no scope would be a PC the account cannot use."""
    response = _adopt(_app(), {"device_id": MESH_NODE})
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "pc_pairing_device_unscoped"


def test_adoption_without_a_presence_port_is_not_ready_rather_than_absent():
    response = _adopt(_app(presence=False), {"device_id": MESH_NODE, "drives": DRIVES})
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "pc_pairing_unavailable"
