"""#5573: an account with two linked PCs can say which one it means.

The Owner's decision is that a linked PC belongs to the account that paired it,
so a second PC must be listable, selectable and nameable exactly like the first.
Before this, the deployment map was the only thing that could name a command
target: a PC that arrived by pairing was invisible to the device directory
(choosing it answered 403 as if it belonged to somebody else), and with two
links the file lane refused everything as ambiguous while the Chat lane had
already run the request on whichever PC the browser last remembered.

These tests read the naming rule, the label surface and the directory rows -
the three things a second PC needs - against real sqlite for the links and the
live device-directory route for the selection.
"""
from __future__ import annotations
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

import test_5172_mesh_device_id_boundary as directory   # noqa: E402
import test_5573_pc_device_pairing as pairing           # noqa: E402

from app.pc_device_pairing_store import link_named_in    # noqa: E402
from app.pc_work_context import (                        # noqa: E402
    _EXEC_READY,
    _link_execution_target,
    linked_pc_targets,
)
from app.claw_device_directory_routes import (           # noqa: E402
    CLAW_DEVICE_DIRECTORY_PATH,
)

NODE_A = "node/meshdomain/klipvoice-node-a"
NODE_B = "O$SnVp94Lb7ltPM78IZukErNte93bqygxqDvjI1eVDck$tGY@Dd2cdXxSOwp"
RUN = pairing.run


def _linked(store, *, owner: str, node: str, label: str | None = None):
    """One real link: a code this account issued, claimed from the Mesh."""
    issued = RUN(store.issue_code(user_id=owner, issued_at=pairing._now()))
    link = RUN(store.complete_claim_from_observation(
        agent_name=issued["install_tag"], mesh_node_id=node, now=pairing._now(),
    ))
    if label is not None:
        link = RUN(store.set_link_label(
            user_id=owner, link_id=link["link_id"], label=label, now=pairing._now(),
        ))
    return link


# -- 1. the naming rule is one match or nothing -----------------------------

def test_only_one_named_machine_decides_and_anything_else_guesses_nothing() -> None:
    links = [
        {"mesh_node_id": NODE_A, "label": "K_lipvoice"},
        {"mesh_node_id": NODE_B, "label": "직장 PC"},
    ]
    assert link_named_in("K_lipvoice PC의 C 드라이브 최상위 목록 보여줘", links) == NODE_A
    # The name is the owner's word, not a token: case and spacing still match.
    assert link_named_in("직장  pc 폴더 좀", links) == NODE_B
    # No name, two names, and a word that is inside neither: untouched.
    assert link_named_in("C 드라이브 보여줘", links) is None
    assert link_named_in("K_lipvoice와 직장 PC를 비교해줘", links) is None
    assert link_named_in("PC", links) is None
    # An unnamed link is never a candidate, and a non-string never a request.
    assert link_named_in("anything", [{"mesh_node_id": NODE_A, "label": None}]) is None
    assert link_named_in(None, links) is None


def test_a_link_takes_the_command_target_only_when_nothing_else_must_decide() -> None:
    one = [{"mesh_node_id": NODE_A, "label": "K_lipvoice"}]
    two = [{"mesh_node_id": NODE_A, "label": "K_lipvoice"},
           {"mesh_node_id": NODE_B, "label": "직장 PC"}]

    assert _link_execution_target(one, None).device_id == NODE_A
    assert _link_execution_target(one, None).status == _EXEC_READY
    # Two links and no choice is a question, not a guess about somebody's PC.
    assert _link_execution_target(two, None) is None
    # A choice the owner made - by click or by name - is answered exactly.
    assert _link_execution_target(two, NODE_B).device_id == NODE_B
    assert _link_execution_target(two, "node/meshdomain/somebody-else") is None
    assert _link_execution_target([], NODE_A) is None


# -- 2. the owner names a linked PC over HTTP ------------------------------

def test_the_owner_names_a_linked_pc_and_another_account_cannot() -> None:
    store = pairing.store()
    mine = _linked(store, owner=pairing.OWNER, node=NODE_A)
    theirs = _linked(store, owner=pairing.OTHER, node=NODE_B)

    app = pairing.app_with(store)

    async def perform():
        async with pairing.client(app) as session:
            named = await session.post(
                f"/api/pc/pairings/{mine['link_id']}/label", json={"label": "K_lipvoice"},
            )
            blank = await session.post(
                f"/api/pc/pairings/{mine['link_id']}/label", json={"label": "   "},
            )
        async with pairing.client(app, user_id=pairing.OTHER) as other:
            stolen = await other.post(
                f"/api/pc/pairings/{mine['link_id']}/label", json={"label": "남의 PC"},
            )
            own = await other.post(
                f"/api/pc/pairings/{theirs['link_id']}/label", json={"label": "내 PC"},
            )
        return named, blank, stolen, own

    named, blank, stolen, own = RUN(perform())
    assert named.status_code == 200, named.text
    assert named.json()["link"]["label"] == "K_lipvoice"
    assert blank.status_code == 400
    # Another account's link is a permission answer, and it names nothing about
    # the row behind it.
    assert stolen.status_code == 403, stolen.text
    assert stolen.json()["error"]["code"] == "pc_pairing_link_forbidden"
    assert own.status_code == 200, own.text
    # The name reaches the directory read the dispatch lane uses.
    listed = RUN(store.links_for_owner(user_id=pairing.OWNER))
    assert [link["label"] for link in listed] == ["K_lipvoice"]


# -- 3. a paired PC is a device this account owns --------------------------

def test_a_paired_pc_is_listed_and_selectable_in_the_device_directory() -> None:
    store = pairing.store()
    link = _linked(store, owner=directory.OWNER, node=NODE_A, label="K_lipvoice")
    app, settings = directory.make_app()
    app.state.pc_device_pairing_store = store

    with directory._session_pair():
        listed = directory._get(app, settings).json()
        row = next((item for item in listed["devices"]
                    if item["deviceId"] == NODE_A), None)
        assert row is not None, listed
        assert row["deviceName"] == "K_lipvoice"
        assert row["selectable"] is True
        # Nothing has proved this PC online in this fixture, and the directory
        # says so instead of inventing a connected machine.
        assert row["usable"] is False
        assert row["state"] == "ACTION_REQUIRED"

        selection = directory.SelectionStore()
        app.state.claw_pc_device_selection_store = selection
        saved = directory._post_select(app, settings, {"device_id": NODE_A})
    assert saved.status_code == 200, saved.text
    assert selection.saves == [(directory.OWNER, directory.WORKSPACE, NODE_A)]
    # The name the owner chose is what the directory hands the browser.
    assert saved.json()["selectedDeviceId"] == NODE_A


def test_the_link_directory_is_a_question_only_when_it_cannot_be_asked() -> None:
    """No store and a failed read are different answers, and both keep the map.

    ``None`` means "the directory could not answer", which is exactly the
    situation a deployment with no 072 tables is in: the ownership map keeps
    behaving as it always did. An empty list means the account has no linked PC.
    """
    request = type("R", (), {"app": type("A", (), {"state": type("S", (), {})()})()})()
    assert RUN(linked_pc_targets(request, pairing.OWNER)) is None

    store = pairing.store()
    holder = type("S", (), {"pc_device_pairing_store": store})()
    asked = type("R", (), {"app": type("A", (), {"state": holder})()})()
    assert RUN(linked_pc_targets(asked, pairing.OWNER)) == []
    _linked(store, owner=pairing.OWNER, node=NODE_A)
    rows = RUN(linked_pc_targets(asked, pairing.OWNER))
    assert [row["mesh_node_id"] for row in rows] == [NODE_A]
    # A revoked link stops being a target without being deleted from history.
    RUN(store.revoke_link(user_id=pairing.OWNER, link_id=rows[0]["link_id"], now=pairing._now()))
    assert RUN(linked_pc_targets(asked, pairing.OWNER)) == []


