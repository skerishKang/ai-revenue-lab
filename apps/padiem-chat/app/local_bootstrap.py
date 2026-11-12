"""OS file locks that order CPython worker processes sharing one SQLite file.

Two things on this host must happen in one process at a time, and both use the
same lock primitive on a stable file next to the database:

* schema startup waits for the lock, so each migration is applied once;
* the idle WAL checkpoint asks for the lock without waiting, so exactly one
  worker process runs it and the others ask again later.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import threading
import time

__all__ = ["ProcessFileLock", "checkpoint_owner_lock", "migration_lock"]


def _lock_descriptor(descriptor: int, *, wait: bool) -> bool:
    """Take the exclusive OS lock on an open file; False only when not waiting."""
    if os.name == "nt":
        import msvcrt
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        while True:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return True
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if not wait:
                    return False
                time.sleep(0.05)
    import fcntl
    if wait:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        return True
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


class ProcessFileLock:
    """One exclusive OS file lock, held by this process until it lets go.

    ``path`` is ``None`` for an in-memory database: nothing is shared with
    another process, so the lock is always granted. A dead process releases its
    OS lock; the stable lock file itself is never unlinked.
    """

    def __init__(self, path: Path | None):
        self._path = path
        self._descriptor: int | None = None
        self._held = False
        # acquire() may run on a helper thread while release() runs elsewhere.
        self._state = threading.Lock()

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self, *, wait: bool) -> bool:
        """Take the lock, or report False when ``wait`` is off and another process has it."""
        with self._state:
            if self._held:
                return True
            if self._path is not None:
                descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    locked = _lock_descriptor(descriptor, wait=wait)
                except BaseException:
                    os.close(descriptor)
                    raise
                if not locked:
                    os.close(descriptor)
                    return False
                self._descriptor = descriptor
            self._held = True
            return True

    def release(self) -> None:
        with self._state:
            # Closing the descriptor is what releases the OS lock.
            descriptor, self._descriptor = self._descriptor, None
            self._held = False
            if descriptor is not None:
                os.close(descriptor)


def _lock_beside_database(connection, suffix: str) -> ProcessFileLock:
    # An in-memory connection is never shared by independently spawned workers.
    database = next((row[2] for row in connection.execute("PRAGMA database_list")
                     if row[1] == "main"), "")
    if not database:
        return ProcessFileLock(None)
    return ProcessFileLock(
        Path(database).resolve().with_suffix(Path(database).suffix + suffix))


@contextmanager
def migration_lock(connection):
    lock = _lock_beside_database(connection, ".migrate.lock")
    lock.acquire(wait=True)
    try:
        # File locks survive executescript's implicit commits; a SQLite
        # transaction around the old loop does not provide this exclusion.
        yield
    finally:
        # Also releases the lock after a migration exception.
        lock.release()


def checkpoint_owner_lock(connection) -> ProcessFileLock:
    """The lock whose holder is the one process that checkpoints this database.

    It sits in the data folder next to the database file, so every worker
    process that opens the same file contends for the same lock.
    """
    return _lock_beside_database(connection, ".checkpoint.lock")
