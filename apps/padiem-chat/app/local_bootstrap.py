"""Serialize SQLite schema startup across CPython worker processes."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


@contextmanager
def migration_lock(connection):
    # An in-memory connection is never shared by independently spawned workers.
    database = next((row[2] for row in connection.execute("PRAGMA database_list")
                     if row[1] == "main"), "")
    if not database:
        yield
        return
    path = Path(database).resolve().with_suffix(Path(database).suffix + ".migrate.lock")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            while True:
                try:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        # File locks survive executescript's implicit commits; a SQLite
        # transaction around the old loop does not provide this exclusion.
        yield
    finally:
        # Closing also releases the lock after a migration exception. A dead
        # process releases its OS lock; the stable lock file is never unlinked.
        os.close(descriptor)
