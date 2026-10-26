"""#5573 PR-2: the PC file lane takes its target from the account's own links.

Before migration 072 the only answer to "which PC is this and which folder may it
read" was the deployment ownership map the Owner edits by hand. These tests drive
the real signed Engine file call with BOTH authorities present, so the direction
of the change is provable and not merely asserted:

* a paired account dispatches to *its* node and *its* approved folder, and the
  map's node and folder never appear in the command;
* an account the directory answered for is bounded by that answer — an empty
  directory is a refusal, not a fallthrough to the map;
* revoking the link stops the lane on the very next call;
* with two approved folders the label is the namespace, and a bare relative path
  is refused rather than guessed.

The map fallback itself is the whole of ``test_5015_pc_read_dispatch.py``: those
tests run with no pairing store composed and must stay green.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

import test_5015_pc_read_dispatch as lane          # noqa: E402
import test_5573_pc_device_pairing as pairing      # noqa: E402

from app import oracle_mesh_read_return_routes as routes  # noqa: E402

LINK_NODE = "node/meshdomain/mesh-pc-09"
QUOTATION = "C:/Users/beta/견적"
ACCOUNTING = "C:/Users/beta/경리"


def _pair(*, roots: tuple[str, ...] = (QUOTATION,), revoke: bool = False):
    """One real 072 link for the lane's OWNER, approved over `roots`."""
    store = pairing.store()

    async def build():
        issued = await store.issue_code(user_id=lane.OWNER, issued_at=pairing._now())
        link = await store.redeem_code(
            code=issued["code"], mesh_node_id=LINK_NODE, label="베타 PC",
            now=pairing._now(), verified=True,
        )
        for path in roots:
            await store.approve_root(
                user_id=lane.OWNER, link_id=link["link_id"], path=path,
                now=pairing._now(),
            )
        if revoke:
            await store.revoke_link(
                user_id=lane.OWNER, link_id=link["link_id"], now=pairing._now(),
            )
        return link

    return store, pairing.run(build())


def _state(monkeypatch, *, pairing_store=None, roots=(QUOTATION,), revoke=False):
    state = lane._state(monkeypatch)
    if pairing_store is None:
        pairing_store, _ = _pair(roots=roots, revoke=revoke)
    state.pc_device_pairing_store = pairing_store
    return state


# -- the directory decides the target, and the map does not get a vote ------

def test_a_paired_account_lists_its_own_folder_on_its_own_node(monkeypatch):
    state = _state(monkeypatch)

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["node_ref"] == LINK_NODE
    assert row["kind"] == "command"
    assert QUOTATION in row["command_text"]
    # The deployment map's device and folder are simply absent: the link, not
    # the operator's row, decided where this command goes.
    assert lane.ROOT not in row["command_text"]
    assert lane.NODE != LINK_NODE


def test_context_names_the_owner_folders_and_no_real_path(monkeypatch):
    state = _state(monkeypatch)

    status, body = lane._dispatch(state, lane._context_payload())
    assert status == 200, body
    assert body["roots"] == [{"label": "견적"}]
    assert QUOTATION not in json.dumps(body, ensure_ascii=False)


# -- no link is a refusal, never a fallthrough ------------------------------

def test_no_link_falls_back_to_the_map_only_while_the_owner_has_not_claimed_yet(monkeypatch):
    """#5906 hotfix (b), transitional on purpose.

    An account with no link uses the deployment map row it already had, so
    production devices keep working until the Owner claims them through the
    pairing flow. This is NOT a widening: the map still only answers for the
    account the map itself pins.
    """
    empty = pairing.store()
    state = _state(monkeypatch, pairing_store=empty)

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["node_ref"] == lane.NODE and lane.ROOT in row["command_text"]


def test_an_account_with_nothing_to_use_gets_no_pc_tools_and_no_failure(monkeypatch):
    """#5906 hotfix (a): the real chat-breaking case.

    Tool discovery must answer 200 with no roots and no PC tools when this
    account has neither a link nor a mapped device. Before this it answered 403,
    and an ordinary chat turn that only asked what tools exist read as a failure.
    """
    state = _state(monkeypatch, pairing_store=pairing.store())
    state.oracle_mesh_return_source = routes.build_oracle_mesh_return_source(
        [{**lane._mapping()[0], "account_ref": "someone-else"}],
        lane.CHANNEL_SECRET, routes.EXECUTION_MODE_MESH,
    )

    status, body = lane._dispatch(state, lane._context_payload())
    assert status == 200, body
    assert body["roots"] == [] and body["tools"] == []
    assert body["device"]["status"] == "not_connected"
    assert state.history_store.status_writes == []
    assert state.history_store.run_rows[lane.RUN]["status"] == "pending"
    assert state.history_store.rows == {}

    refused, refused_body = lane._dispatch(state, lane._base_payload())
    assert refused == 403 and refused_body["error"]["code"] == "oracle_mesh_device_unverified"
    assert state.history_store.rows == {}


def test_revoking_the_link_leaves_only_what_the_map_still_pins(monkeypatch):
    """R5 with the transitional fallback, stated exactly.

    Revoking kills the link's own authority — its folders and its node. What
    survives is the *separate* deployment map row for the same account, which is
    the thing scheduled for deletion once the Owner claims their PCs (TODO in the
    route). The revoked node and its folder never come back: the dispatch below
    runs on the map's device and the map's folder, not the link's.
    """
    state = _state(monkeypatch, revoke=True)

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["node_ref"] == lane.NODE != LINK_NODE
    assert QUOTATION not in row["command_text"] and lane.ROOT in row["command_text"]


# -- two approved folders: the label is the namespace ----------------------

def test_two_roots_require_the_label_and_it_selects_the_exact_folder(monkeypatch):
    state = _state(monkeypatch, roots=(QUOTATION, ACCOUNTING))

    refused, _ = lane._dispatch(state, lane._base_payload(
        op="read", path="notes.txt", tool_call_ref=lane.READ_CALL,
    ))
    # Nothing was staged: the server refused to choose between two of the
    # owner's folders on their behalf.
    assert refused == 422, refused
    assert state.history_store.rows == {}

    status, body = lane._dispatch(state, lane._base_payload(
        op="read", path="견적/notes.txt", tool_call_ref=lane.READ_CALL,
    ))
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["kind"] == "read"
    assert row["file_path"] == QUOTATION + "/notes.txt"
    assert row["node_ref"] == LINK_NODE


def test_two_roots_are_offered_as_labels_for_the_model(monkeypatch):
    state = _state(monkeypatch, roots=(QUOTATION, ACCOUNTING))

    status, body = lane._dispatch(state, lane._context_payload())
    assert status == 200, body
    assert [root["label"] for root in body["roots"]] == ["견적", "경리"]
    assert ACCOUNTING not in json.dumps(body, ensure_ascii=False)


def test_one_folder_accepts_the_label_or_a_bare_relative_path_alike(monkeypatch):
    """Naming the one folder is redundant, not a different request.

    A model that learned the label from context and a model that skipped it both
    mean the same approved folder; neither can reach a subfolder that happens to
    share the label's spelling, because the label is consumed only as a prefix.
    """
    state = _state(monkeypatch)

    bare_status, bare = lane._dispatch(state, lane._base_payload(
        op="read", path="notes.txt", tool_call_ref=lane.READ_CALL,
    ))
    named_status, named = lane._dispatch(state, lane._base_payload(
        op="read", path="견적/notes.txt",
        tool_call_ref=lane.READ_CALL + "0",
    ))
    assert bare_status == named_status == 200, (bare, named)
    assert (
        state.history_store.rows[bare["dispatch"]["dispatch_id"]]["file_path"]
        == state.history_store.rows[named["dispatch"]["dispatch_id"]]["file_path"]
        == QUOTATION + "/notes.txt"
    )

    outside_status, _ = lane._dispatch(state, lane._base_payload(
        op="read", path="견적/../경리/notes.txt",
        tool_call_ref=lane.READ_CALL + "1",
    ))
    assert outside_status == 422


# -- the map still answers when there is no directory to ask --------------

def test_an_unapplied_migration_falls_back_to_the_map_unchanged(monkeypatch):
    state = lane._state(monkeypatch)

    class Unapplied:
        async def links_for_owner(self, **values):
            raise RuntimeError("no such table: pc_device_links")

    state.pc_device_pairing_store = Unapplied()

    status, body = lane._dispatch(state, lane._base_payload())
    assert status == 200, body
    row = state.history_store.rows[body["dispatch"]["dispatch_id"]]
    assert row["node_ref"] == lane.NODE
    assert lane.ROOT in row["command_text"]

    context_status, context_body = lane._dispatch(state, lane._context_payload())
    assert context_status == 200, context_body
    # The folder's own name is what the map has always exposed as the root.
    assert context_body["roots"] == [{"label": lane.ROOT.rsplit("/", 1)[-1]}]


def test_the_module_owns_its_refusal_vocabulary():
    # Guards against a fallback that quietly becomes a guess: the refusal the
    # directory produces is the existing one, so no new user-facing sentence is
    # introduced by this slice.
    assert routes.__dict__["_pc_files_directory_target"] is not None
    assert callable(routes._pc_files_pick_root)
    assert routes._pc_files_pick_root(
        [{"label": "견적", "path": QUOTATION}], "견적/../Windows",
    ) is None


# -- presence: the receipt is keyed by the server's own node identity -------

def _presence_store():
    from app.mesh_device_presence_store import D1MeshDevicePresenceStore

    return D1MeshDevicePresenceStore(pairing.RealSQLiteD1(pairing.database()))


def _record(state, entries):
    request = type("R", (), {"app": type("A", (), {"state": state})()})()
    pairing.run(routes._record_mesh_presence(request, state.oracle_mesh_return_source, entries))


def test_a_paired_node_is_recorded_under_the_servers_composed_identity(monkeypatch):
    store = _presence_store()
    state = _state(monkeypatch)
    state.mesh_device_presence_store = store

    _record(state, [{"device_id": LINK_NODE, "connected": True}])

    receipt = pairing.run(store.load(device_id=LINK_NODE))
    assert receipt is not None
    assert receipt["device_id"] == LINK_NODE
    # Nothing resolved a Broker credential generation for a paired PC, and that
    # is a Mesh-only receipt, not a failure (#5553 requirement 6).
    assert receipt["source"] == "mesh"
    assert receipt["credential_generation"] is None


def test_presence_falls_back_to_the_map_for_a_device_the_directory_does_not_name(monkeypatch):
    store = _presence_store()
    state = _state(monkeypatch)
    state.mesh_device_presence_store = store

    # The map's own device still records exactly as it did before PR-2.
    _record(state, [{"device_id": lane.DEVICE, "connected": True}])
    assert pairing.run(store.load(device_id=lane.DEVICE)) is not None

    # A revoked link stops feeding presence too: the node is neither linked nor
    # mapped, so nothing is written rather than something being guessed.
    revoked = _state(monkeypatch, revoke=True)
    revoked.mesh_device_presence_store = store
    _record(revoked, [{"device_id": LINK_NODE, "connected": True}])
    assert pairing.run(store.load(device_id=LINK_NODE)) is None
