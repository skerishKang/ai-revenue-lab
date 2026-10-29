"""#5881 follow-on — the state copy moves real rows and can name what changed after it.

The rows are made by the real stores, not by hand-written INSERTs: what gets copied must
be what a running system wrote. What is proved: every table moves whole, a run that cannot
verify refuses loudly instead of leaving half a database, and the snapshot answers "what
did the queue change during the switch" without a write-path journal.
"""
from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sqlite3
import sys

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.d1_sqlite import SqliteD1  # noqa: E402
from app.mesh_device_presence_store import D1MeshDevicePresenceStore  # noqa: E402
from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from copy_state import TABLES, copy_state, diff_state  # noqa: E402
from schema import apply  # noqa: E402

USER = "usr_" + "b" * 32
NOW = __import__("datetime").datetime(2026, 10, 29, 3, 0, 0, tzinfo=__import__(
    "datetime").timezone.utc)


def _file(tmp_path, name):
    path = str(tmp_path / name)
    connection = sqlite3.connect(path)
    apply(connection)
    connection.close()
    return path


def _fill(path):
    """One code, one claimed link and one presence receipt, written by the stores."""

    connection = sqlite3.connect(path, isolation_level=None)
    connection.row_factory = sqlite3.Row
    database = SqliteD1(connection)
    pairing = D1PcPairingStore(database)
    issued = asyncio.run(pairing.issue_code(user_id=USER, issued_at=NOW))
    asyncio.run(pairing.complete_claim_from_observation(
        agent_name="%s [C D] CGI-9" % issued["install_tag"],
        mesh_node_id="node//COPYPC", now=NOW))
    asyncio.run(D1MeshDevicePresenceStore(database).upsert(
        device_id="device-copy", connected=True, received_at=NOW,
        credential_generation=None, source="mesh"))
    connection.close()


def _counts(path):
    connection = sqlite3.connect(path)
    try:
        return {table: connection.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
                for table in TABLES}
    finally:
        connection.close()


def test_copy_moves_every_named_table_whole(tmp_path):
    source = _file(tmp_path, "export.sqlite")
    _fill(source)
    target = _file(tmp_path, "queue.sqlite")
    report = copy_state(source, target)

    filled = _counts(source)
    assert filled == _counts(target)
    assert sum(filled.values()) > 0, "the fixture must actually have rows"
    assert all(report[table]["rows"] == filled[table] for table in TABLES)
    assert all(report[table]["written"] == filled[table] for table in TABLES)


def test_a_fresh_copy_reports_no_change_and_later_writes_are_named(tmp_path):
    source = _file(tmp_path, "export.sqlite")
    _fill(source)
    target = _file(tmp_path, "queue.sqlite")
    copy_state(source, target)
    clean = diff_state(target)
    assert all(not clean[table][kind] for table in TABLES
               for kind in ("added", "removed", "changed"))

    connection = sqlite3.connect(target, isolation_level=None)
    connection.row_factory = sqlite3.Row
    asyncio.run(D1PcPairingStore(SqliteD1(connection)).pause_link(
        user_id=USER, link_id=_only_link_id(connection), now=NOW))
    connection.close()

    after = diff_state(target)
    assert after["pc_device_links"]["changed"], "a paused link must show up as changed"
    assert after["pc_pairing_codes"]["added"] == []


def _only_link_id(connection):
    row = connection.execute("SELECT link_id FROM pc_device_links LIMIT 1").fetchone()
    return row[0]


def test_an_export_without_the_tables_stops_instead_of_empting_the_queue(tmp_path):
    empty = str(tmp_path / "not-an-export.sqlite")
    sqlite3.connect(empty).close()
    target = _file(tmp_path, "queue.sqlite")
    _fill(target)
    try:
        copy_state(empty, target)
    except RuntimeError as exc:
        assert "missing tables" in str(exc)
    else:
        raise AssertionError("a source without the tables must be refused")
    # The refusal left the queue exactly as it was.
    assert sum(_counts(target).values()) > 0


def test_a_repeated_copy_is_the_same_shape_as_the_first(tmp_path):
    source = _file(tmp_path, "export.sqlite")
    _fill(source)
    target = _file(tmp_path, "queue.sqlite")
    first = copy_state(source, target)
    second = copy_state(source, target)
    assert {table: first[table]["rows"] for table in TABLES} == \
           {table: second[table]["rows"] for table in TABLES}
    changes = diff_state(target)
    left = [value for item in changes.values() for value in item.values()]
    assert not any(left), "a second copy of the same export is not a change"

def test_the_command_line_the_runbook_types_actually_runs(tmp_path):
    """`copy_state.py copy --source … --target …` reached argparse, never the copy.

    Measured on the host 2026-10-30 while running section 4 of the cutover runbook: the
    entry point handed `sys.argv` - the script path first - to `parse_args`, so the
    documented invocation died with "invalid choice: '<path>/copy_state.py'" before it
    opened a database. The suite could not have caught it: every test calls `main` with a
    list it built itself. This test runs the file the way a person does.
    """
    missing = str(tmp_path / "no-such-export.sqlite")
    target = str(tmp_path / "queue.sqlite")
    completed = subprocess.run(
        [sys.executable, str(QUEUE / "copy_state.py"), "copy",
         "--source", missing, "--target", target],
        capture_output=True, text=True, timeout=120,
    )
    shouted = completed.stdout + completed.stderr
    assert "invalid choice" not in shouted, "argparse ate the script path again"
    assert completed.stdout.startswith("PC_STATE_REFUSED"), completed.stdout[:120]
    assert completed.returncode == 1, "a refused source is a refusal, not a crash"


def test_the_diff_shape_parses_from_the_command_line_too(tmp_path):
    target = _file(tmp_path, "queue.sqlite")
    completed = subprocess.run(
        [sys.executable, str(QUEUE / "copy_state.py"), "diff", "--target", target],
        capture_output=True, text=True, timeout=120,
    )
    assert "invalid choice" not in completed.stdout + completed.stderr
    assert completed.returncode in (0, 1), completed.returncode
