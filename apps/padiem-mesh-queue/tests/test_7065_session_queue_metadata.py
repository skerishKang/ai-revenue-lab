"""Session identity stays in the existing owned dispatch metadata."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

import service
from app.d1_sqlite import SqliteD1
from app.history import HistoryError
from app.mcp_gateway_session import pc_session_enabled
from background_history import QueueHistoryStore, _operation_json
from test_queue_dispatch_create import _arguments, _queue_db, USER, CHANNEL
from test_queue_claim_lane import _Request, endpoint_of
from app.oracle_mesh_read_return_routes import ORACLE_MESH_READ_POLL_PATH


@pytest.fixture
def database():
    connection = _queue_db()
    yield connection
    connection.close()


def _store(connection):
    return QueueHistoryStore(SqliteD1(connection), run_ownership=service._forwarded_run_ownership)


def _session_arguments(**overrides):
    command = base64.b64encode(json.dumps({
        "v": 1, "op": "start", "shell": "cmd", "command": "",
    }).encode()).decode()
    return {**_arguments(), "kind": "command", "user_mode": True,
            "command_text": json.dumps({"shell": "session", "command": command,
                                        "cwd": None, "timeout_seconds": 0, "distro": None}),
            "background": True, "job_operation": {"op": "session"}, **overrides}


def test_session_marker_survives_reopen_and_owned_public_and_private_projections(database):
    async def run():
        store = _store(database)
        created = await store.create_oracle_mesh_dispatch(**_session_arguments())
        dispatch_id = created["dispatch_id"]
        assert _operation_json({"op": "session"}) == '{"op":"session"}'
        persisted = database.execute(
            "SELECT job_operation_json FROM queue_background_dispatch WHERE dispatch_id=?",
            (dispatch_id,),
        ).fetchone()[0]
        assert json.loads(persisted) == {"op": "session"}
        reopened = _store(database)
        for reader in (reopened.get_oracle_mesh_dispatch_for_owner,
                       reopened.get_pc_output_dispatch_for_owner):
            row = await reader(user_id=USER, dispatch_id=dispatch_id)
            assert row["job_operation"] == {"op": "session"}
            assert row["background"] is True
            assert row["device_id"] == _arguments()["device_id"]
            assert await reader(user_id="another-owner", dispatch_id=dispatch_id) is None
        pending = await reopened.oldest_pending_oracle_mesh_dispatch()
        assert pending["user_mode"] == 1
        assert pending["command_text"] == _session_arguments()["command_text"]
        assert "job_operation" not in pending
        repeated = await reopened.create_oracle_mesh_dispatch(**_session_arguments())
        assert repeated["dispatch_id"] == dispatch_id

    asyncio.run(run())


@pytest.mark.parametrize("overrides", [
    {"background": False}, {"user_mode": False}, {"user_mode": 1},
    {"kind": "read", "command_text": None},
    {"job_operation": {"op": "session", "path": "C:/extra"}},
    {"job_operation": {"op": "session", "session": "a" * 32}},
    {"job_operation": {"op": "session", "text": "never stored"}},
])
def test_invalid_session_metadata_is_rejected_before_any_storage(database, overrides):
    with pytest.raises(HistoryError):
        asyncio.run(_store(database).create_oracle_mesh_dispatch(**_session_arguments(**overrides)))
    assert database.execute("SELECT COUNT(*) FROM oracle_mesh_dispatch").fetchone()[0] == 0
    assert database.execute("SELECT COUNT(*) FROM queue_background_dispatch").fetchone()[0] == 0


@pytest.mark.parametrize("enabled", [False, True])
def test_queue_poll_has_the_same_explicit_default_off_switch(database, tmp_path, enabled):
    app = service.create_app(connection=database, channel_secret=CHANNEL,
                             legacy_map_lane=False, output_directory=str(tmp_path / "output"),
                             mcp_pc_session_enabled=enabled)
    assert pc_session_enabled(SimpleNamespace(app=app)) is enabled


def test_queue_switch_defaults_off(database, tmp_path):
    app = service.create_app(connection=database, channel_secret=CHANNEL,
                             legacy_map_lane=False, output_directory=str(tmp_path / "output"))
    assert pc_session_enabled(SimpleNamespace(app=app)) is False


@pytest.mark.parametrize("value,expected", [(None, False), ("", False), ("0", False),
                                            ("false", False), ("true", True), ("1", True)])
def test_environment_switch_is_forwarded_without_reading_real_configuration(monkeypatch, value, expected):
    captured = {}
    app = SimpleNamespace(state=SimpleNamespace(queue_database=object()))
    if value is None:
        monkeypatch.delenv("PADIEM_MCP_PC_SESSION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PADIEM_MCP_PC_SESSION_ENABLED", value)
    monkeypatch.setenv("MESH_QUEUE_LEGACY_MAP_LANE", "off")
    monkeypatch.setattr(service, "read_secret_file", lambda *args, **kwargs: "x" * 32)
    monkeypatch.setattr(service, "start_liveness_watchdog", lambda database: None)

    def create(**kwargs):
        captured.update(kwargs)
        return app

    monkeypatch.setattr(service, "create_app", create)
    assert service.app_from_environment() is app
    assert captured["mcp_pc_session_enabled"] is expected


def test_invalid_switch_fails_before_configuration_files_are_opened(monkeypatch):
    monkeypatch.setenv("PADIEM_MCP_PC_SESSION_ENABLED", "maybe")
    monkeypatch.setattr(service, "read_secret_file", lambda *args, **kwargs: pytest.fail("unexpected file read"))
    with pytest.raises(ValueError, match="PADIEM_MCP_PC_SESSION_ENABLED"):
        service.app_from_environment()


INPUT_VALUE = "queue-input-private-canary-안녕"
INPUT_REF = "d" * 32
SESSION_ID = "e" * 32


def _input_frame(*, secret=False, operation=None, marker=None, shell="session"):
    document = {"v": 1, "op": "input", "session": SESSION_ID, "secret": secret}
    document.update(operation or {})
    text_marker = {"ref": INPUT_REF, "chars": len(INPUT_VALUE),
                   "bytes": len(INPUT_VALUE.encode("utf-8"))}
    if not secret:
        text_marker["sha256_prefix"] = hashlib.sha256(INPUT_VALUE.encode()).hexdigest()[:8]
    text_marker.update(marker or {})
    return json.dumps({"shell": shell, "command": base64.b64encode(
        json.dumps(document).encode()).decode(), "cwd": None,
        "timeout_seconds": 0, "distro": None,
        "session_input": text_marker})


def _poll_app(database, tmp_path, *, enabled=True):
    return service.create_app(connection=database, channel_secret=CHANNEL,
                              legacy_map_lane=False, output_directory=str(tmp_path / "output"),
                              mcp_pc_session_enabled=enabled)


async def _stage_input(app, *, command=None, user_mode=True, background=False):
    assert await app.state.desktop_text_store.deposit_desktop_text(ref=INPUT_REF, text=INPUT_VALUE)
    arguments = {**_arguments(), "kind": "command", "user_mode": user_mode,
                 "command_text": _input_frame() if command is None else command,
                 "background": background}
    return await app.state.history_store.create_oracle_mesh_dispatch(**arguments)


async def _poll(app, *, secret=CHANNEL):
    return await endpoint_of(app, ORACLE_MESH_READ_POLL_PATH)(
        _Request(app.state, {}, secret=secret))


@pytest.mark.parametrize("secret", [False, True])
def test_poll_delivers_input_once_without_putting_it_in_database(database, tmp_path, caplog, secret):
    async def run():
        app = _poll_app(database, tmp_path)
        created = await _stage_input(app, command=_input_frame(secret=secret))
        response = await _poll(app)
        assert response.status_code == 200
        dispatch = json.loads(response.body)["dispatch"]
        assert dispatch["dispatch_id"] == created["dispatch_id"]
        assert dispatch["session_input_text"] == INPUT_VALUE
        assert "desktop_text" not in dispatch
        stored = database.execute("SELECT command_text FROM oracle_mesh_dispatch").fetchone()[0]
        assert stored == dispatch["command_text"]
        assert INPUT_VALUE not in stored
        assert base64.b64encode(INPUT_VALUE.encode()).decode() not in stored
        if secret:
            assert "sha256_prefix" not in stored
        assert INPUT_VALUE not in "\n".join(database.iterdump())
        assert INPUT_VALUE not in caplog.text
        assert await app.state.desktop_text_store.take_desktop_text(ref=INPUT_REF) is None
        assert json.loads((await _poll(app)).body)["dispatch"] is None

    asyncio.run(run())


def test_switch_off_preserves_the_one_shot_value_and_original_poll_shape(database, tmp_path):
    async def run():
        app = _poll_app(database, tmp_path, enabled=False)
        await _stage_input(app)
        response = await _poll(app)
        assert response.status_code == 200
        dispatch = json.loads(response.body)["dispatch"]
        assert "session_input_text" not in dispatch
        assert "desktop_text" not in dispatch
        assert await app.state.desktop_text_store.take_desktop_text(ref=INPUT_REF) == INPUT_VALUE

    asyncio.run(run())


@pytest.mark.parametrize("command", [
    "echo ordinary-command",
    _input_frame(shell="powershell"),
    _input_frame(operation={"op": "read"}),
    _input_frame(operation={"v": 2}),
    _input_frame(operation={"text_b64": "c3RhbGU="}),
    _input_frame(operation={"secret": "true"}),
    _input_frame(marker={"ref": "not-a-reference"}),
    _input_frame(marker={"chars": 4001}),
    _input_frame(marker={"sha256_prefix": "invalid"}),
    _input_frame(secret=True, marker={"sha256_prefix": "a" * 8}),
])
def test_ordinary_or_forged_marker_cannot_consume_session_input(database, tmp_path, command):
    async def run():
        app = _poll_app(database, tmp_path)
        await _stage_input(app, command=command)
        response = await _poll(app)
        assert response.status_code == 200
        assert "session_input_text" not in json.loads(response.body)["dispatch"]
        assert await app.state.desktop_text_store.take_desktop_text(ref=INPUT_REF) == INPUT_VALUE

    asyncio.run(run())


@pytest.mark.parametrize("arguments", [{"user_mode": False}, {"background": True}])
def test_only_foreground_user_commands_can_take_input(database, tmp_path, arguments):
    async def run():
        app = _poll_app(database, tmp_path)
        await _stage_input(app, **arguments)
        response = await _poll(app)
        assert response.status_code == 200
        assert "session_input_text" not in json.loads(response.body)["dispatch"]
        assert await app.state.desktop_text_store.take_desktop_text(ref=INPUT_REF) == INPUT_VALUE

    asyncio.run(run())


def test_rejected_channel_proof_and_lost_claim_never_take_input(database, tmp_path, monkeypatch):
    async def run():
        app = _poll_app(database, tmp_path)
        await _stage_input(app)
        assert (await _poll(app, secret="invalid-channel-proof")).status_code == 403

        async def lose_claim(**kwargs):
            return False

        monkeypatch.setattr(app.state.history_store, "claim_oracle_mesh_dispatch", lose_claim)
        response = await _poll(app)
        assert response.status_code == 200
        assert json.loads(response.body)["dispatch"] is None
        assert await app.state.desktop_text_store.take_desktop_text(ref=INPUT_REF) == INPUT_VALUE

    asyncio.run(run())
