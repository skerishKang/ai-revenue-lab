"""This deployment's one decision about how SQLite connections behave.

The COM2 database files sit on an ext4 volume whose fsync measured 200-600 ms
on 2026-11-03 (WSL ext4.vhdx on a SATA HDD). With ``synchronous=FULL`` every
commit paid at least one such fsync, which is what made a 1-second status read
and 3-second orchestration write appear as slow SQL rather than slow storage
(``sqlite_wait`` stayed under 1 ms the whole time).

So the file-sync stance is fixed once, here, instead of at each call site:

* WAL stays on — readers never block the writer.
* ``synchronous=NORMAL`` makes a commit write the WAL without an fsync per
  commit. A power loss can lose the most recent commits; the database itself
  stays consistent (no torn pages, no corruption). That trade was decided by
  the CTO on 2026-11-03.
* ``wal_autocheckpoint`` is lowered so a checkpoint copies about a megabyte at
  a time instead of the whole 4 MiB WAL.
* ``busy_timeout`` stays, so a writer waits instead of failing.

Nothing here changes what a statement does.
"""

from __future__ import annotations

__all__ = [
    "BUSY_TIMEOUT_MS",
    "CACHE_KIB",
    "AUTOCHECKPOINT_PAGES",
    "READER_IDLE_SECONDS",
    "IDLE_QUIET_SECONDS",
    "IDLE_CHECKPOINT_SECONDS",
    "configure_writer",
    "configure_reader",
]

#: How long a writer waits for another writer before reporting "busy".
BUSY_TIMEOUT_MS = 5000

#: Page cache per connection, in KiB (negative means KiB, not pages).
CACHE_KIB = -20_000

#: Checkpoint after this many WAL frames (~1 MiB at a 4 KiB page size).
AUTOCHECKPOINT_PAGES = 256

#: A pooled read connection closes itself after this long unused.
READER_IDLE_SECONDS = 60

#: Only checkpoint when no statement has run for this long...
IDLE_QUIET_SECONDS = 60

#: ...and at most this often.
IDLE_CHECKPOINT_SECONDS = 300


def configure_writer(connection) -> None:
    """Apply the write-side policy to a connection this process owns."""

    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
    connection.execute("PRAGMA cache_size = %d" % CACHE_KIB)
    connection.execute("PRAGMA wal_autocheckpoint = %d" % AUTOCHECKPOINT_PAGES)


def configure_reader(connection) -> None:
    """Apply the read-side policy.

    A reader keeps the same wait and cache stance as the writer but can never
    write, and it holds no transaction between statements, so it never pins a
    WAL snapshot the way an open read transaction would.
    """

    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA busy_timeout = %d" % BUSY_TIMEOUT_MS)
    connection.execute("PRAGMA cache_size = %d" % CACHE_KIB)
