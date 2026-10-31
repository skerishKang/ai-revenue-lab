"""Stage 2-C differential harness: the DO-side broker stack vs the COM2 service.

Both sides run the SAME broker code (`BrokerComposition`). The DO side stands on
an independent in-memory implementation of the Durable Object SQLite-storage
API (`_DoStorage` below); the COM2 side is the real skeleton service — file WAL
database, proof-gated HTTP door, uvicorn socket. That isolates exactly what the
move changes: storage semantics and transport, never broker rules.

Eight vectors (design §7): envelope parity, CAS loser, expiry boundary, purge,
replay/sequence, scope, real-socket concurrency, rollback rehearsal.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import re
import socket
import sqlite3
import threading
import time
import types
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn

import harness_support as harness
import service as broker_service

_TESTS = Path(__file__).resolve().parent
_DEPLOY = _TESTS.parent / "deploy"
_ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:\+00:00|Z)?$")


# --- the DO-side storage double (independent of apps/padiem-broker/storage.py)

class _DoCursor:
    def __init__(self, rows, written):
        self._rows = rows
        self.rowsWritten = written

    def toArray(self):
        return list(self._rows)


class _DoSql:
    def __init__(self, connection):
        self._connection = connection

    def exec(self, query, *bindings):
        cursor = self._connection.execute(query, bindings)
        if cursor.description is not None:
            return _DoCursor([dict(row) for row in cursor.fetchall()], 0)
        written = cursor.rowcount
        return _DoCursor([], written if isinstance(written, int) and written > 0 else 0)


class _DoStorage:
    """A minimal Durable Object SQLite-storage double used by broker tests."""

    def __init__(self):
        self._connection = sqlite3.connect(":memory:", isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self.sql = _DoSql(self._connection)

    def transactionSync(self, callback):
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            result = callback()
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        self._connection.execute("COMMIT")
        return result

    def close(self):
        self._connection.close()


def _env():
    return types.SimpleNamespace(
        LOCAL_AGENT_BROKER_AUTHORITY_REF=harness.AUTHORITY,
        LOCAL_AGENT_BROKER_PEPPER=harness.PEPPER,
    )


def _do_side():
    do_storage = _DoStorage()
    side = broker_service.BrokerComposition(storage=do_storage, env=_env())
    return side, do_storage


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str) and _ISO.match(value):
        return "<timestamp>"
    return value


def _seed(side) -> None:
    seeded = side._runtime.register_binding(harness.register_payload())
    assert seeded["ok"] is True, seeded


@pytest.fixture()
def sides(tmp_path):
    do_side, do_storage = _do_side()
    app = broker_service.build_app(environ=harness.environ(tmp_path))
    yield types.SimpleNamespace(do=do_side, storage=do_storage, app=app, path=tmp_path)
    do_storage.close()
    app.state.broker_storage.close()


def _run(coro):
    return asyncio.run(coro)


async def _both(sides, method, payload, *, do_call=None, envelope=None):
    """Run one vector call on both sides and return both envelopes."""

    if do_call is None:
        do_call = getattr(sides.do, method)
    do_result = do_call(payload)
    if hasattr(do_result, "__await__"):
        do_result = await do_result
    async with harness.client_for(sides.app) as client:
        response = await harness.rpc(client, method, envelope if envelope is not None else payload)
    assert response.status_code == 200, response.text
    return do_result, response.json()


# --- 1. envelope parity ------------------------------------------------------

@pytest.mark.asyncio
async def test_vector_1_envelope_parity_across_the_broker_lanes(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)

    open_payload = harness.open_session_payload(now=harness.now_iso())
    do_open, svc_open = await _both(sides, "open_session", open_payload)
    assert _normalize(do_open) == _normalize(svc_open)
    assert svc_open["ok"] is True

    auth = harness.auth_payload()
    do_auth, svc_auth = await _both(sides, "authenticate_device_session", auth)
    assert _normalize(do_auth) == _normalize(svc_auth)
    assert svc_auth["ok"] is True

    directory = {"account_ref": harness.ACCOUNT, "workspace_ref": harness.WORKSPACE}
    do_dir, svc_dir = await _both(sides, "device_directory", directory)
    assert _normalize(do_dir) == _normalize(svc_dir)

    do_truth, svc_truth = await _both(sides, "device_truth", directory)
    assert _normalize(do_truth) == _normalize(svc_truth)


# --- 2. CAS loser ------------------------------------------------------------

@pytest.mark.asyncio
async def test_vector_2_cas_loser_reports_the_same_refusal_on_both_sides(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)
    rotate = {
        "binding_ref": harness.BINDING, "expected_generation": 1,
        "new_credential_b64": base64.b64encode(b"rotated-credential").decode(),
        "now": harness.now_iso(),
    }
    winner_do, winner_svc = await _both(sides, "rotate_credential", rotate)
    assert winner_do["ok"] is True and winner_svc["ok"] is True

    loser_do, loser_svc = await _both(sides, "rotate_credential", rotate)
    assert loser_do["ok"] is False and loser_svc["ok"] is False
    assert loser_do["error"]["code"] == loser_svc["error"]["code"]
    assert loser_svc["error"]["code"] == "stale_device_credential_generation"


# --- 3. expiry boundary ------------------------------------------------------

@pytest.mark.asyncio
async def test_vector_3_expired_open_denies_identically(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)
    stale_open = harness.open_session_payload(
        session="sess.expired.1", now=harness.now_iso(-7200), ttl=60,
    )
    do_open, svc_open = await _both(sides, "open_session", stale_open)
    assert _normalize(do_open) == _normalize(svc_open)

    auth = harness.auth_payload(session="sess.expired.1")
    do_auth, svc_auth = await _both(sides, "authenticate_device_session", auth)
    assert do_auth == svc_auth
    assert svc_auth["ok"] is False

    fresh_open = harness.open_session_payload(session="sess.fresh.1")
    do_fresh, svc_fresh = await _both(sides, "open_session", fresh_open)
    assert do_fresh["ok"] is True and svc_fresh["ok"] is True
    do_ok, svc_ok = await _both(sides, "authenticate_device_session", harness.auth_payload(session="sess.fresh.1"))
    assert _normalize(do_ok) == _normalize(svc_ok)
    assert svc_ok["ok"] is True


# --- 4. purge on revoke / rotate ---------------------------------------------

def _material(command_id: str) -> dict:
    return {
        "request_id": f"request.{command_id}",
        "run_id": f"run.{command_id}",
        "device_id": harness.DEVICE,
        "root_ref": "root.1",
        "argv": ["python", "-V"],
        "cwd_relative": ".",
        "requested_at": harness.now_iso(),
        "timeout_seconds": 30,
        "shell_authority": False,
        "admin_elevation": False,
        "environment_payload": None,
        "provider_authority": None,
        "p01_approval_payload": None,
    }


def _material_rows(connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM local_agent_command_material").fetchone()[0]


@pytest.mark.asyncio
async def test_vector_4_material_is_purged_by_revoke_on_both_sides(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)
    enqueue = harness.enqueue_payload(command="cmd.purge.1")
    material = {"payload": enqueue, "material": _material("cmd.purge.1")}

    do_enq = sides.do._runtime.enqueue_command_with_material(enqueue, _material("cmd.purge.1"))
    assert do_enq["ok"] is True, do_enq
    async with harness.client_for(sides.app) as client:
        response = await harness.rpc(client, "enqueue_command_with_material", material)
    assert response.status_code == 200
    assert response.json()["ok"] is True, response.text

    do_conn = sides.storage._connection
    svc_conn = sides.app.state.broker_storage._connection
    assert _material_rows(do_conn) == 1 and _material_rows(svc_conn) == 1

    revoke = harness.revoke_payload()
    do_revoke, svc_revoke = await _both(sides, "revoke_binding", revoke)
    assert do_revoke["ok"] is True and svc_revoke["ok"] is True
    assert _material_rows(do_conn) == 0 and _material_rows(svc_conn) == 0


# --- 5. replay / sequence ----------------------------------------------------

@pytest.mark.asyncio
async def test_vector_5_exact_retry_and_sequence_agree(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)
    first = harness.enqueue_payload(command="cmd.replay.1")

    do_first = sides.do._runtime.enqueue_command(first)
    async with harness.client_for(sides.app) as client:
        svc_first = (await harness.rpc(client, "enqueue_command_with_material",
                                       {"payload": first, "material": _material("cmd.replay.1")}))
    # Without material the command cannot be acknowledged; the skeleton door
    # exposes the atomic form, so compare the atomic envelopes instead.
    assert svc_first.status_code == 200
    do_atomic = sides.do._runtime.enqueue_command_with_material(first, _material("cmd.replay.1"))
    assert _normalize(do_atomic["command"]) == _normalize(svc_first.json()["command"])

    async with harness.client_for(sides.app) as client:
        retry = await harness.rpc(client, "enqueue_command_with_material",
                                  {"payload": first, "material": _material("cmd.replay.1")})
    do_retry = sides.do._runtime.enqueue_command_with_material(first, _material("cmd.replay.1"))
    assert _normalize(do_retry) == _normalize(retry.json())

    second = harness.enqueue_payload(command="cmd.replay.2")
    do_second = sides.do._runtime.enqueue_command_with_material(second, _material("cmd.replay.2"))
    async with harness.client_for(sides.app) as client:
        svc_second = await harness.rpc(client, "enqueue_command_with_material",
                                       {"payload": second, "material": _material("cmd.replay.2")})
    assert do_second["ok"] is True and svc_second.json()["ok"] is True
    # Both sides minted the same per-binding sequence for their first command.
    assert _normalize(do_first["command"]) == _normalize(svc_first.json()["command"])
    assert do_second["command"]["sequence"] == svc_second.json()["command"]["sequence"]


# --- 6. scope ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_vector_6_scope_and_bad_credential_deny_identically(sides):
    _seed(sides.do)
    _seed(sides.app.state.broker)
    wrong_scope = harness.open_session_payload(
        session="sess.scope.1", account="usr_" + "b" * 32,
    )
    do_scope, svc_scope = await _both(sides, "open_session", wrong_scope)
    assert _normalize(do_scope) == _normalize(svc_scope)
    assert svc_scope["ok"] is False

    bad = harness.auth_payload(session="sess.scope.1", credential=b"wrong-secret")
    do_bad, svc_bad = await _both(sides, "authenticate_device_session", bad)
    assert do_bad == svc_bad
    assert svc_bad == {
        "ok": False,
        "error": {"code": "device_session_auth_failed",
                  "message": svc_bad["error"]["message"]},
    }
    assert "wrong-secret" not in json.dumps(svc_bad)


# --- 7. real-socket concurrency ---------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_vector_7_two_concurrent_rotations_exactly_one_wins(tmp_path):
    app = broker_service.build_app(environ=harness.environ(tmp_path))
    _seed(app.state.broker)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 10
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started

        rotate = {
            "binding_ref": harness.BINDING, "expected_generation": 1,
            "new_credential_b64": base64.b64encode(b"rotated-over-socket").decode(),
            "now": harness.now_iso(),
        }

        async def fire():
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                response = await harness.rpc(client, "rotate_credential", rotate)
                assert response.status_code == 200
                return response.json()

        async def race():
            return await asyncio.gather(fire(), fire())

        outcomes = _run(race())
        wins = [item for item in outcomes if item.get("ok") is True]
        losses = [item for item in outcomes if item.get("ok") is False]
        assert len(wins) == 1 and len(losses) == 1, outcomes
        assert losses[0]["error"]["code"] == "stale_device_credential_generation"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.state.broker_storage.close()


# --- 8. rollback rehearsal ---------------------------------------------------

def _table_digests(connection) -> dict[str, str]:
    digests = {}
    for table in ("local_agent_broker_state", "local_agent_broker_used_command_id",
                  "local_agent_command_material", "local_agent_http_session"):
        try:
            rows = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        except sqlite3.DatabaseError:
            rows = []
        payload = json.dumps(sorted((json.dumps(row, sort_keys=True, default=str) for row in rows)))
        digests[table] = hashlib.sha256(payload.encode()).hexdigest()
    return digests


def _load_backup_module():
    spec = importlib.util.spec_from_file_location("broker_backup", _DEPLOY / "backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _restore_snapshot(db_path: Path, snapshot_path: Path) -> None:
    """Stage-B-style restore replayed on SQLite: replace every broker table."""

    live = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        live.execute("ATTACH DATABASE ? AS snap", (str(snapshot_path),))
        live.execute("BEGIN IMMEDIATE")
        try:
            for table in ("local_agent_broker_state", "local_agent_broker_used_command_id",
                          "local_agent_command_material", "local_agent_http_session"):
                live.execute(f"DELETE FROM main.{table}")
                live.execute(f"INSERT INTO main.{table} SELECT * FROM snap.{table}")
            live.execute("COMMIT")
        except Exception:
            live.execute("ROLLBACK")
            raise
        finally:
            live.execute("DETACH DATABASE snap")
    finally:
        live.close()


def test_vector_8_snapshot_restore_returns_the_exact_prior_state(tmp_path):
    app = broker_service.build_app(environ=harness.environ(tmp_path))
    db_path = tmp_path / "broker.sqlite3"
    backup = _load_backup_module()
    try:
        _seed(app.state.broker)
        before = _table_digests(app.state.broker_storage._connection)
        result = backup.snapshot(db_path, tmp_path / "backups", keep=7)
        snapshot_path = tmp_path / "backups" / result["file"]
        assert snapshot_path.is_file()

        # Mutate after the snapshot: a fresh session is written to the live DB.
        opened = app.state.broker._runtime.open_session(harness.open_session_payload())
        assert opened["ok"] is True
        mutated = _table_digests(app.state.broker_storage._connection)
        assert mutated != before

        _restore_snapshot(db_path, snapshot_path)
        restored = _table_digests(app.state.broker_storage._connection)
        assert restored == before
    finally:
        app.state.broker_storage.close()
