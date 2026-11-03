"""#5881 follow-on — the internal call is a door with a list of names on it.

The queue answers only the names it declared, only for a caller that proves the service
secret, and never repeats back what it was handed: an argument can name a customer's
path, and the store's own exception text is not ours to publish.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import json
import pathlib
import sqlite3
import pytest
import sys

import pytest
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from schema import apply  # noqa: E402
from internal_store import (
    INTERNAL_STORE_PATH, PAIRING_METHODS, QUEUE_SERVICE_SECRET_HEADER,
)  # noqa: E402


def _load_queue_service():
    # Another suite may already have a top-level ``service`` module cached (the
    # broker owns one too), so this helper loads the queue's own file by path.
    spec = importlib.util.spec_from_file_location(
        "padiem_mesh_queue_service_under_test", QUEUE / "service.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_app = _load_queue_service().create_app

SECRET = "queue-channel-secret-value-261029"
SERVICE_SECRET = "queue-service-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire, *, secret=SERVICE_SECRET):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if wire is None else json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body))})
        if secret is not None:
            self.headers[QUEUE_SERVICE_SECRET_HEADER.lower()] = secret
        self._body = body

    async def body(self):
        return self._body


def _app(**kwargs):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    kwargs.setdefault("service_secret", SERVICE_SECRET)
    return create_app(connection=connection, channel_secret=SECRET,
                      ownership_map=json.dumps(OWNERSHIP), mode="mesh", **kwargs)


def _handler(app):
    return next(route.endpoint for route in app.routes if route.path == INTERNAL_STORE_PATH)


def _call(app, wire, **kwargs):
    return asyncio.run(_handler(app)(_Request(app.state, wire, **kwargs)))


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def test_an_undeclared_name_is_refused_before_anything_is_read():
    response = _call(_app(), {"method": "delete_everything", "arguments": {}})
    assert response.status_code == 400
    assert _body(response)["error"]["code"] == "queue_method_not_allowed"


def test_a_caller_without_the_service_secret_is_refused():
    app = _app()
    for secret in (None, "wrong-service-secret-value-0000"):
        response = _call(app, {"method": "list_links", "arguments": {"user_id": "u"}},
                         secret=secret)
        assert response.status_code == 403, secret
        assert _body(response)["error"]["code"] == "queue_channel_rejected"


def test_a_declared_name_runs_on_the_real_store_and_answers_with_its_result():
    app = _app()
    issued = _body(_call(app, {"method": "issue_code",
                               "arguments": {"user_id": "usr_" + "a" * 32,
                                             "issued_at": "2026-10-29T00:00:00.000Z"}}))
    assert issued["ok"] is True and issued["result"]["install_tag"]
    listed = _body(_call(app, {"method": "list_links", "arguments": {
        "user_id": "usr_" + "a" * 32}}))
    assert listed == {"ok": True, "result": []}


def test_a_store_failure_is_named_without_repeating_what_it_was_given():
    marker = "C:/Users/customer/private-file.txt"
    response = _call(_app(), {"method": "device_scope",
                              "arguments": {"device_id": marker, "unexpected": 1}})
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "queue_store_failed"
    assert marker not in response.body.decode("utf-8")


def test_the_door_is_not_even_open_without_a_service_secret_installed():
    app = _app(service_secret=None)
    assert not any(route.path == INTERNAL_STORE_PATH for route in app.routes)


def test_only_the_two_declared_keys_are_accepted():
    response = _call(_app(), {"method": "list_links", "arguments": {}, "extra": 1})
    assert response.status_code == 400
    assert _body(response)["error"]["code"] == "queue_invalid_body"


def test_pairing_store_is_reachable_through_the_same_object_the_executor_lane_uses():
    app = _app()
    assert isinstance(app.state.pc_device_pairing_store, D1PcPairingStore)
    links = asyncio.run(app.state.pc_device_pairing_store.list_links(
        user_id="usr_" + "a" * 32))
    assert links == []


def test_the_body_gate_admits_exactly_the_limit_and_refuses_one_byte_more():
    """2026-11-02 한도 감사 2번 — RPC 본문 상한 8MB의 경계 계약.

    JSON 공백으로 본문을 정확히 상한에 맞춘다(파싱 결과는 같은 호출): 정확히 상한은
    200 통과, +1바이트는 기존과 같은 413/queue_body_too_large.
    """
    from internal_store import MAX_INTERNAL_BODY_BYTES

    app = _app()

    def raw_body(total):
        wire = {"method": "list_links", "arguments": {"user_id": "usr_" + "a" * 32}}
        body = json.dumps(wire).encode("utf-8")
        pad = total - len(body)
        assert pad >= 0
        return b"{" + b" " * pad + body[1:]

    at_limit = raw_body(MAX_INTERNAL_BODY_BYTES)
    assert len(at_limit) == MAX_INTERNAL_BODY_BYTES
    admitted = _Request(app.state, None)
    admitted._body = at_limit
    admitted.headers["content-length"] = str(len(at_limit))
    ok = asyncio.run(_handler(app)(admitted))
    assert ok.status_code == 200, ok.body
    assert _body(ok)["ok"] is True

    over = raw_body(MAX_INTERNAL_BODY_BYTES + 1)
    assert len(over) == MAX_INTERNAL_BODY_BYTES + 1
    refused_request = _Request(app.state, None)
    refused_request._body = over
    refused_request.headers["content-length"] = str(len(over))
    refused = asyncio.run(_handler(app)(refused_request))
    assert refused.status_code == 413
    assert _body(refused)["error"]["code"] == "queue_body_too_large"


def test_delete_account_pc_data_rpc_is_idempotent_and_preserves_shared_history(tmp_path):
    app = _app(output_directory=str(tmp_path / "pc-outputs"),
               background_jobs_directory=str(tmp_path / "background-jobs"))
    connection = app.state.queue_database.connection
    assert "delete_account_pc_data" in PAIRING_METHODS

    owner, other = "account-one", "account-two"
    now = "2026-11-03T00:00:00Z"
    later = "2026-11-04T00:00:00Z"
    for suffix, user, digest in (("one", owner, "a"), ("two", other, "b")):
        code_id = "code-" + suffix
        connection.execute(
            "INSERT INTO pc_pairing_codes "
            "(code_id, code_sha256, tag_sha256, user_id, state, issued_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (code_id, digest * 64, ("c" if suffix == "one" else "d") * 64,
             user, "pending", now, later),
        )
        connection.execute(
            "INSERT INTO pc_install_tokens "
            "(token_id, token_sha256, code_id, user_id, issued_at, expires_at) "
            "VALUES (?,?,?,?,?,?)",
            ("token-" + suffix, ("e" if suffix == "one" else "f") * 64,
             code_id, user, now, later),
        )
        connection.execute(
            "INSERT INTO pc_device_links "
            "(link_id, user_id, mesh_node_id, state, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            ("link-" + suffix, user, "node/demo/pc-" + suffix, "active", now, now),
        )
        connection.execute(
            "INSERT INTO oracle_mesh_dispatch "
            "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
            "revision_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "node_ref, root_ref, path_relative, file_path, state, expires_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dispatch-" + suffix, user, "run-" + suffix, "command-" + suffix,
                "tool-" + suffix, "request-" + suffix, "revision-" + suffix,
                ("1" if suffix == "one" else "2") * 64, "account-" + suffix,
                "workspace-" + suffix, "device-" + suffix, "node-" + suffix,
                "root-" + suffix, "file.txt", "C:/file.txt", "consumed", later, now,
            ),
        )
    for device, refs in (("shared-device", [owner, other]), ("owner-device", [owner])):
        connection.execute(
            "INSERT INTO mesh_device_presence "
            "(device_id, connected, received_at, credential_generation, source, "
            "last_connected_at, account_refs_json) VALUES (?,?,?,?,?,?,?)",
            (device, 1, now, 1, "broker", now, json.dumps(refs)),
        )
    connection.execute(
        "INSERT INTO mesh_device_drives (device_id, drives_json, received_at) VALUES (?,?,?)",
        ("shared-device", json.dumps(["C:"]), now),
    )

    for _ in range(2):
        response = _call(app, {
            "method": "delete_account_pc_data",
            "arguments": {"user_id": owner},
        })
        assert response.status_code == 200, response.body
        assert _body(response) == {"ok": True, "result": True}

    for table in ("pc_pairing_codes", "pc_install_tokens", "pc_device_links"):
        assert connection.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (owner,)
        ).fetchone()["n"] == 0
        assert connection.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (other,)
        ).fetchone()["n"] == 1

    shared = connection.execute(
        "SELECT account_refs_json FROM mesh_device_presence WHERE device_id = ?",
        ("shared-device",),
    ).fetchone()
    assert shared is not None
    assert json.loads(shared["account_refs_json"]) == [other]
    assert connection.execute(
        "SELECT COUNT(*) AS n FROM mesh_device_presence WHERE device_id = ?",
        ("owner-device",),
    ).fetchone()["n"] == 0

    # Replay-prevention history is retained, without the account in it; the
    # device-wide drive inventory stays untouched.
    assert connection.execute(
        "SELECT COUNT(*) AS n FROM oracle_mesh_dispatch WHERE user_id = ?", (owner,)
    ).fetchone()["n"] == 0
    scrubbed = connection.execute(
        "SELECT * FROM oracle_mesh_dispatch WHERE dispatch_id = ?", ("dispatch-one",)
    ).fetchone()
    assert scrubbed is not None
    assert scrubbed["user_id"].startswith("deleted:")
    for column in ("account_ref", "workspace_ref", "device_id", "node_ref", "root_ref"):
        assert scrubbed[column] == scrubbed["user_id"], column
    assert scrubbed["path_relative"] == "deleted"
    assert scrubbed["file_path"] == "deleted"
    assert scrubbed["command_text"] is None
    # Replay keys are unchanged, and the second idempotent call above did not
    # mint a second token for the same row.
    assert scrubbed["run_id"] == "run-one"
    assert scrubbed["request_fingerprint"] == "1" * 64
    other_dispatch = connection.execute(
        "SELECT * FROM oracle_mesh_dispatch WHERE dispatch_id = ?", ("dispatch-two",)
    ).fetchone()
    assert other_dispatch["user_id"] == other
    assert other_dispatch["account_ref"] == "account-two"
    assert other_dispatch["file_path"] == "C:/file.txt"
    # The scrubbed row still refuses the same run: replay prevention survives.
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO oracle_mesh_dispatch "
            "(dispatch_id, user_id, run_id, command_id, tool_request_ref, request_id, "
            "revision_ref, request_fingerprint, account_ref, workspace_ref, device_id, "
            "node_ref, root_ref, path_relative, file_path, state, expires_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "dispatch-replay", scrubbed["user_id"], "run-one", "command-r",
                "tool-r", "request-r", "revision-r", "3" * 64, "account-r",
                "workspace-r", "device-r", "node-r", "root-r", "file.txt",
                "C:/file.txt", "pending", later, now,
            ),
        )
    drive_columns = {
        row["name"] for row in connection.execute(
            "PRAGMA table_info(mesh_device_drives)"
        ).fetchall()
    }
    assert "user_id" not in drive_columns
    assert connection.execute(
        "SELECT COUNT(*) AS n FROM mesh_device_drives WHERE device_id = ?",
        ("shared-device",),
    ).fetchone()["n"] == 1


def test_queue_account_cleanup_removes_only_target_job_and_output_files(tmp_path):
    background = tmp_path / "executor" / "background-jobs"
    app = _app(output_directory=str(tmp_path / "pc-outputs"),
               background_jobs_directory=str(background))
    store = app.state.pc_output_store
    users = ("account-one", "account-two")

    async def write_output(user):
        fields = dict(user_id=user, subject_id="subject-" + user,
                      run_id="run-" + user, device_id="device-" + user)
        content = ("output-" + user).encode()
        begin = await store.begin_pc_output(
            **fields, source="test", size=len(content),
            sha256=hashlib.sha256(content).hexdigest())
        await store.append_pc_output(
            **fields, upload_id=begin["upload_id"], offset=0,
            data=base64.b64encode(content).decode())
        ref = await store.finish_pc_output(**fields, upload_id=begin["upload_id"])
        owner = store._owner(**fields)
        scope = hashlib.sha256(owner.encode()).hexdigest()
        return fields, ref, scope, content

    first, second = asyncio.run(write_output(users[0])), asyncio.run(write_output(users[1]))
    background.mkdir(parents=True)
    job_paths = {}
    for user in users:
        owner = json.dumps([user, "node-" + user, "run-" + user],
                           separators=(",", ":"))
        job_id = "job-" + user
        name = hashlib.sha256(json.dumps([owner, job_id], separators=(",", ":")).encode()).hexdigest()
        receipt = background / (name + ".json")
        receipt.write_text(json.dumps({"job_id": job_id, "owner": owner, "state": "done"}))
        (background / (name + ".log")).write_bytes(("job-" + user).encode())
        job_paths[user] = receipt

    response = _call(app, {
        "method": "delete_account_pc_data",
        "arguments": {"user_id": users[0]},
    })
    assert response.status_code == 200, response.body
    assert _body(response) == {"ok": True, "result": True}
    assert not job_paths[users[0]].exists()
    assert job_paths[users[1]].exists()
    assert not (background / (job_paths[users[0]].stem + ".log")).exists()
    assert (background / (job_paths[users[1]].stem + ".log")).exists()
    assert not (tmp_path / "pc-outputs" / "outputs" / first[2]).exists()
    assert not (tmp_path / "pc-outputs" / "uploads" / first[2]).exists()
    assert (tmp_path / "pc-outputs" / "outputs" / second[2]).exists()
    assert (tmp_path / "pc-outputs" / "uploads" / second[2]).exists()
    assert asyncio.run(store.read_pc_output(
        **second[0], handle=second[1]["handle"], offset=0, length=len(second[3])
    ))["content"] == second[3].decode()
    with pytest.raises(ValueError, match="deleted"):
        asyncio.run(store.read_pc_output(
            **first[0], handle=first[1]["handle"], offset=0, length=len(first[3])
        ))

    replay = _call(app, {
        "method": "delete_account_pc_data",
        "arguments": {"user_id": users[0]},
    })
    assert replay.status_code == 200, replay.body
    assert job_paths[users[1]].exists()
    assert (tmp_path / "pc-outputs" / "outputs" / second[2]).exists()


def test_account_delete_fails_closed_without_shared_executor_work_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ORACLE_MESH_WORK_DIR", raising=False)
    app = _app(output_directory=str(tmp_path / "pc-outputs"),
               background_jobs_directory=None)
    response = _call(app, {
        "method": "delete_account_pc_data",
        "arguments": {"user_id": "account-one"},
    })
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "queue_store_failed"

def test_queue_uses_the_executor_work_directory_for_receipt_deletion(tmp_path, monkeypatch):
    work_dir = tmp_path / "executor-work"
    monkeypatch.setenv("ORACLE_MESH_WORK_DIR", str(work_dir))
    app = _app(output_directory=str(tmp_path / "pc-outputs"),
               background_jobs_directory=None)
    assert app.state.pc_device_pairing_store.background_jobs_directory == work_dir / "background-jobs"
