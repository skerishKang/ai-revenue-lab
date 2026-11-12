"""#7624: a pending link bound to an older code still activates.

The install walk renames the agent to the newest code's tag, so the presence
beat can carry a tag that is younger than the binding a typed claim left
behind. The observation now binds the account's own `pending_verification`
row to the observed code and activates it - once, and only when the observed
tag belongs to a live code of the same account and the same PC. Nothing else
moves: another account's row, another PC's row and an already active row are
untouched, the drives granted are the ones the observation saw, and the typed
claim still lands in `pending_verification` activating nothing by itself.

Every store here is the real SQLite database with the real migrations applied;
`pairing_code_id` is read from the raw rows because the public link projection
never exposes it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.pc_device_pairing_store import D1PcPairingStore, PcPairingError, derive_install_tag

from test_5573_pc_device_pairing import (
    NODE,
    OTHER,
    OTHER_NODE,
    OWNER,
    RealSQLiteD1,
    database,
)

NOW = datetime.now(timezone.utc)


def _pair():
    conn = database(with_072=True)
    return D1PcPairingStore(RealSQLiteD1(conn)), conn


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _issue(store, user_id, *, issued_at=None):
    return _run(store.issue_code(
        user_id=user_id, issued_at=issued_at or NOW))


def _claim(store, code, node=NODE):
    return _run(store.redeem_code(
        code=code, mesh_node_id=node, label=None, now=NOW, verified=False))


def _observe(store, code, node=NODE, *, now=None):
    agent_name = derive_install_tag(code) + " [C: D:] PC-OFFICE"
    return _run(store.complete_claim_from_observation(
        agent_name=agent_name, mesh_node_id=node, now=now or NOW))


def _raw_row(conn, *, user_id, node):
    row = conn.execute(
        "SELECT state, pairing_code_id, updated_at FROM pc_device_links "
        "WHERE user_id=? AND mesh_node_id=?",
        (user_id, node),
    ).fetchone()
    return dict(row) if row else None


def _observe_twice(store, code, node=NODE):
    first = _observe(store, code, node)
    second = _observe(store, code, node)
    return first, second


def test_a_pending_row_bound_to_an_older_code_activates_on_a_newer_codes_observation():
    store, conn = _pair()
    # The first install: the observation claims and activates the link.
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    assert _raw_row(conn, user_id=OWNER, node=NODE)["state"] == "active"
    # Re-pair: revoke, claim a new code (typed claim -> pending, bound to it),
    # then run the renewed install so the beat carries a NEWER code's tag.
    links = _run(store.list_links(user_id=OWNER))
    assert _run(store.revoke_link(
        user_id=OWNER, link_id=links[0]["link_id"], now=NOW)) is True
    c2 = _issue(store, OWNER)
    _claim(store, c2["code"])
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "pending_verification"
    assert row["pairing_code_id"] == c2["code_id"]
    c3 = _issue(store, OWNER)
    completed = _observe(store, c3["code"])
    assert completed is not None and completed.get("_promoted") is True
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "active"
    # The row is bound to the code whose observation promoted it.
    assert row["pairing_code_id"] == c3["code_id"]


def test_another_accounts_code_tag_never_promotes_another_accounts_pending_row():
    store, conn = _pair()
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    links = _run(store.list_links(user_id=OWNER))
    _run(store.revoke_link(user_id=OWNER, link_id=links[0]["link_id"], now=NOW))
    c2 = _issue(store, OWNER)
    _claim(store, c2["code"])
    # Account B issues its own live code for the same PC and its install runs.
    other_code = _issue(store, OTHER)
    assert _observe(store, other_code["code"]) is not None
    # A's pending row keeps its own binding and stays pending.
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "pending_verification"
    assert row["pairing_code_id"] == c2["code_id"]
    # B's own fresh link is the standard lane, keyed to B's account.
    other_row = _raw_row(conn, user_id=OTHER, node=NODE)
    assert other_row["state"] == "active"
    assert other_row["pairing_code_id"] == other_code["code_id"]


def test_another_nodes_observation_never_promotes_the_pending_row():
    store, conn = _pair()
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    links = _run(store.list_links(user_id=OWNER))
    _run(store.revoke_link(user_id=OWNER, link_id=links[0]["link_id"], now=NOW))
    c2 = _issue(store, OWNER)
    _claim(store, c2["code"])
    c3 = _issue(store, OWNER)
    assert _observe(store, c3["code"], node=OTHER_NODE) is not None
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "pending_verification"
    assert row["pairing_code_id"] == c2["code_id"]


def test_an_expired_codes_tag_never_promotes():
    store, conn = _pair()
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    links = _run(store.list_links(user_id=OWNER))
    _run(store.revoke_link(user_id=OWNER, link_id=links[0]["link_id"], now=NOW))
    c2 = _issue(store, OWNER)
    _claim(store, c2["code"])
    stale = _issue(store, OWNER, issued_at=NOW - timedelta(
        seconds=601 + 60))
    with_error = None
    try:
        _observe(store, stale["code"])
    except PcPairingError as exc:
        with_error = str(exc)
    assert with_error is not None and "expired" in with_error
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "pending_verification"


def test_two_beats_racing_the_same_rename_promote_exactly_once():
    store, conn = _pair()
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    links = _run(store.list_links(user_id=OWNER))
    _run(store.revoke_link(user_id=OWNER, link_id=links[0]["link_id"], now=NOW))
    c2 = _issue(store, OWNER)
    _claim(store, c2["code"])
    c3 = _issue(store, OWNER)
    first, second = _observe_twice(store, c3["code"])
    promoted = [item for item in (first, second) if item is not None and item.get("_promoted")]
    assert len(promoted) == 1
    row = _raw_row(conn, user_id=OWNER, node=NODE)
    assert row["state"] == "active"
    assert row["pairing_code_id"] == c3["code_id"]


def test_an_already_active_row_is_never_rebound_or_reverified():
    store, conn = _pair()
    c1 = _issue(store, OWNER)
    assert _observe(store, c1["code"]) is not None
    before = _raw_row(conn, user_id=OWNER, node=NODE)
    assert before["state"] == "active"
    c2 = _issue(store, OWNER)
    completed = _observe(store, c2["code"])
    # The established PC is not re-verified: the row keeps its own binding.
    assert completed is not None and not completed.get("_promoted")
    after = _raw_row(conn, user_id=OWNER, node=NODE)
    assert after["state"] == "active"
    assert after["pairing_code_id"] == c1["code_id"]
    assert after["updated_at"] == before["updated_at"]


def test_two_accounts_on_one_pc_stay_connected_side_by_side():
    store, conn = _pair()
    a1 = _issue(store, OWNER)
    assert _observe(store, a1["code"]) is not None
    # Account B adds the same PC: a typed claim (pending) then the renewed
    # install whose beat carries B's newer code tag.
    b1 = _issue(store, OTHER)
    _claim(store, b1["code"])
    b2 = _issue(store, OTHER)
    assert _observe(store, b2["code"]) is not None
    a_row = _raw_row(conn, user_id=OWNER, node=NODE)
    b_row = _raw_row(conn, user_id=OTHER, node=NODE)
    assert a_row["state"] == "active"
    assert a_row["pairing_code_id"] == a1["code_id"]
    assert b_row["state"] == "active"
    assert b_row["pairing_code_id"] == b2["code_id"]


def test_the_typed_claim_still_lands_in_pending_verification_only():
    store, conn = _pair()
    code = _issue(store, OWNER)["code"]
    claimed = _claim(store, code)
    assert claimed["state"] == "pending_verification"
    assert _raw_row(conn, user_id=OWNER, node=NODE)["state"] == "pending_verification"
    granted = [root["path"] for root in claimed["roots"] if root["state"] == "active"]
    assert granted == []
