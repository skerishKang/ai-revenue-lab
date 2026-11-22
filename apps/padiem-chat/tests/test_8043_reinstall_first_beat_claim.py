"""#8043: the beat after a reinstall claims with the NEW tag, in both stores.

The #7990/#7109 lesson is that a pairing contract must be exercised through the
D1 store *and* the queue-backed proxy — a single-store test misses allowlist or
serialisation drift. A fake clock fixes issue=install, +24s=first beat, and the
code's ten-minute TTL, so the timing claim is deterministic.

Scenario vocabulary (no account, token or code value is ever printed):
  * install at T0  -> a code/tag is issued with a 600s TTL;
  * beat at T0+24s -> the agent name carries the NEW tag -> claim completes;
  * beat with only the OLD (already spent/expired) tag -> still expired;
  * no cross-account / cross-node link is ever created.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CHAT = ROOT / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _support.pc_device_pairing as pairing
import test_queue_pairing_managed_parity as qp
from app.pc_device_pairing_store import (
    PcPairingError,
    derive_install_tag,
)
from app.queue_store_proxy import (
    QueueBackedPairingStore,
    QueueUnavailable,
)

RUN = pairing.run
OWNER = pairing.OWNER
OTHER = pairing.OTHER
NEW_NODE = "node//8043-new"
OLD_NODE = "node//8043-old"

T0 = datetime(2026, 11, 19, 4, 45, 6, tzinfo=timezone.utc)
BEAT = T0 + timedelta(seconds=24)          # install +24s — inside the 600s TTL
STALE_ISSUED = T0 - timedelta(minutes=11)  # an old code already past its TTL

#: The queue answers a store refusal as a 502 -> QueueUnavailable, while the D1
#: store raises PcPairingError directly. Both are the "refused" outcome here.
REFUSAL = {"local": PcPairingError, "queue": QueueUnavailable}


def _issue(store, *, owner=OWNER, at=T0):
    return RUN(store.issue_code(user_id=owner, issued_at=at))


def _name(tag):
    # A bare tag is enough: with no presented token the gate checks the code's
    # own binding, which still stands inside the TTL.
    return f"{tag} [C D] NEEDR-PC"


def _local():
    return pairing.store()


def _queue():
    return QueueBackedPairingStore(qp._client(qp._queue_app(qp._db())))


@pytest.fixture(params=["local", "queue"])
def store(request):
    """The same contract over the D1 store and the queue-backed proxy."""
    kind = request.param
    return kind, (_local() if kind == "local" else _queue())


# -- 1. the +24s beat with the NEW tag completes the claim -------------------

def test_first_beat_after_reinstall_claims_with_new_tag(store):
    _, db = store
    issued = _issue(db)
    new_tag = derive_install_tag(issued["code"])

    link = RUN(db.complete_claim_from_observation(
        agent_name=_name(new_tag), mesh_node_id=NEW_NODE, now=BEAT,
    ))

    assert link["state"] == "active"
    assert link["mesh_node_id"] == NEW_NODE
    links = RUN(db.list_links(user_id=OWNER))
    assert [row["mesh_node_id"] for row in links] == [NEW_NODE]


def test_the_new_tag_is_usable_through_the_whole_ttl_window(store):
    _, db = store
    issued = _issue(db)
    tag = derive_install_tag(issued["code"])
    # The TTL deliberately stays at 600s: the fix is about *when* the claim
    # arrives, not about stretching the code's life.
    link = RUN(db.complete_claim_from_observation(
        agent_name=_name(tag), mesh_node_id=NEW_NODE,
        now=T0 + timedelta(seconds=599),
    ))
    assert link["state"] == "active"


# -- 2. an OLD tag alone stays expired ---------------------------------------

def test_old_tag_only_beat_stays_expired(store):
    kind, db = store
    old = _issue(db, at=STALE_ISSUED)
    old_tag = derive_install_tag(old["code"])
    fresh = _issue(db, at=T0)          # a new code exists but is not in the beat

    assert RUN(db.complete_claim_from_observation(
        agent_name=_name(old_tag), mesh_node_id=NEW_NODE, now=BEAT,
    )) is None
    # Nothing was claimed for either code; the fresh one is still peekable.
    assert RUN(db.list_links(user_id=OWNER)) == []
    fresh_row = RUN(db.peek_pairing_code(code=fresh["code"], now=BEAT))
    assert fresh_row["code_id"] == fresh["code_id"]


# -- 3. no cross-account or cross-node mixing --------------------------------

def test_another_accounts_tag_claims_only_that_account(store):
    _, db = store
    _issue(db, at=T0)                  # my code is issued but not used
    other = _issue(db, owner=OTHER, at=T0)
    other_tag = derive_install_tag(other["code"])

    link = RUN(db.complete_claim_from_observation(
        agent_name=_name(other_tag), mesh_node_id=NEW_NODE, now=BEAT,
    ))
    assert link["user_id"] == OTHER
    # The tag belongs to exactly one account: my account gained nothing, and
    # the shared node carries each owner's own independent link.
    assert RUN(db.list_links(user_id=OWNER)) == []
    assert [row["mesh_node_id"] for row in RUN(db.list_links(user_id=OTHER))] == [NEW_NODE]


def test_a_spent_tag_from_a_different_node_is_refused(store):
    kind, db = store
    issued = _issue(db)
    tag = derive_install_tag(issued["code"])
    RUN(db.complete_claim_from_observation(
        agent_name=_name(tag), mesh_node_id=NEW_NODE, now=BEAT,
    ))
    with pytest.raises(REFUSAL[kind]) as refused:
        RUN(db.complete_claim_from_observation(
            agent_name=_name(tag), mesh_node_id=OLD_NODE, now=BEAT,
        ))
    if kind == "local":
        assert str(refused.value) == "pairing code used"
    assert [row["mesh_node_id"] for row in RUN(db.list_links(user_id=OWNER))] == [NEW_NODE]


# -- 4. the one-hour refusal log window is unchanged -------------------------

def test_refusal_log_suppresses_repeats_for_one_hour_and_opens_a_new_window():
    from app.oracle_mesh_read_return_routes import _PairingRefusalLog

    clock = {"t": 0.0}
    tracker = _PairingRefusalLog(now_func=lambda: clock["t"])
    records = []

    class _Logger:
        def warning(self, fmt, *args):
            records.append(("warning", fmt % args if args else fmt))

        def info(self, fmt, *args):
            records.append(("info", fmt % args if args else fmt))

    logger = _Logger()
    tracker.record(logger, "abc123", "pairing code expired")
    clock["t"] = 30.0
    tracker.record(logger, "abc123", "pairing code expired")
    clock["t"] = 3599.0
    tracker.record(logger, "abc123", "pairing code expired")

    assert [level for level, _ in records] == ["warning"]
    assert "reason=pairing code expired" in records[0][1]
    assert "node=abc123" in records[0][1]

    clock["t"] = 3601.0
    tracker.record(logger, "abc123", "pairing code expired")
    assert [level for level, _ in records] == ["warning", "info", "warning"]
    assert "count=2" in records[1][1]
