"""Background metadata shares staging atomicity, owner scope and queue backups."""
from __future__ import annotations

import asyncio
import pathlib
import sqlite3
import sys

import pytest

QUEUE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QUEUE.parents[1] / "apps" / "padiem-chat"))
sys.path.insert(0, str(QUEUE))

import schema
from app.d1_sqlite import SqliteD1, connect
from app.history import HistoryError
from background_history import QueueHistoryStore
from service import _forwarded_run_ownership
from test_queue_dispatch_create import _arguments, USER


def _store(connection):
    return QueueHistoryStore(SqliteD1(connection), run_ownership=_forwarded_run_ownership)


@pytest.fixture
def database(tmp_path):
    path = str(tmp_path / "queue.sqlite3")
    connection = connect(path)
    schema.apply(connection)
    yield connection, path
    connection.close()


@pytest.mark.parametrize("kind", ["read", "command"])
def test_trusted_background_mode_and_owner_survive_claim(database, kind):
    connection, _ = database
    store = _store(connection)
    args = _arguments()
    if kind == "command":
        args.update(kind="command", command_text="echo sample")

    async def run():
        created = await store.create_oracle_mesh_dispatch(**args, background=True)
        dispatch_id = created["dispatch_id"]
        assert created["owner_ref"] == USER and created["background"] is True
        pending = await store.oldest_pending_oracle_mesh_dispatch()
        assert pending["owner_ref"] == USER and pending["background"] is True
        assert pending["node_ref"] == args["node_ref"]
        assert pending["run_id"] == args["run_id"]
        assert await store.get_oracle_mesh_dispatch_for_owner(
            user_id="another-owner", dispatch_id=dispatch_id
        ) is None
        owned = await store.get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=dispatch_id
        )
        assert owned["claimed"] is False
        assert owned["device_id"] == args["device_id"]
        assert "nonce_sha256" not in owned
        assert await store.claim_oracle_mesh_dispatch(
            dispatch_id=dispatch_id, nonce_sha256="nonce-digest"
        )
        owned = await store.get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=dispatch_id
        )
        assert owned["claimed"] is True and owned["background"] is True
        assert "nonce_sha256" not in owned
        repeated = await store.create_oracle_mesh_dispatch(**args, background=True)
        assert repeated["dispatch_id"] == dispatch_id
        with pytest.raises(HistoryError, match="execution mode changed"):
            await store.create_oracle_mesh_dispatch(**args)
    asyncio.run(run())


def test_normal_and_legacy_dispatches_keep_their_original_shape(database):
    connection, _ = database
    store = _store(connection)

    async def run():
        args = _arguments()
        created = await store.create_oracle_mesh_dispatch(**args)
        assert "background" not in created and "owner_ref" not in created
        assert "background" not in await store.oldest_pending_oracle_mesh_dispatch()
        # An older queue row has no metadata. It remains a normal dispatch.
        connection.execute("DELETE FROM queue_background_dispatch")
        assert "background" not in await store.oldest_pending_oracle_mesh_dispatch()
        with pytest.raises(HistoryError, match="execution mode changed"):
            await store.create_oracle_mesh_dispatch(**args, background=True)
    asyncio.run(run())


def test_failed_metadata_write_rolls_back_the_dispatch_and_releases_transaction(database):
    connection, _ = database
    connection.execute(
        "CREATE TRIGGER refuse_background BEFORE INSERT ON queue_background_dispatch "
        "BEGIN SELECT RAISE(ABORT, 'test metadata failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError):
        asyncio.run(_store(connection).create_oracle_mesh_dispatch(
            **_arguments(), background=True
        ))
    assert connection.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 0
    assert not connection.in_transaction
    connection.execute("DROP TRIGGER refuse_background")
    created = asyncio.run(_store(connection).create_oracle_mesh_dispatch(
        **_arguments(), background=True
    ))
    assert created["background"] is True


def test_another_connection_cannot_claim_between_dispatch_and_metadata(database):
    connection, path = database
    observer = connect(path)
    seen = []

    def inspect_visibility():
        seen.append(observer.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0])
        return 0

    connection.create_function("inspect_background_visibility", 0, inspect_visibility)
    connection.execute(
        "CREATE TRIGGER inspect_background AFTER INSERT ON oracle_mesh_dispatch "
        "BEGIN SELECT inspect_background_visibility(); END"
    )
    try:
        asyncio.run(_store(connection).create_oracle_mesh_dispatch(
            **_arguments(), background=True
        ))
        assert seen == [0]
        assert observer.execute(
            "SELECT COUNT(*) FROM oracle_mesh_dispatch d "
            "JOIN queue_background_dispatch b ON b.dispatch_id=d.dispatch_id "
            "WHERE b.background=1"
        ).fetchone()[0] == 1
    finally:
        observer.close()


def test_reopen_and_existing_full_database_backup_preserve_metadata(database, tmp_path):
    connection, _ = database
    created = asyncio.run(_store(connection).create_oracle_mesh_dispatch(
        **_arguments(), background=True
    ))
    schema.apply(connection)
    # Match the existing backup.sh full-database snapshot operation.
    backup_path = str(tmp_path / "backup.sqlite3")
    connection.execute("VACUUM INTO ?", (backup_path,))
    restored = connect(backup_path)
    try:
        schema.apply(restored)
        owned = asyncio.run(_store(restored).get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=created["dispatch_id"]
        ))
        assert owned["background"] is True and owned["owner_ref"] == USER
    finally:
        restored.close()


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_background_requires_real_boolean(database, invalid):
    connection, _ = database
    with pytest.raises(HistoryError, match="boolean"):
        asyncio.run(_store(connection).create_oracle_mesh_dispatch(
            **_arguments(), background=invalid
        ))
    assert connection.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 0


def test_busy_pc_is_skipped_and_claim_guard_prevents_same_pc_overlap(database):
    connection, _ = database
    store = _store(connection)

    async def run():
        first = await store.create_oracle_mesh_dispatch(**_arguments(), background=True)
        same_pc = await store.create_oracle_mesh_dispatch(
            **_arguments(run_id="run_" + "2" * 32)
        )
        other_args = _arguments(run_id="run_" + "3" * 32)
        other_args.update(node_ref="node_OTHER", device_id="device-other")
        other_pc = await store.create_oracle_mesh_dispatch(**other_args)
        assert await store.claim_oracle_mesh_dispatch(
            dispatch_id=first["dispatch_id"], nonce_sha256="first-claim"
        )
        # A stale selection made before the first claim cannot start another
        # command on that PC; the exclusion is also in the atomic UPDATE.
        assert not await store.claim_oracle_mesh_dispatch(
            dispatch_id=same_pc["dispatch_id"], nonce_sha256="racing-claim"
        )
        pending = await store.oldest_pending_oracle_mesh_dispatch()
        assert pending["dispatch_id"] == other_pc["dispatch_id"]
        assert await store.claim_oracle_mesh_dispatch(
            dispatch_id=other_pc["dispatch_id"], nonce_sha256="other-claim"
        )
        connection.execute(
            "UPDATE oracle_mesh_dispatch SET state='done' WHERE dispatch_id=?",
            (first["dispatch_id"],),
        )
        assert (await store.oldest_pending_oracle_mesh_dispatch())["dispatch_id"] == same_pc["dispatch_id"]
        assert await store.claim_oracle_mesh_dispatch(
            dispatch_id=same_pc["dispatch_id"], nonce_sha256="after-completion"
        )
    asyncio.run(run())


def test_authenticated_queue_rpc_and_poll_project_stored_background_owner(database):
    import json
    from test_queue_dispatch_create import _door, _post, CHANNEL
    from test_queue_claim_lane import _Request
    from app.oracle_mesh_read_return_routes import oracle_mesh_read_poll

    connection, _ = database
    handler, state = _door(connection)
    assert isinstance(state.history_store, QueueHistoryStore)
    args = {**_arguments(), "kind": "command", "command_text": "echo sample", "background": True}
    response = _post(handler, state, "create_oracle_mesh_dispatch", args)
    assert response.status_code == 200
    response = asyncio.run(oracle_mesh_read_poll(_Request(state, None, secret=CHANNEL)))
    assert response.status_code == 200
    dispatch = json.loads(response.body)["dispatch"]
    assert dispatch["background"] is True
    assert dispatch["owner_ref"] == USER
    assert dispatch["node_ref"] == args["node_ref"]
    assert dispatch["run_id"] == args["run_id"]
    assert dispatch["kind"] == "command"


def test_private_output_authority_binds_device_without_changing_public_normal_row(database):
    connection, _ = database
    store = _store(connection)
    async def run():
        args = _arguments()
        created = await store.create_oracle_mesh_dispatch(**args)
        dispatch_id = created["dispatch_id"]
        public = await store.get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=dispatch_id
        )
        assert "device_id" not in public
        private = await store.get_pc_output_dispatch_for_owner(
            user_id=USER, dispatch_id=dispatch_id
        )
        assert private["device_id"] == args["device_id"]
        assert await store.get_pc_output_dispatch_for_owner(
            user_id="another-owner", dispatch_id=dispatch_id
        ) is None
    asyncio.run(run())


@pytest.mark.parametrize("operation", [
    {"op": "read", "path": "C:/notes.txt"},
    {"op": "list", "path": "C:/notes"},
    {"op": "delete", "path": "C:/notes.txt"},
    {"op": "move", "path": "C:/notes.txt", "destination": "C:/archive.txt"},
    {"op": "write", "path": "C:/notes.txt", "expected_bytes": 7, "expected_sha256": "a" * 64},
])
def test_job_operation_is_atomic_immutable_and_only_in_owned_row(database, operation):
    connection, _ = database
    store = _store(connection)

    async def run():
        args = _arguments()
        if operation["op"] != "read":
            args.update(kind="command", command_text="echo sample")
        first = await store.create_oracle_mesh_dispatch(
            **args, background=True, job_operation=operation
        )
        repeated = await store.create_oracle_mesh_dispatch(
            **args, background=True, job_operation=dict(reversed(list(operation.items())))
        )
        assert repeated["dispatch_id"] == first["dispatch_id"]
        owned = await store.get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=first["dispatch_id"]
        )
        assert owned["job_operation"] == operation
        assert "job_operation" not in await store.oldest_pending_oracle_mesh_dispatch()
        with pytest.raises(HistoryError, match="operation changed"):
            await store.create_oracle_mesh_dispatch(
                **args, background=True, job_operation={**operation, "path": "C:/changed.txt"}
            )
        assert (await store.get_oracle_mesh_dispatch_for_owner(
            user_id=USER, dispatch_id=first["dispatch_id"]
        ))["job_operation"] == operation
    asyncio.run(run())


@pytest.mark.parametrize("operation", [
    {"op": "exec", "path": "C:/notes.txt"},
    {"op": "write", "path": "C:/notes.txt", "content": "raw content"},
    {"op": "write", "path": "C:/notes.txt", "expected_bytes": True, "expected_sha256": "a" * 64},
    {"op": "write", "path": "C:/notes.txt", "expected_bytes": 0, "expected_sha256": "invalid"},
])
def test_invalid_job_operation_is_rejected_before_staging(database, operation):
    connection, _ = database
    with pytest.raises(HistoryError):
        asyncio.run(_store(connection).create_oracle_mesh_dispatch(
            **_arguments(), background=True, job_operation=operation
        ))
    assert connection.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 0


def test_metadata_upgrade_preserves_preoperation_background_rows(database):
    connection, _ = database
    created = asyncio.run(_store(connection).create_oracle_mesh_dispatch(
        **_arguments(), background=True
    ))
    connection.execute("DROP TABLE queue_background_dispatch")
    connection.execute(
        "CREATE TABLE queue_background_dispatch "
        "(dispatch_id TEXT PRIMARY KEY, background INTEGER NOT NULL)"
    )
    connection.execute(
        "INSERT INTO queue_background_dispatch VALUES (?,1)", (created["dispatch_id"],)
    )
    schema.apply(connection)
    schema.apply(connection)
    row = connection.execute("SELECT * FROM queue_background_dispatch").fetchone()
    assert row["dispatch_id"] == created["dispatch_id"] and row["background"] == 1
    assert row["job_operation_json"] is None
