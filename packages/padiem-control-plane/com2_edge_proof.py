"""Verify edge-signed WebSocket provenance, with durable replay prevention.

No inbound header is trusted until its HMAC and request binding are verified.
This verifier is not wired into a live route; the edge signer is separate work.
"""
from contextlib import closing
import hashlib
import hmac
import os
import re
import sqlite3
import time

ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
PROOF_RE = re.compile(r"^v1=[0-9a-f]{64}$")
TLS_VERSIONS = frozenset({"TLSv1.2", "TLSv1.3"})

#: #6604 — how the replay store is made durable.
#:
#: ``full`` (default) is exactly what every COM2 host has run since 2026-10-31:
#: the rollback journal with a synchronous FULL commit, so one request costs one
#: fsync of its INSERT. ``normal`` keeps the same per-request
#: BEGIN IMMEDIATE / INSERT / COMMIT, the same unique request id and the same
#: one-verify-at-a-time order, but keeps the store in WAL and commits with
#: synchronous=NORMAL, so the fsync leaves the request path.
#:
#: What ``normal`` trades is durability of the newest writes, not replay
#: detection. A process crash loses nothing (the OS already has the pages); an
#: abrupt power loss can drop the last few commits, so a signed request whose id
#: was consumed seconds before that loss could be accepted once after the
#: restart. That exposure is bounded by the signature lifetime — the verifier's
#: window, at most 300 s and 300 s in production — not by the store.
SYNC_MODE_ENV = "PADIEM_EDGE_REPLAY_SYNC_MODE"
SYNC_MODES = {"full": ("DELETE", "FULL"), "normal": ("WAL", "NORMAL")}


def replay_sync_mode(env=None) -> str:
    """The store mode this process serves; anything unrecognised means ``full``."""
    raw = (os.environ if env is None else env).get(SYNC_MODE_ENV)
    value = raw.strip().lower() if isinstance(raw, str) else ""
    return value if value in SYNC_MODES else "full"


class EdgeProofVerifier:
    def __init__(self, secret: str, replay_db: str, *, window: int = 300,
                 all_requests: bool = False, sync_mode: str | None = None):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("edge proof secret required")
        if not 1 <= window <= 300 or not replay_db or replay_db == ":memory:":
            raise ValueError("durable replay database and bounded window required")
        self._all_requests = all_requests
        self._key = secret.encode("utf-8")
        self._db = replay_db
        self._window = window
        # A host-wide setting, not a per-call one: the store's journal mode is
        # written into the file, so two callers asking for different modes in one
        # process would fight over it. Tests and the benchmark may name it.
        self.sync_mode = (replay_sync_mode() if sync_mode is None else
                          sync_mode if sync_mode in SYNC_MODES else "full")
        # ``journal_mode`` is written into the file, so it is chosen once here:
        # a store left in WAL by an earlier ``normal`` run comes back to the
        # rollback journal when the host serves ``full`` again, and no request
        # pays for a mode switch.
        with closing(self._connect()) as db:
            db.execute(f"PRAGMA journal_mode={SYNC_MODES[self.sync_mode][0]}")
            db.execute("CREATE TABLE IF NOT EXISTS edge_proof_seen (request_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        """One replay-store connection that commits at this mode's durability.

        ``synchronous`` is a property of the connection, not of the file, so it
        is set on every connection this verifier opens.
        """
        db = sqlite3.connect(self._db, timeout=5, isolation_level=None)
        db.execute(f"PRAGMA synchronous={SYNC_MODES[self.sync_mode][1]}")
        return db

    def verify(self, *, method: str, path: str, headers, now: int | None = None) -> bool:
        try:
            at_text = headers.get("x-padiem-edge-at")
            request_id = headers.get("x-padiem-edge-id")
            tls = headers.get("x-padiem-edge-tls")
            proof = headers.get("x-padiem-edge-proof")
            if (not isinstance(method, str) or not method or "\n" in method
                or not isinstance(path, str) or not path.startswith("/") or "\n" in path
                or not isinstance(at_text, str) or not at_text.isascii() or not at_text.isdigit()
                or not isinstance(request_id, str) or not ID_RE.fullmatch(request_id)
                or tls not in TLS_VERSIONS or not isinstance(proof, str) or not PROOF_RE.fullmatch(proof)):
                return False
            at = int(at_text)
            if str(at) != at_text or abs((int(time.time()) if now is None else now) - at) > self._window:
                return False
            signed = "\n".join(("v1", method, path, at_text, request_id, tls)).encode("utf-8")
            expected = "v1=" + hmac.new(self._key, signed, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(proof, expected):
                return False
            current = int(time.time()) if now is None else now
            with closing(self._connect()) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM edge_proof_seen WHERE expires_at < ?", (current,))
                try:
                    db.execute("INSERT INTO edge_proof_seen VALUES (?, ?)", (request_id, at + self._window))
                except sqlite3.IntegrityError:
                    db.execute("ROLLBACK")
                    return False
                db.execute("COMMIT")
            return True
        except (ValueError, TypeError, OverflowError, sqlite3.Error):
            return False
