"""#6604 — the replay store's durability is a setting, and the default is unchanged.

`full` is what COM2 has always served: rollback journal + synchronous FULL, one
fsync per signed request. `normal` keeps every ordering guarantee (one
BEGIN IMMEDIATE · INSERT · COMMIT per request, unique request id, one verify at
a time) and moves only the fsync out of the request path by holding the store in
WAL with synchronous=NORMAL.

Nothing here weakens replay detection: the same id presented twice is refused in
both modes, including after a restart, because the row is committed (durably in
`full`, in the WAL in `normal`) either way.
"""
import hashlib
import hmac
import sqlite3
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


@pytest.mark.parametrize("mode", ["full", "normal"])
def test_a_refused_replay_leaves_exactly_one_row(tmp_path, mode):
    db = tmp_path / "replay.sqlite3"
    verifier = EdgeProofVerifier(SECRET, str(db), sync_mode=mode)
    proof = headers("d" * 32)
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is True
    assert verifier.verify(method="GET", path=PATH, headers=proof, now=1000) is False
    with closing(sqlite3.connect(str(db))) as conn:
        rows = conn.execute("SELECT request_id, expires_at FROM edge_proof_seen").fetchall()
    assert rows == [("d" * 32, 1300)]            # one bounded row, no duplicate


def test_going_back_to_full_returns_the_rollback_journal(tmp_path, monkeypatch):
    db = tmp_path / "replay.sqlite3"
    monkeypatch.setenv(SYNC_MODE_ENV, "normal")
    normal = EdgeProofVerifier(SECRET, str(db))
    assert normal.sync_mode == "normal"
    assert pragmas(normal)[0] == "wal"
    monkeypatch.setenv(SYNC_MODE_ENV, "full")
    restored = EdgeProofVerifier(SECRET, str(db))
    assert restored.sync_mode == "full"
    assert pragmas(restored) == ("delete", 2)
    # The ids consumed while the store was in WAL are still refused.
    assert restored.verify(method="GET", path=PATH, headers=headers(), now=1000) is True
