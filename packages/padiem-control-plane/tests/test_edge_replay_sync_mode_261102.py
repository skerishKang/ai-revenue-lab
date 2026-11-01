"""#6604 / #6611 — the replay store's durability mode, and what `normal` saves.

`full` is what COM2 has always served: one connection per request, rollback
journal, synchronous FULL — one fsync per signed request. `normal` keeps every
ordering guarantee (one BEGIN IMMEDIATE · INSERT · COMMIT per request, unique
request id, one verify at a time) and moves the fsync out of the request path by
holding one connection in WAL with synchronous=NORMAL and checkpointing on a
separate connection off that path.

Nothing here weakens replay detection: the same id presented twice is refused in
both modes, including after a restart, because the row is committed (durably in
`full`, in the WAL in `normal`) either way.
"""
import hashlib
import hmac
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from com2_edge_proof import (
    SYNC_MODE_ENV,
    EdgeProofVerifier,
    replay_sync_mode,
)

SECRET = "synthetic-test-" + "x" * 32
PATH = "/api/claw/connector/gateway/session"


def headers(request_id="a" * 32, at=1000, tls="TLSv1.3", path=PATH):
    signed = "\n".join(("v1", "GET", path, str(at), request_id, tls)).encode()
    proof = "v1=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-edge-at": str(at), "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": tls, "x-padiem-edge-proof": proof}


def pragmas(verifier):
    """The store's journal mode (a file property) and the commit durability
    that a request connection actually carries (a connection property)."""
    with closing(sqlite3.connect(verifier._db)) as db:
        journal = db.execute("PRAGMA journal_mode").fetchone()[0].lower()
    with closing(verifier._connect()) as db:
        synchronous = db.execute("PRAGMA synchronous").fetchone()[0]
    return journal, synchronous


def test_unset_or_unknown_environment_means_the_unchanged_full_commit(tmp_path, monkeypatch):
    monkeypatch.delenv(SYNC_MODE_ENV, raising=False)
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db))
    assert verifier.sync_mode == "full"
    assert pragmas(verifier) == ("delete", 2)    # rollback journal, synchronous FULL
    assert verifier.verify(method="GET", path=PATH, headers=headers(), now=1000) is True

    for value in ("", " fast ", "0", "OFF", "wal", "\n"):
        monkeypatch.setenv(SYNC_MODE_ENV, value)
        assert replay_sync_mode() == "full", value


def test_normal_opens_the_store_in_wal_with_a_normal_commit(tmp_path, monkeypatch):
    monkeypatch.setenv(SYNC_MODE_ENV, "normal")
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db))
    assert verifier.sync_mode == "normal"
    assert pragmas(verifier) == ("wal", 1)
    assert verifier.verify(method="GET", path=PATH, headers=headers(), now=1000) is True
    # The request path must not checkpoint on its own: the held connection has
    # SQLite's automatic checkpointing off and the verifier schedules PASSIVE
    # checkpoints itself.
    assert verifier._held().execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_the_same_signed_request_twice_is_refused_in_both_modes(tmp_path, mode):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode=mode)
    proof = headers("b" * 32)
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is True
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is False
    # A restart re-reads the same store: the consumed id stays consumed.
    assert EdgeProofVerifier(SECRET, str(db), sync_mode=mode).verify(
        method="GET", path=PATH, headers=proof, now=1001) is False
    # And a forged or stale proof is still refused, not merely unrecorded.
    forged = dict(proof, **{"x-padiem-edge-proof": "v1=" + "0" * 64})
    assert verifier.verify(method="GET", path=PATH, headers=forged, now=1000) is False
    assert verifier.verify(
        method="GET", path=PATH, headers=headers("c" * 32, at=699), now=1000) is False
    verifier.close()


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_a_refused_replay_leaves_exactly_one_row(tmp_path, mode):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode=mode)
    proof = headers("d" * 32)
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is True
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is False
    verifier.close()
    with closing(sqlite3.connect(str(db))) as conn:
        rows = conn.execute("SELECT request_id, expires_at FROM edge_proof_seen").fetchall()
    assert rows == [("d" * 32, 1300)]            # one bounded row, no duplicate


def test_going_back_to_full_returns_the_rollback_journal(tmp_path, monkeypatch):
    db = tmp_path / "replay.sqlite3"
    monkeypatch.setenv(SYNC_MODE_ENV, "normal")
    normal = EdgeProofVerifier(SECRET, str(db))
    assert normal.sync_mode == "normal"
    assert pragmas(normal)[0] == "wal"
    normal.close()
    monkeypatch.setenv(SYNC_MODE_ENV, "full")
    restored = EdgeProofVerifier(SECRET, str(db))
    assert restored.sync_mode == "full"
    assert pragmas(restored) == ("delete", 2)
    # The ids consumed while the store was in WAL are still refused.
    assert restored.verify(method="GET", path=PATH, headers=headers(), now=1000) is True


def test_normal_serves_two_hundred_requests_from_one_connection(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def counting(database, *args, **kwargs):
        opened.append(database)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode="normal",
                                 checkpoint_every=10_000, checkpoint_seconds=10_000)
    for index in range(200):
        assert verifier.verify(method="GET", path=PATH,
                               headers=headers(f"{index:032x}"), now=1000) is True
    # One setup connection in __init__, then the held one: no per-request open.
    assert len(opened) == 2, len(opened)
    assert verifier._held() is verifier._held()
    verifier.close()


def test_full_still_opens_one_connection_per_request(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    def counting(database, *args, **kwargs):
        opened.append(database)
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", counting)
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db))
    assert verifier.sync_mode == "full"
    for index in range(20):
        assert verifier.verify(method="GET", path=PATH,
                               headers=headers(f"{index:032x}"), now=1000) is True
    assert len(opened) == 21, len(opened)         # setup + one per request, as before


def test_a_lost_connection_is_reopened_once_and_the_replay_is_still_refused(tmp_path):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode="normal")
    assert verifier.verify(method="GET", path=PATH, headers=headers("e" * 32), now=1000) is True
    verifier._conn.close()                        # the volume took the handle away
    assert verifier.verify(method="GET", path=PATH, headers=headers("f" * 32), now=1000) is True
    # The reopened connection reads the same store, so ids stay consumed.
    assert verifier.verify(method="GET", path=PATH, headers=headers("f" * 32), now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=headers("e" * 32), now=1000) is False
    verifier.close()


def test_the_checkpoint_does_not_run_on_the_request_path(tmp_path, monkeypatch):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode="normal",
                                 checkpoint_every=3, checkpoint_seconds=10_000)
    started, release, threads = threading.Event(), threading.Event(), []

    def slow_checkpoint():
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(5)

    monkeypatch.setattr(verifier, "_checkpoint", slow_checkpoint)
    for index in range(3):
        assert verifier.verify(method="GET", path=PATH,
                               headers=headers(f"{index:032x}"), now=1000) is True
    returned_before_checkpoint_finished = not release.is_set()
    assert started.wait(5)
    assert threads and threads[0] != threading.current_thread().name
    assert returned_before_checkpoint_finished
    # While it is still holding, the next request is served, not queued behind it.
    started_at = time.monotonic()
    assert verifier.verify(method="GET", path=PATH, headers=headers("9" * 32), now=1000) is True
    assert time.monotonic() - started_at < 1.0
    release.set()
    verifier.close()


def test_eight_concurrent_verifies_stay_ordered_and_all_accepted(tmp_path):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode="normal",
                                 checkpoint_every=10_000, checkpoint_seconds=10_000)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(
            lambda index: verifier.verify(method="GET", path=PATH,
                                          headers=headers(f"{index:032x}"), now=1000),
            range(8)))
    assert results == [True] * 8, results
    assert verifier.verify(method="GET", path=PATH,
                           headers=headers(f"{3:032x}"), now=1000) is False
    verifier.close()
