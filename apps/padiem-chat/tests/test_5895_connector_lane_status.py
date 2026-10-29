"""#5895 — the lane's own counts and ages, which #82 monitoring reads.

Standard 4 says a stop must be known within ten minutes. On 2026-10-29 nothing could
answer "is work waiting that nobody is claiming?" without reading a log by hand: the
canary was silent, the queue's health endpoint is loopback-only, and the executor's
counters lived in its own process. The dispatch table already carried the answer in
columns the lane writes for its own reasons — `state`, `nonce_sha256`,
`claimed_until`, `expires_at`, `created_at`, `node_ref` — so this is a read, not a
new piece of state.

These run the real `D1HistoryStore` SQL against the real committed schema, because
the whole value of the read is that its conditions match the poll's conditions. A
drift between the two would either report an idle lane as stalled or hide a stalled
one as busy.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from app.history import HistoryError, ORACLE_MESH_CLAIM_LEASE_SECONDS
from test_4139_mesh_original import _dispatch_kwargs, fixture

STALE = "2000-01-01T00:00:00.000Z"
NODE_A = "node-com1-aaaa@bbbb"
NODE_B = "node-com2-cccc@dddd"


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _staged(store, run_id: str, **overrides) -> str:
    asyncio.run(store.record_claw_run(
        user_id="usr_owner_4139", run_id=run_id, channel="web", action="txt_read",
        title="Claw: lane status", status="pending",
        conversation_id="chat_" + "c" * 32, workspace_id="ws-1",
    ))
    fields = _dispatch_kwargs(run_id=run_id)
    fields["node_ref"] = NODE_A
    fields.update(overrides)
    return asyncio.run(store.create_oracle_mesh_dispatch(**fields))["dispatch_id"]


def _claim(store, dispatch_id: str, label: str = "poll") -> None:
    assert asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(label),
    )) is True


def _lane(store) -> dict:
    return asyncio.run(store.oracle_mesh_lane_status())


def test_an_empty_lane_reads_zero_and_no_age_rather_than_a_invented_number(tmp_path):
    store, _bucket = fixture(tmp_path)
    lane = _lane(store)
    assert lane["unclaimed"] == {"count": 0, "oldest_seconds": None}
    assert lane["claimed"] == {"count": 0, "oldest_seconds": None}
    assert lane["nodes"] == []


def test_queued_work_reads_as_waiting_for_a_claim(tmp_path):
    store, _bucket = fixture(tmp_path)
    _staged(store, "run-lane-queue")
    lane = _lane(store)
    assert lane["unclaimed"]["count"] == 1
    assert lane["claimed"]["count"] == 0
    assert lane["unclaimed"]["oldest_seconds"] is not None
    assert lane["unclaimed"]["oldest_seconds"] < 60, "it was staged a moment ago"
    assert lane["nodes"] == [
        {"node_ref": NODE_A, "open": 1, "oldest_seconds":
            lane["unclaimed"]["oldest_seconds"]},
    ]


def test_a_claim_moves_the_same_row_out_of_waiting_and_into_working(tmp_path):
    """The boundary the monitor's verdict turns on.

    One row, two states: while a live claim is held the work is not "waiting for a
    claim", and the same row returns the instant its lease runs out. That is the same
    comparison the poll yields on, so a stalled executor and a working one cannot be
    confused.
    """
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lane-claim")
    _claim(store, dispatch_id)

    lane = _lane(store)
    assert lane["unclaimed"]["count"] == 0
    assert lane["claimed"]["count"] == 1
    assert lane["claimed"]["oldest_seconds"] is not None

    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET claimed_until=? WHERE dispatch_id=?",
        STALE, dispatch_id,
    ))
    lane = _lane(store)
    assert lane["claimed"]["count"] == 0
    assert lane["unclaimed"]["count"] == 1, "an expired lease is waiting again"


def test_a_renewed_claim_stays_working_and_keeps_one_age(tmp_path):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _staged(store, "run-lane-renew")
    _claim(store, dispatch_id)
    before = _lane(store)["claimed"]
    assert asyncio.run(store.renew_oracle_mesh_claim(
        dispatch_id=dispatch_id, nonce_sha256=_nonce("poll"),
    )) is not None
    after = _lane(store)["claimed"]
    assert after["count"] == before["count"] == 1
    assert after["oldest_seconds"] >= before["oldest_seconds"], "age is from creation"
    assert after["oldest_seconds"] < ORACLE_MESH_CLAIM_LEASE_SECONDS + 60


def test_dispatch_past_its_own_life_is_in_no_bucket(tmp_path):
    """A dead row must not keep a monitor alerting forever.

    The dispatch's own expiry is the lane's outer bound; after it, neither "waiting"
    nor "working" applies, and the age that a monitor would otherwise report keeps
    growing without anything that can still be answered.
    """
    store, _bucket = fixture(tmp_path)
    doomed = _staged(store, "run-lane-doomed")
    assert _lane(store)["unclaimed"]["count"] == 1
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET expires_at=? WHERE dispatch_id=?",
        STALE, doomed,
    ))
    lane = _lane(store)
    assert lane["unclaimed"] == {"count": 0, "oldest_seconds": None}
    assert lane["claimed"]["count"] == 0
    assert lane["nodes"] == []


def test_per_pc_rows_are_grouped_and_the_oldest_pc_leads(tmp_path):
    store, _bucket = fixture(tmp_path)
    _staged(store, "run-lane-b-1", node_ref=NODE_B)
    _staged(store, "run-lane-b-2", node_ref=NODE_B)
    _staged(store, "run-lane-a-1", node_ref=NODE_A)

    lane = _lane(store)
    by_node = {row["node_ref"]: row for row in lane["nodes"]}
    assert by_node[NODE_B]["open"] == 2
    assert by_node[NODE_A]["open"] == 1
    assert by_node[NODE_A]["oldest_seconds"] >= by_node[NODE_B]["oldest_seconds"]
    assert [row["node_ref"] for row in lane["nodes"]][0] == NODE_B, "oldest first"


def test_the_pc_list_is_bounded_because_a_monitor_reads_it_on_a_schedule(tmp_path):
    store, _bucket = fixture(tmp_path)
    for index in range(10):
        _staged(store, f"run-lane-many-{index}", node_ref=f"node-{index}@x")
    lane = _lane(store)
    assert len(lane["nodes"]) == 8, "the presence-beat bound, not a new number"
    assert lane["unclaimed"]["count"] == 10, "the totals stay whole"
    assert len(asyncio.run(store.oracle_mesh_lane_status(node_limit=2))["nodes"]) == 2


def test_an_unusable_bound_is_refused_rather_than_read_as_zero(tmp_path):
    store, _bucket = fixture(tmp_path)
    for bad in (0, -1, 65, True, "8"):
        with pytest.raises(HistoryError):
            asyncio.run(store.oracle_mesh_lane_status(node_limit=bad))


def test_a_row_created_in_the_future_is_not_a_negative_wait(tmp_path):
    """Clock skew is a fact of two hosts, and an age must never read as negative."""
    store, _bucket = fixture(tmp_path)
    _staged(store, "run-lane-skew")
    ahead = (datetime.now(timezone.utc) + timedelta(seconds=600)).isoformat().replace(
        "+00:00", "Z",
    )
    asyncio.run(store._run(
        "UPDATE oracle_mesh_dispatch SET created_at=? WHERE 1=1", ahead,
    ))
    lane = _lane(store)
    assert lane["unclaimed"]["oldest_seconds"] == 0
    assert lane["nodes"][0]["oldest_seconds"] == 0
