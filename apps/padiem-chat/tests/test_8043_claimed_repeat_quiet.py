"""#8043: a claimed code's own node re-reporting ends quietly even after expiry.

The store used to raise "pairing code expired" when the very node that claimed a
code re-reported its tag after the code's TTL -- once an hour per node of log
noise, though the link already stands and the repeat grants nothing. The expiry
of a spent code is irrelevant to its own node; only a different node naming the
spent tag is refused. Real sqlite with the pairing migrations applied; the clock
is injected and no other test file is imported.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.pc_device_pairing_store import (
    D1PcPairingStore,
    PcPairingError,
    derive_install_tag,
)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
OWNER = "usr_" + "a" * 32
NODE = "node//mesh-pc-01"
OTHER_NODE = "node/meshdomain/mesh-pc-02"
BASE = datetime(2026, 11, 20, 0, 0, 0, tzinfo=timezone.utc)


class _Statement:
    def __init__(self, conn, query):
        self.conn = conn
        self.query = query
        self.args: tuple = ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        cursor = self.conn.execute(self.query, self.args)
        return {"results": [dict(row) for row in cursor.fetchall()]}

    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row is not None else None


class _SQLiteD1:
    """The prepare/bind/run/first surface the D1 store uses, over real sqlite."""

    def __init__(self, conn):
        self.conn = conn

    def prepare(self, query):
        return _Statement(self.conn, query)


def _store():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    return D1PcPairingStore(_SQLiteD1(conn))


def _run(coro):
    return asyncio.run(coro)


def _issued(store, issued_at):
    issued = _run(store.issue_code(user_id=OWNER, issued_at=issued_at))
    return issued, derive_install_tag(issued["code"])


def test_own_node_repeat_of_a_claimed_expired_code_ends_quietly():
    store = _store()
    _, tag = _issued(store, BASE)
    link = _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=BASE + timedelta(minutes=1),
    ))
    assert link["state"] == "active"
    # The code's 10-minute TTL has long passed; the SAME node re-reports its tag.
    # The link stands, the repeat grants nothing, and it must not raise.
    result = _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=BASE + timedelta(minutes=20),
    ))
    assert result is None


def test_a_different_node_naming_the_spent_tag_is_still_refused():
    store = _store()
    _, tag = _issued(store, BASE)
    _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=BASE + timedelta(minutes=1),
    ))
    with pytest.raises(PcPairingError) as excinfo:
        _run(store.complete_claim_from_observation(
            agent_name=tag, mesh_node_id=OTHER_NODE, now=BASE + timedelta(minutes=20),
        ))
    assert str(excinfo.value) == "pairing code used"


def test_an_unclaimed_expired_code_is_cancelled_and_ends_quietly():
    store = _store()
    issued, tag = _issued(store, BASE)
    late = BASE + timedelta(minutes=20)
    assert _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=late,
    )) is None
    # The code was cancelled by the first observation, not left pending.
    with pytest.raises(PcPairingError) as excinfo:
        _run(store.peek_pairing_code(code=issued["code"], now=BASE))
    assert str(excinfo.value) == "pairing code used"
    # Re-offers of the same expired tag are silent from then on.
    assert _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=late + timedelta(minutes=5),
    )) is None


def test_four_expired_tags_are_quiet_on_every_reoffer_cycle():
    store = _store()
    nodes = ["node//mesh-pc-%d" % index for index in range(4)]
    tags = [_issued(store, BASE)[1] for _ in nodes]
    late = BASE + timedelta(minutes=20)
    for cycle in range(3):
        for node, tag in zip(nodes, tags):
            assert _run(store.complete_claim_from_observation(
                agent_name=tag, mesh_node_id=node,
                now=late + timedelta(minutes=5 * cycle),
            )) is None


def test_a_fresh_tag_from_a_reinstall_is_claimed_after_an_expired_one_goes_quiet():
    store = _store()
    _, tag = _issued(store, BASE)
    late = BASE + timedelta(minutes=20)
    assert _run(store.complete_claim_from_observation(
        agent_name=tag, mesh_node_id=NODE, now=late,
    )) is None
    _issued_fresh, fresh_tag = _issued(store, late)
    link = _run(store.complete_claim_from_observation(
        agent_name=fresh_tag, mesh_node_id=OTHER_NODE,
        now=late + timedelta(seconds=1),
    ))
    assert link["state"] == "active"
