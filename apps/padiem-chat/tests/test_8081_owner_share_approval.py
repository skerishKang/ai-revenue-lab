"""#8081 — the owner's own connection card approves reported share units.

The card calls the existing owner-scoped endpoint; this file proves the rendered
action, the scope after approval, another member's refusal, and that a guest
page makes no pairing API call. No screenshot and no raw-source copy assertion.
"""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from app.d1_sqlite import SqliteD1
from app.local_cpython import apply_migrations
from app.pc_device_pairing_store import D1PcPairingStore, PcPairingError

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "static"
MODULE = STATIC / "pc-pairing-card.js"
HARNESS = HERE / "pc_pairing_card_harness.js"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is required for the browser harness")

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
SHARE = "//fileserver/sharename"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "pairing.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    for index, user in enumerate((OWNER, OTHER)):
        connection.execute(
            "INSERT INTO users (id, auth_provider, provider_subject, email, display_name, "
            "picture_url, created_at, updated_at) VALUES (?, 'google', ?, "
            "'owner@example.test', '', '', '2026-11-19T00:00:00Z', '2026-11-19T00:00:00Z')",
            (user, f"sub_8081_{index}"),
        )
    return D1PcPairingStore(SqliteD1(connection)), connection


def _claim(store, user, node):
    issued = asyncio_run(store.issue_code(user_id=user, issued_at=_now() - timedelta(minutes=1)))
    return asyncio_run(store.complete_claim_from_observation(
        agent_name=issued["install_tag"] + " [C] {Z:=" + SHARE + "} MACHINE",
        mesh_node_id=node, now=_now(),
    ))


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


def _public_link(store, link_id):
    return next(row for row in asyncio_run(store.list_links(user_id=OWNER))
                if row["link_id"] == link_id)


def _run_harness():
    result = subprocess.run([NODE, str(HARNESS), str(MODULE)], capture_output=True,
                            text=True, timeout=120, encoding="utf-8", errors="replace",
                            check=False)
    return result.stdout + result.stderr


def test_the_owner_card_action_and_guest_contract_run_in_the_harness():
    output = _run_harness()
    assert "PC_PAIRING_CARD=PASS" in output
    for name in (
        "the owner card shows a reported share and the consent action",
        "approving a share posts only its reference and the consent sentence",
        "after approval the candidate action is gone from the owner card",
        "a guest makes no pairing API calls",
    ):
        assert "PC_PAIRING_CARD_CHECK " + name + " PASS" in output, name


def test_only_the_approved_share_is_in_scope_and_another_member_cannot_approve(tmp_path):
    store, db = _store(tmp_path)
    try:
        owner_link = _claim(store, OWNER, "node//mesh-owner")
        other_link = _claim(store, OTHER, "node//mesh-other")
        assert owner_link["link_id"] != other_link["link_id"]
        share_ref = next(
            row["root_ref"]
            for row in _public_link(store, owner_link["link_id"])["share_candidates"]
            if row["path"] == SHARE
        )
        # The other member's signed-in approval is refused by the store's owner
        # re-check, without saying whether that link exists.
        with pytest.raises(PcPairingError):
            asyncio_run(store.approve_share_candidate(
                user_id=OTHER, link_id=owner_link["link_id"],
                root_ref=share_ref, now=_now()))
        # The owner's own approval grants exactly one share unit.
        approved = asyncio_run(store.approve_share_candidate(
            user_id=OWNER, link_id=owner_link["link_id"],
            root_ref=share_ref, now=_now()))
        assert approved["path"] == SHARE and approved["state"] == "active"
        scope = asyncio_run(store.link_for(user_id=OWNER, mesh_node_id="node//mesh-owner"))
        assert [root["path"] for root in scope["roots"]] == ["C:", SHARE]
        other_scope = asyncio_run(store.link_for(user_id=OTHER, mesh_node_id="node//mesh-other"))
        assert [root["path"] for root in other_scope["roots"]] == ["C:"]
    finally:
        db.close()

