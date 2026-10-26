"""#5573 PR-4a: a pairing completes from the tag the server already sees.

A beta PC cannot name its own MeshCentral node identity — that is what
`meshctrl listdevices` reports on the executor host. So the install wrapper
stamps the derived tag into the agent's name, the existing presence beat carries
that name to Chat, and the tag decides the owner: it only ever existed inside
one unexpired one-time code.

These tests run against real sqlite with migration 072 applied, because the
properties that matter are database properties: one code produces exactly one
link, a used tag stays used, and no agent name is ever written down.
"""
from __future__ import annotations
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing            # noqa: E402
import test_5015_pc_read_dispatch as lane                # noqa: E402

from app import oracle_mesh_read_return_routes as routes  # noqa: E402
from app.mesh_device_presence_store import D1MeshDevicePresenceStore  # noqa: E402
from app.pc_device_pairing_store import (                # noqa: E402
    PcPairingError,
    derive_install_tag,
    tag_from_agent_name,
)

from datetime import timedelta                           # noqa: E402

NODE = "node/meshdomain/mesh-beta-01"
MESHCTRL_NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
RUN = pairing.run


def _issued(store, *, minutes_ago: int = 0):
    """One real code for the lane's OWNER, plus the tag derived from it."""
    issued = RUN(store.issue_code(
        user_id=lane.OWNER,
        issued_at=pairing._now() - timedelta(minutes=minutes_ago),
    ))
    return issued, derive_install_tag(issued["code"])


# -- 1. the tag completes the claim -----------------------------------------

def test_an_observed_agent_tag_completes_the_pairing_as_an_active_link() -> None:
    store = pairing.store()
    issued, tag = _issued(store)

    link = RUN(store.complete_claim_from_observation(
        agent_name=f"PADIEM {tag} beta-notebook", mesh_node_id=NODE, now=pairing._now(),
    ))

    assert link["state"] == "active"
    assert link["mesh_node_id"] == NODE
    assert link["roots"] == []
    # The dispatch lane reads links, not codes: the claim is usable right now.
    live = RUN(store.link_for(user_id=lane.OWNER, mesh_node_id=NODE))
    assert live["link_id"] == link["link_id"]
    assert issued["code_id"] != link["link_id"]


# -- 2. the tag is exactly as single-use as the code ------------------------

def test_a_second_observation_of_the_same_tag_creates_no_second_link() -> None:
    store = pairing.store()
    issued, tag = _issued(store)

    first = RUN(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=pairing._now(),
    ))
    with pytest.raises(PcPairingError) as again:
        RUN(store.complete_claim_from_observation(
            agent_name=tag, mesh_node_id=NODE, now=pairing._now(),
        ))
    assert str(again.value) == "pairing code used"

    links = RUN(store.links_for_owner(user_id=lane.OWNER))
    assert [row["link_id"] for row in links] == [first["link_id"]]


# -- 3. expiry and unknown tags refuse, and expiry is closed off ------------

def test_an_expired_tag_is_cancelled_and_an_unknown_tag_is_refused() -> None:
    store = pairing.store()
    issued, tag = _issued(store, minutes_ago=11)

    with pytest.raises(PcPairingError) as expired:
        RUN(store.complete_claim_from_observation(
            agent_name=tag, mesh_node_id=NODE, now=pairing._now(),
        ))
    assert str(expired.value) == "pairing code expired"
    assert RUN(store.links_for_owner(user_id=lane.OWNER)) == []

    with pytest.raises(PcPairingError) as unknown:
        RUN(store.complete_claim_from_observation(
            agent_name="pd-01234567", mesh_node_id=NODE, now=pairing._now(),
        ))
    assert str(unknown.value) == "pairing tag unknown"

    row = store.db.conn.execute(
        "SELECT state FROM pc_pairing_codes WHERE code_id=?", (issued["code_id"],),
    ).fetchone()
    assert row["state"] == "cancelled"


# -- 4. ordinary names change nothing, and no name is ever stored -----------

def test_a_name_without_a_tag_claims_nothing_and_names_are_not_stored() -> None:
    store = pairing.store()
    issued, tag = _issued(store)

    assert RUN(store.complete_claim_from_observation(
        agent_name="DESKTOP-7Q41B2X", mesh_node_id=NODE, now=pairing._now(),
    )) is None
    assert RUN(store.links_for_owner(user_id=lane.OWNER)) == []

    RUN(store.complete_claim_from_observation(
        agent_name=f"PADIEM-PC {tag} (견적 작업실)", mesh_node_id=NODE, now=pairing._now(),
    ))
    rows = store.db.conn.execute(
        "SELECT * FROM pc_device_links"
    ).fetchall()
    stored = " ".join(str(value) for row in rows for value in tuple(row))
    # The node identity is the link; the human-readable name is not kept, and
    # neither is the plaintext code behind the tag.
    assert "견적 작업실" not in stored and "PADIEM-PC" not in stored
    assert tag not in stored


def test_the_tag_is_found_as_a_token_and_never_guessed() -> None:
    tag = derive_install_tag("K7QM2XTR9F4B")
    assert tag_from_agent_name(tag) == tag
    assert tag_from_agent_name(f"desk {tag.upper()} v2") == tag
    # Not a tag: a longer alnum run, two candidates, or a lookalike shape.
    assert tag_from_agent_name(f"x{tag}5") is None
    assert tag_from_agent_name(f"{tag} {tag}") is None
    assert tag_from_agent_name("pd-1234567") is None
    assert tag_from_agent_name(None) is None


# -- 5. the presence beat path completes the claim end to end --------------

def test_a_presence_beat_with_the_tag_completes_the_claim(monkeypatch) -> None:
    state = lane._state(monkeypatch)
    store = pairing.store()
    issued, tag = _issued(store)
    state.pc_device_pairing_store = store
    state.mesh_device_presence_store = D1MeshDevicePresenceStore(
        pairing.RealSQLiteD1(pairing.database())
    )

    request = type("R", (), {"app": type("A", (), {"state": state})()})()
    RUN(routes._record_mesh_presence(
        request, state.oracle_mesh_return_source,
        [{"device_id": NODE, "connected": True, "agent_name": f"PADIEM {tag}"}],
    ))

    links = RUN(store.links_for_owner(user_id=lane.OWNER))
    assert [row["mesh_node_id"] for row in links] == [NODE]
    # The beat is recorded under the same identity, so presence and authority
    # cannot disagree about which PC this is.
    receipt = RUN(state.mesh_device_presence_store.load(device_id=NODE))
    assert receipt is not None and receipt["connected"] == 1

    # The meshctrl spelling is a link identity too (Owner decision (A)).
    other = pairing.store()
    issued2, tag2 = _issued(other)
    RUN(other.complete_claim_from_observation(
        agent_name=tag2, mesh_node_id=MESHCTRL_NODE, now=pairing._now(),
    ))
    assert [row["mesh_node_id"] for row in RUN(
        other.links_for_owner(user_id=lane.OWNER)
    )] == [MESHCTRL_NODE]
