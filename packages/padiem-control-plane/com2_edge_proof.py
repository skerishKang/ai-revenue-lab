"""Verify edge-signed WebSocket provenance, with durable replay prevention.

No inbound header is trusted until its HMAC and request binding are verified.
This verifier is not wired into a live route; the edge signer is separate work.
"""
from contextlib import closing, contextmanager
import atexit
import errno
import hashlib
import hmac
import os
import re
import sqlite3
import threading
import time

from padiem_ai_core.output_store import exclusive_file_lock

ID_RE = re.compile(r"^[0-9a-f]{32,64}$")
PROOF_RE = re.compile(r"^v1=[0-9a-f]{64}$")
TLS_VERSIONS = frozenset({"TLSv1.2", "TLSv1.3"})

#: #6604 / #6611 — how the replay store is made durable.
#:
#: ``full`` (default) is exactly what every COM2 host has run since 2026-10-31:
#: one connection per request, the rollback journal and a synchronous FULL
#: commit, so one request costs one fsync of its INSERT. ``normal`` keeps the
#: same per-request BEGIN IMMEDIATE / INSERT / COMMIT, the same unique request id
#: and the same one-verify-at-a-time order, but serves the store from one
#: connection per process held in WAL with synchronous=NORMAL, so the fsync
#: leaves the request path. WAL pays its shm mapping per connection and
#: checkpoints (fsyncs) when the last connection closes, which is why the
#: connection is held and checkpoints are taken off the request path.
#:
#: What ``normal`` trades is durability of the newest writes, not replay
#: detection. A process crash loses nothing (the OS already has the pages); an
#: abrupt power loss can drop the last few commits, so a signed request whose id
#: was consumed seconds before that loss could be accepted once after the
#: restart. That exposure is bounded by the signature lifetime — the verifier's
#: window, at most 300 s and 300 s in production — not by the store.
SYNC_MODE_ENV = "PADIEM_EDGE_REPLAY_SYNC_MODE"
SYNC_MODES = {"full": ("DELETE", "FULL"), "normal": ("WAL", "NORMAL")}
#: How often a held WAL is folded back into the database, in committed requests
#: or in seconds. PASSIVE on its own connection: it never waits for a reader and
#: never holds the verifier's connection, so no signed request queues behind it.
CHECKPOINT_EVERY_REQUESTS = 200
CHECKPOINT_EVERY_SECONDS = 30.0

#: #7543 stage 1 — one store write at a time across processes, not only inside one.
#:
#: The ingress semaphore (#6563) and ``_verify_lock`` line signed requests up
#: inside a single process. Two worker processes on one replay store each had
#: their own line, so their writes met at SQLite's lock instead: the loser
#: waited the connection timeout out, ``verify`` turned the ``sqlite3.Error``
#: into ``False`` and a correctly signed request answered 403 (the 2026-11-02
#: two-worker run). Every store write is therefore made under an OS file lock on
#: this file beside the replay database:
#:
#: * the wait has no deadline, the same contract as the ingress semaphore — a
#:   slow store delays a signed request, it does not fail it. The lock is held
#:   only around the store write (each SQLite call inside keeps its own five
#:   second limit), and the OS releases it the moment its holder exits or dies;
#: * a lock that cannot be taken at all is a refusal: ``verify`` answers
#:   ``False`` and records nothing, exactly like any other store failure. No
#:   request is ever admitted without its id having been recorded;
#: * the freshness window is checked again once the lock is held, so waiting
#:   for another process never stretches a signature's lifetime;
#: * the file is created at construction in the store's own directory, so a
#:   host that cannot place it fails to start instead of answering 403s. It
#:   holds no data and is never unlinked.
#:
#: Replay detection itself never depended on this line and still does not: the
#: request id is the store's primary key in every mode.
LOCK_SUFFIX = ".verify.lock"




def replay_sync_mode(env=None) -> str:
    """The store mode this process serves; anything unrecognised means ``full``."""
    raw = (os.environ if env is None else env).get(SYNC_MODE_ENV)
    value = raw.strip().lower() if isinstance(raw, str) else ""
    return value if value in SYNC_MODES else "full"


class EdgeProofVerifier:
    def __init__(self, secret: str, replay_db: str, *, window: int = 300,
                 all_requests: bool = False, sync_mode: str | None = None,
                 checkpoint_every: int = CHECKPOINT_EVERY_REQUESTS,
                 checkpoint_seconds: float = CHECKPOINT_EVERY_SECONDS):
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
        self._checkpoint_every = max(1, int(checkpoint_every))
        self._checkpoint_seconds = max(1.0, float(checkpoint_seconds))
        self._conn: sqlite3.Connection | None = None
        self._conn_lock = threading.Lock()
        self._verify_lock = threading.Lock()
        self._writes = 0
        self._last_checkpoint = time.monotonic()
        self._checkpointing = False
        # Beside the store itself, symlinks resolved the way SQLite resolves them
        # for its own journal and WAL files: the account that can write the store
        # can write this file, and no second location has to be granted.
        self._lock_path = os.path.realpath(os.fspath(replay_db)) + LOCK_SUFFIX
        # ``journal_mode`` is written into the file, so it is chosen once here:
        # a store left in WAL by an earlier ``normal`` run comes back to the
        # rollback journal when the host serves ``full`` again, and no request
        # pays for a mode switch. Taken under the cross-process slot, so two
        # processes starting together do not meet over the mode, and so a host
        # that cannot create or lock the slot file fails here, at start.
        with self._process_slot():
            with closing(self._connect()) as db:
                db.execute(f"PRAGMA journal_mode={SYNC_MODES[self.sync_mode][0]}")
                db.execute("CREATE TABLE IF NOT EXISTS edge_proof_seen (request_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)")
                db.commit()
        if self.sync_mode == "normal":
            atexit.register(self.close)

    @contextmanager
    def _process_slot(self):
        """Hold the one cross-process slot for a store write (#7543).

        The byte-range lock itself is the shared output-store helper
        (:func:`padiem_ai_core.output_store.exclusive_file_lock`), so this edge
        package carries no Windows-only import and both hosts take the same
        lock the queue-and-executor output store takes. The wait keeps the
        contract from #7543 - no deadline, the same as the ingress semaphore -
        through the retry below, and failing to open or lock raises
        ``OSError`` before the body runs. Releasing never raises: once the body
        has answered, a close error must not turn that answer around.
        """
        # The slot file is placed first, outside the wait: a host that cannot
        # create it fails right here, exactly like the per-call descriptor did,
        # instead of a placement error being retried as lock contention.
        os.close(os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600))
        lock = None
        while lock is None:
            attempt = exclusive_file_lock(self._lock_path)
            try:
                attempt.__enter__()
                lock = attempt
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                time.sleep(0.005)
        try:
            yield
        finally:
            try:
                lock.__exit__(None, None, None)
            except OSError:
                pass

    def _connect(self) -> sqlite3.Connection:
        """One short-lived connection that commits at this mode's durability.

        ``synchronous`` is a property of the connection, not of the file, so it
        is set on every connection this verifier opens. The default mode keeps
        using one connection per request exactly as before; ``normal`` uses it
        for setup, for tests, and for a checkpoint.
        """
        db = sqlite3.connect(self._db, timeout=5, isolation_level=None)
        db.execute(f"PRAGMA synchronous={SYNC_MODES[self.sync_mode][1]}")
        return db

    def _held(self) -> sqlite3.Connection:
        """The one connection a ``normal`` store is served from.

        Created lazily, so a host that serves no signed request never opens the
        store, and used only inside :attr:`_verify_lock`. ``check_same_thread``
        is answered by that lock: the middleware hands verification to a worker
        thread, and the same thread is not guaranteed for the next request.
        """
        with self._conn_lock:
            if self._conn is None:
                db = sqlite3.connect(self._db, timeout=5, isolation_level=None,
                                     check_same_thread=False)
                db.execute("PRAGMA synchronous=NORMAL")
                # The request path never checkpoints; _maybe_checkpoint does.
                db.execute("PRAGMA wal_autocheckpoint=0")
                self._conn = db
                self._writes = 0
                self._last_checkpoint = time.monotonic()
            return self._conn

    def _discard(self) -> None:
        """Drop the held connection after a failure so the next call reopens."""
        with self._conn_lock:
            db, self._conn = self._conn, None
        if db is not None:
            try:
                db.close()
            except sqlite3.Error:
                pass

    def close(self) -> None:
        """Release the held connection (process exit, or a host restart hook)."""
        self._discard()

    def _record(self, db: sqlite3.Connection, request_id: str, at: int, current: int) -> bool:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM edge_proof_seen WHERE expires_at < ?", (current,))
        try:
            db.execute("INSERT INTO edge_proof_seen VALUES (?, ?)", (request_id, at + self._window))
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")
            return False
        db.execute("COMMIT")
        return True

    def _record_held(self, request_id: str, at: int, current: int) -> bool:
        try:
            with self._verify_lock:
                accepted = self._record(self._held(), request_id, at, current)
                self._writes += 1
            if accepted:
                self._maybe_checkpoint()
            return accepted
        except (sqlite3.OperationalError, sqlite3.ProgrammingError):
            # A held handle can go stale or be closed underneath the verifier
            # (the volume remounted, the database replaced). One reconnect,
            # inside the same serialized call; a second failure is the
            # verifier's ordinary fail-closed answer.
            self._discard()
            with self._verify_lock:
                accepted = self._record(self._held(), request_id, at, current)
                self._writes += 1
            if accepted:
                self._maybe_checkpoint()
            return accepted

    def _maybe_checkpoint(self) -> None:
        with self._conn_lock:
            if self._checkpointing:
                return
            due = (self._writes >= self._checkpoint_every
                   or time.monotonic() - self._last_checkpoint >= self._checkpoint_seconds)
            if not due:
                return
            self._checkpointing = True
            self._writes = 0
            self._last_checkpoint = time.monotonic()
        threading.Thread(target=self._checkpoint, name="edge-replay-checkpoint",
                         daemon=True).start()

    def _checkpoint(self) -> None:
        """Fold the WAL back in on a connection of its own, off the request path."""
        try:
            with closing(sqlite3.connect(self._db, timeout=5, isolation_level=None)) as db:
                db.execute("PRAGMA synchronous=NORMAL")
                db.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass
        finally:
            with self._conn_lock:
                self._checkpointing = False

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
            # One store write at a time across every process on this store. A
            # slot that cannot be taken raises OSError and is refused below with
            # nothing recorded; the wait itself has no deadline (see LOCK_SUFFIX).
            with self._process_slot():
                # Asked again now that the slot is held: a request that waited
                # for another process past its window is as stale as one that
                # arrived late, and is refused the same way.
                current = int(time.time()) if now is None else now
                if abs(current - at) > self._window:
                    return False
                if self.sync_mode == "normal":
                    return self._record_held(request_id, at, current)
                with closing(self._connect()) as db:
                    return self._record(db, request_id, at, current)
        except (ValueError, TypeError, OverflowError, sqlite3.Error, OSError):
            return False
