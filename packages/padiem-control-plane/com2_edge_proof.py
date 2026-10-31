"""Verify edge-signed WebSocket provenance, with durable replay prevention.

No inbound header is trusted until its HMAC and request binding are verified.
This verifier is not wired into a live route; the edge signer is separate work.
"""
from contextlib import closing
import hashlib
import hmac
import re
import sqlite3
import time

ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
PROOF_RE = re.compile(r"^v1=[0-9a-f]{64}$")
TLS_VERSIONS = frozenset({"TLSv1.2", "TLSv1.3"})


class EdgeProofVerifier:
    def __init__(self, secret: str, replay_db: str, *, window: int = 300):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("edge proof secret required")
        if not 1 <= window <= 300 or not replay_db or replay_db == ":memory:":
            raise ValueError("durable replay database and bounded window required")
        self._key = secret.encode("utf-8")
        self._db = replay_db
        self._window = window
        with closing(sqlite3.connect(self._db)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS edge_proof_seen (request_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
            db.commit()

    def verify(self, *, method: str, path: str, headers, now: int | None = None) -> bool:
        try:
            at_text = headers.get("x-padiem-edge-at")
            request_id = headers.get("x-padiem-edge-id")
            tls = headers.get("x-padiem-edge-tls")
            proof = headers.get("x-padiem-edge-proof")
            if (method != "GET" or path != "/api/claw/connector/gateway/session"
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
            with closing(sqlite3.connect(self._db, timeout=5, isolation_level=None)) as db:
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
