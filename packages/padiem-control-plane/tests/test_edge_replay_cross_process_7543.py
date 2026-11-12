"""#7543 stage 1 — one replay-store write at a time across processes too.

Inside one process the ingress semaphore (#6563) and the verifier's own lock
already line signed requests up. Two worker processes sharing one replay store
each had their own line, so their writes met at SQLite's lock instead: the
loser waited the connection timeout out, the verifier turned the resulting
``sqlite3.Error`` into ``False`` and a correctly signed request answered 403.

The verifier now takes an OS file lock on a file beside the replay database for
the whole store write. These tests pin four things:

* two processes writing through one store never refuse a correctly signed
  request (the first test fails on the previous verifier);
* the same request id is accepted exactly once, whichever process sees it;
* a slot that cannot be taken refuses the request and consumes nothing, and a
  store whose slot file cannot exist fails at construction, not per request;
* a request that waited for the slot past its signature window is refused.

The contention is made deterministic instead of slow: each worker process holds
its write transaction open for a few milliseconds and gives SQLite almost no
time to wait, so an unserialized overlap fails at once rather than after the
production five seconds.
"""
import hashlib
import hmac
import contextlib
import multiprocessing
import os
import sqlite3
import stat
import time
from contextlib import closing

import pytest

import com2_edge_proof
from com2_edge_proof import LOCK_SUFFIX, EdgeProofVerifier

SECRET = "synthetic-test-" + "x" * 32
PATH = "/api/claw/connector/gateway/session"
#: How long each worker keeps its write transaction open, and how long SQLite
#: may wait for another writer. The hold is far longer than the wait, so two
#: writes that overlap inside SQLite cannot both succeed.
HOLD_SECONDS = 0.05
BUSY_SECONDS = 0.01
PER_PROCESS = 6


def headers(request_id="a" * 32, at=1000, tls="TLSv1.3", path=PATH):
    signed = "\n".join(("v1", "GET", path, str(at), request_id, tls)).encode()
    proof = "v1=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return {"x-padiem-edge-at": str(at), "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": tls, "x-padiem-edge-proof": proof}


def _worker(db, mode, id_prefix, count, hold, busy, barrier, results, finished):
    """One worker process: verify ``count`` signed requests through ``db``.

    The store already exists (the parent built it), so construction here does
    not write. Only after it are this process's SQLite connections slowed and
    made impatient, which is what turns an unserialized overlap into an
    immediate ``database is locked`` instead of a five second wait.
    """
    verifier = EdgeProofVerifier(SECRET, db, sync_mode=mode,
                                 checkpoint_every=10 ** 6, checkpoint_seconds=10 ** 6)
    real_connect = sqlite3.connect

    class HoldingConnection(sqlite3.Connection):
        def execute(self, sql, *args):
            if isinstance(sql, str) and sql.startswith("INSERT INTO edge_proof_seen"):
                time.sleep(hold)              # the write transaction is open here
            return super().execute(sql, *args)

    def impatient_connect(database, *args, **kwargs):
        if busy is not None:
            kwargs["timeout"] = busy
        kwargs["factory"] = HoldingConnection
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = impatient_connect       # this worker process only
    barrier.wait(30)
    verdicts = [
        verifier.verify(method="GET", path=PATH,
                        headers=headers(f"{id_prefix}{index:031x}"), now=1000)
        for index in range(count)
    ]
    results.put((id_prefix, verdicts))
    # Closing the last WAL connection checkpoints the store, which is not a
    # request and takes no slot. Every worker therefore keeps its connection
    # until all of them have answered, so that close cannot land in the middle
    # of another worker's (deliberately impatient) write.
    finished.wait(60)
    verifier.close()


def _run_processes(db, mode, prefixes, *, hold, busy):
    """Start one worker process per prefix together; return ``[(prefix, verdicts)]``."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(len(prefixes))
    results, finished = context.Queue(), context.Event()
    workers = [
        context.Process(target=_worker, args=(
            db, mode, prefix, PER_PROCESS, hold, busy, barrier, results, finished))
        for prefix in prefixes
    ]
    for worker in workers:
        worker.start()
    try:
        collected = [results.get(timeout=60) for _ in workers]
    finally:
        finished.set()
        for worker in workers:
            worker.join(30)
            if worker.is_alive():
                worker.kill()
    assert [worker.exitcode for worker in workers] == [0] * len(workers)
    return collected


def _rows(db):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute("SELECT count(*) FROM edge_proof_seen").fetchone()[0]


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_two_processes_on_one_store_never_refuse_a_signed_request(tmp_path, mode):
    db = str(tmp_path / "replay.sqlite3")
    EdgeProofVerifier(SECRET, db, sync_mode=mode).close()     # the store exists
    collected = dict(_run_processes(
        db, mode, ("1", "2"), hold=HOLD_SECONDS, busy=BUSY_SECONDS))
    # Every request was correctly signed and carried a fresh id. Before the
    # cross-process slot the two writers overlapped inside SQLite and the loser
    # came back False (a 403 for a healthy request).
    assert collected == {"1": [True] * PER_PROCESS, "2": [True] * PER_PROCESS}
    assert _rows(db) == 2 * PER_PROCESS


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_the_same_request_id_is_accepted_once_across_two_processes(tmp_path, mode):
    db = str(tmp_path / "replay.sqlite3")
    EdgeProofVerifier(SECRET, db, sync_mode=mode).close()
    # Both processes present the SAME ids at the same time, at the production
    # wait: the slot must not let a replay through, and must not lose the
    # original either.
    verdicts = [answers for _prefix, answers in _run_processes(
        db, mode, ("9", "9"), hold=0.005, busy=None)]
    accepted = [first + second for first, second in zip(*verdicts)]
    assert accepted == [1] * PER_PROCESS, verdicts
    assert _rows(db) == PER_PROCESS
    # And afterwards every one of those ids stays refused, in a third process.
    again = EdgeProofVerifier(SECRET, db, sync_mode=mode)
    assert [
        again.verify(method="GET", path=PATH,
                     headers=headers(f"9{index:031x}"), now=1001)
        for index in range(PER_PROCESS)
    ] == [False] * PER_PROCESS
    again.close()


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_the_slot_file_sits_beside_the_store_and_is_private(tmp_path, mode):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode=mode)
    slot = tmp_path / ("replay.sqlite3" + LOCK_SUFFIX)
    # Created at construction, in the store's own directory: the account that
    # can write the store can write its slot, with no second location to grant.
    assert slot.is_file()
    assert slot.parent == db.parent
    if os.name != "nt":
        assert stat.S_IMODE(slot.stat().st_mode) & 0o077 == 0
    assert verifier.verify(method="GET", path=PATH, headers=headers(), now=1000) is True
    # The slot is released after every answer, so the next request is not
    # parked behind the previous one: accepted, replayed, accepted again.
    assert verifier.verify(method="GET", path=PATH, headers=headers(), now=1000) is False
    assert verifier.verify(method="GET", path=PATH, headers=headers("b" * 32), now=1000) is True
    verifier.close()
    assert slot.is_file()                         # stable: never unlinked


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_a_slot_that_cannot_be_taken_refuses_and_consumes_nothing(tmp_path, monkeypatch, mode):
    db = str(tmp_path / "replay.sqlite3")
    verifier = EdgeProofVerifier(SECRET, db, sync_mode=mode)
    proof = headers("c" * 32)

    @contextlib.contextmanager
    def refused_slot():
        raise OSError("no locks available")
        yield

    with monkeypatch.context() as patch:
        patch.setattr(verifier, "_process_slot", lambda: refused_slot())
        # Fail closed, like any other store failure: no slot, no acceptance.
        assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is False
    assert _rows(db) == 0                          # the id was never recorded
    # Nothing was consumed, so the same signed request is served once the slot
    # works again, and only once.
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is True
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is False
    verifier.close()


def test_a_store_whose_slot_file_cannot_exist_fails_at_construction(tmp_path):
    db = tmp_path / "replay.sqlite3"
    (tmp_path / ("replay.sqlite3" + LOCK_SUFFIX)).mkdir()    # not a lockable file
    # A deployment that cannot place the slot must not start and then answer
    # every request 403: the constructor raises, exactly like an unusable store.
    with pytest.raises(OSError):
        EdgeProofVerifier(SECRET, str(db))


def test_a_request_that_waited_past_its_window_is_refused(tmp_path, monkeypatch):
    db = str(tmp_path / "replay.sqlite3")
    verifier = EdgeProofVerifier(SECRET, db)
    proof = headers("d" * 32, at=1000)
    # The request arrives inside its window and the clock moves past it while
    # the slot is being waited for: waiting for another process must not
    # stretch a signature's lifetime.
    clock = {"now": 1000.0}
    original_slot = verifier._process_slot

    @contextlib.contextmanager
    def slot_after_a_long_wait():
        with original_slot():
            clock["now"] = 1301.0
            yield

    with monkeypatch.context() as patch:
        patch.setattr(verifier, "_process_slot", slot_after_a_long_wait)
        patch.setattr(com2_edge_proof.time, "time", lambda: clock["now"])
        assert verifier.verify(method="GET", path=PATH, headers=proof) is False
    assert _rows(db) == 0                          # refused, and not consumed
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is True
