"""Real SQLite credential/confirmation lifecycle and account boundaries."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from starlette.routing import Route

from app.mcp_gateway_account_routes import (
    MCP_APPROVAL_PATH, MCP_APPROVALS_PATH, MCP_TOKEN_PATH, MCP_TOKENS_PATH,
    authenticate_mcp_request, mcp_approval_post, mcp_approvals_get,
    mcp_token_delete, mcp_tokens_get, mcp_tokens_post,
)
from app.mcp_gateway_store import (
    D1McpGatewayStore, MCP_APPROVAL_TTL_SECONDS, McpGatewayStoreError,
)
from test_5222_account_model_selection import BASE, build_app, client_for, seed_db, session


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "085_mcp_gateway.sql"
SHELL_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "094_mcp_shell_audit.sql"
OAUTH_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "095_mcp_oauth.sql"
COMMON_JOB_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "099_mcp_common_job_receipts.sql"
SCOPE_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "100_mcp_token_device_scope.sql"
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
DEVICE = "node//test-owner-pc"
FAKE_SECRET = "fixed-test-material-not-a-live-credential"


def test_099_receipt_migration_runs_after_097_without_intermediate_file(tmp_path):
    from app.local_cpython import LOCAL_LEDGER_TABLE, apply_migrations

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "097_seed.sql").write_text(
        "CREATE TABLE padiem_mcp_audit (user_id TEXT, token_id TEXT, device_id TEXT);\n",
        encoding="utf-8",
    )
    (migrations / COMMON_JOB_MIGRATION.name).write_text(
        COMMON_JOB_MIGRATION.read_text(encoding="utf-8"), encoding="utf-8",
    )
    db = sqlite3.connect(":memory:")
    assert apply_migrations(db, migrations) == 2
    columns = {row[1] for row in db.execute("PRAGMA table_info(padiem_mcp_audit)")}
    applied = {row[0] for row in db.execute(f"SELECT name FROM {LOCAL_LEDGER_TABLE}")}
    assert "job_receipt_sha256" in columns
    assert applied == {"097_seed.sql", "099_mcp_common_job_receipts.sql"}


class Pairing:
    def __init__(self, owner):
        self.owner, self.active = owner, True

    async def link_for(self, *, user_id, mesh_node_id):
        if self.active and user_id == self.owner and mesh_node_id == DEVICE:
            return {"mesh_node_id": DEVICE, "roots": [{"path": "C:/Documents"}]}
        return None

    async def links_for_owner(self, *, user_id):
        if self.active and user_id == self.owner:
            return [{"mesh_node_id": DEVICE, "label": "Owner PC",
                     "roots": [{"path": "C:/Documents"}]}]
        return []


def setup():
    db, owner, other, _ = seed_db()
    for path in (MIGRATION, SHELL_MIGRATION, OAUTH_MIGRATION, COMMON_JOB_MIGRATION,
                 SCOPE_MIGRATION):
        if path.exists():
            db.conn.executescript(path.read_text(encoding="utf-8"))
    store = D1McpGatewayStore(db, secret_factory=lambda: FAKE_SECRET)
    return db, owner, other, store


def account_app(db, owner, store):
    app = build_app(db)
    app.state.mcp_gateway_store = store
    app.state.pc_device_pairing_store = Pairing(owner)
    # Also supports the focused test before app_factory registration lands.
    paths = {route.path for route in app.routes}
    if MCP_TOKENS_PATH not in paths:
        app.router.routes.extend([
            Route(MCP_TOKENS_PATH, mcp_tokens_get, methods=["GET"]),
            Route(MCP_TOKENS_PATH, mcp_tokens_post, methods=["POST"]),
            Route(MCP_TOKEN_PATH, mcp_token_delete, methods=["DELETE"]),
            Route(MCP_APPROVALS_PATH, mcp_approvals_get, methods=["GET"]),
            Route(MCP_APPROVAL_PATH, mcp_approval_post, methods=["POST"]),
        ])
    return app


async def issued(store, owner):
    token = await store.issue_token(user_id=owner, device_id=DEVICE, name="Local test", now=NOW)
    identity = await store.authenticate(token["token"], now=NOW)
    return token, identity


@pytest.mark.asyncio
async def test_token_hash_only_list_and_revocation_are_owner_scoped():
    db, owner, other, store = setup()
    token, identity = await issued(store, owner)
    assert identity["user_id"] == owner and identity["device_id"] == DEVICE
    raw = dict(db.conn.execute("SELECT * FROM padiem_mcp_tokens").fetchone())
    assert FAKE_SECRET not in json.dumps(raw)
    assert token["token"] not in json.dumps(await store.list_tokens(user_id=owner))
    assert "token_sha256" not in (await store.list_tokens(user_id=owner))[0]
    assert await store.list_tokens(user_id=other) == []
    assert await store.authenticate(token["token"] + "forged") is None
    assert not await store.revoke_token(user_id=other, token_id=token["id"])
    assert await store.authenticate(token["token"])
    assert await store.revoke_token(user_id=owner, token_id=token["id"])
    assert await store.authenticate(token["token"]) is None
    db.conn.executescript(MIGRATION.read_text())
    assert await store.authenticate(token["token"]) is None


@pytest.mark.asyncio
async def test_bearer_cannot_borrow_session_or_other_account_pc_and_pause_revokes_use():
    db, owner, other, store = setup()
    app = account_app(db, owner, store)
    token, _ = await issued(store, owner)
    request = SimpleNamespace(app=app, headers={"authorization": "Bearer " + token["token"]})
    principal = await authenticate_mcp_request(request)
    assert principal == {"owner_id": owner, "device_id": DEVICE, "token_id": token["id"], "name": "Local test",
                         "device_scope": None, "device_scope_json": None}
    app.state.pc_device_pairing_store.active = False
    assert await authenticate_mcp_request(request) is None
    app.state.pc_device_pairing_store.active = True
    # Even an erroneously issued token cannot supply a different owner's link.
    wrong = await store.issue_token(user_id=other, device_id=DEVICE, name="Other", now=NOW)
    request.headers = {"authorization": "Bearer " + wrong["token"]}
    assert await authenticate_mcp_request(request) is None
    request.headers = {}
    assert await authenticate_mcp_request(request) is None


@pytest.mark.asyncio
async def test_approval_binds_exact_material_owner_token_device_and_consumes_once():
    db, owner, other, store = setup()
    _, identity = await issued(store, owner)
    args = {"path": "C:/Documents/a.txt", "content": "actual owner-reviewed material"}
    pending = await store.create_approval(identity=identity, tool_name="pc_write", arguments=args, now=NOW)
    assert pending["status"] == "pending" and pending["arguments"] == args
    assert await store.get_approval(user_id=other, approval_id=pending["id"]) is None
    assert await store.decide_approval(user_id=other, approval_id=pending["id"], request_digest=pending["request_digest"], decision="approve", now=NOW) is None
    assert await store.decide_approval(user_id=owner, approval_id=pending["id"], request_digest="f" * 64, decision="approve", now=NOW) is None
    consume = dict(identity=identity, approval_id=pending["id"], tool_name="pc_write", arguments=args, now=NOW)
    assert await store.consume_approval(**consume) is None
    decided = await store.decide_approval(user_id=owner, approval_id=pending["id"], request_digest=pending["request_digest"], decision="approve", now=NOW)
    assert decided["status"] == "approved"
    assert await store.consume_approval(**{**consume, "arguments": {**args, "content": "changed"}}) is None
    assert await store.consume_approval(**{**consume, "identity": {**identity, "device_id": "node/another-pc"}}) is None
    another, other_identity = await issued(store, owner)
    assert another["id"] != identity["token_id"]
    assert await store.consume_approval(**{**consume, "identity": other_identity}) is None
    claims = await asyncio.gather(store.consume_approval(**consume), store.consume_approval(**consume))
    assert sum(claim is not None for claim in claims) == 1
    assert await store.consume_approval(**consume) is None
    assert (await store.get_approval(user_id=owner, approval_id=pending["id"]))["status"] == "consumed"


@pytest.mark.asyncio
async def test_ordinary_mcp_retry_claims_matching_owner_approval_once_without_metadata():
    _, owner, _, store = setup()
    _, identity = await issued(store, owner)
    arguments = {"path": "C:/Documents/a.txt", "content": "exact contents"}
    pending = await store.create_approval(identity=identity, tool_name="pc_write", arguments=arguments, now=NOW)
    call = dict(identity=identity, tool_name="pc_write", arguments=arguments, now=NOW)
    assert await store.consume_matching_approval(**call) is None
    await store.decide_approval(user_id=owner, approval_id=pending["id"], request_digest=pending["request_digest"], decision="approve", now=NOW)
    assert await store.consume_matching_approval(**{**call, "arguments": {**arguments, "path": "C:/Documents/b.txt"}}) is None
    _, another = await issued(store, owner)
    assert await store.consume_matching_approval(**{**call, "identity": another}) is None
    claims = await asyncio.gather(store.consume_matching_approval(**call), store.consume_matching_approval(**call))
    assert sum(claim is not None for claim in claims) == 1
    assert next(claim for claim in claims if claim)["approval_id"] == pending["id"]
    assert await store.consume_matching_approval(**call) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["expired", "revoked", "denied"])
async def test_expired_revoked_and_denied_confirmations_cannot_execute(blocked):
    _, owner, _, store = setup()
    token, identity = await issued(store, owner)
    pending = await store.create_approval(identity=identity, tool_name="pc_delete", arguments={"path": "a.txt"}, now=NOW)
    decision = "deny" if blocked == "denied" else "approve"
    assert await store.decide_approval(user_id=owner, approval_id=pending["id"], request_digest=pending["request_digest"], decision=decision, now=NOW)
    if blocked == "revoked":
        await store.revoke_token(user_id=owner, token_id=token["id"], now=NOW)
    moment = NOW + timedelta(seconds=MCP_APPROVAL_TTL_SECONDS) if blocked == "expired" else NOW
    assert await store.consume_approval(identity=identity, approval_id=pending["id"], tool_name="pc_delete", arguments={"path": "a.txt"}, now=moment) is None
    assert await store.list_approvals(user_id=owner, now=moment) == []


@pytest.mark.asyncio
async def test_audit_records_exact_metadata_without_secret_or_file_content():
    db, owner, _, store = setup()
    token, identity = await issued(store, owner)
    await store.audit(identity=identity, tool_name="pc_write", arguments={"path": "a.txt", "content": "private-file-body"}, status="completed", now=NOW)
    row = dict(db.conn.execute("SELECT * FROM padiem_mcp_audit").fetchone())
    assert row["token_id"] == token["id"] and row["tool_name"] == "pc_write" and row["status"] == "completed"
    assert len(row["request_digest"]) == 64
    assert "private-file-body" not in json.dumps(row) and FAKE_SECRET not in json.dumps(row)


@pytest.mark.asyncio
async def test_common_job_receipt_is_hashed_and_bound_to_token_account_and_pc():
    db, owner, other, store = setup()
    token, identity = await issued(store, owner)
    job_id = "dsp_" + "a" * 32
    await store.audit(
        identity=identity, tool_name="pc_shell_start", arguments={"command": "private-command"},
        status="running", exit_code=0, duration_ms=12, output_bytes=5,
        output_truncated=False, job_receipt_id=job_id, now=NOW,
    )
    row = dict(db.conn.execute("SELECT * FROM padiem_mcp_audit").fetchone())
    assert row["job_receipt_sha256"] == __import__("hashlib").sha256(job_id.encode("ascii")).hexdigest()
    assert row["status"] == "running" and row["exit_code"] == 0 and row["duration_ms"] == 12
    assert row["output_bytes"] == 5 and row["output_truncated"] == 0
    assert job_id not in json.dumps(row) and "private-command" not in json.dumps(row)
    assert await store.owns_job_receipt(identity=identity, job_id=job_id)

    _other_token, other_identity = await issued(store, other)
    assert not await store.owns_job_receipt(identity=other_identity, job_id=job_id)
    _, other_pc_identity = await issued(store, owner)
    other_pc_identity = {**other_pc_identity, "device_id": "node//other-owner-pc"}
    assert not await store.owns_job_receipt(identity=other_pc_identity, job_id=job_id)
    assert not await store.owns_job_receipt(identity=identity, job_id="oracle_mesh_cmd_" + "a" * 32)
    assert await store.revoke_token(user_id=owner, token_id=token["id"], now=NOW)
    assert not await store.owns_job_receipt(identity=identity, job_id=job_id)


@pytest.mark.asyncio
async def test_file_tools_may_record_the_receipt_a_continuation_reads():
    db, owner, _, store = setup()
    _, identity = await issued(store, owner)
    cases = (("pc_read", {"path": "a.txt"}, "dsp_" + "b" * 32),
             ("pc_list", {"path": "."}, "dsp_" + "c" * 32))
    for tool_name, arguments, job_id in cases:
        await store.audit(identity=identity, tool_name=tool_name, arguments=arguments,
                          status="running", job_receipt_id=job_id, now=NOW)
        assert await store.owns_job_receipt(identity=identity, job_id=job_id)
    # Every other tool still cannot write a receipt: its row would be refused
    # and the dispatch cancelled after the PC had already run the work.
    for tool_name, arguments in (("pc_write", {"path": "a.txt", "content": "x"}),
                                 ("pc_browser_open", {"url": "https://example.test/"})):
        with pytest.raises(McpGatewayStoreError):
            await store.audit(identity=identity, tool_name=tool_name, arguments=arguments,
                              status="running", job_receipt_id="dsp_" + "d" * 32, now=NOW)
    assert await store.owns_job_receipt(identity=identity, job_id="dsp_" + "d" * 32) is False


@pytest.mark.asyncio
async def test_account_routes_issue_once_require_own_pc_and_no_owner_override(capsys, caplog):
    db, owner, other, store = setup()
    app = account_app(db, owner, store)
    async with client_for(app) as client:
        assert (await client.get(MCP_TOKENS_PATH)).status_code == 401
        client.cookies.update(session(app, owner))
        cross = await client.post(MCP_TOKENS_PATH, headers={"Origin": "https://other.example.test"}, json={"name": "test", "device_id": DEVICE})
        assert cross.status_code == 403
        forged = await client.post(MCP_TOKENS_PATH, headers={"Origin": BASE}, json={"name": "test", "device_id": DEVICE, "owner_id": other})
        assert forged.status_code == 422
        wrong = await client.post(MCP_TOKENS_PATH, headers={"Origin": BASE}, json={"name": "test", "device_id": "node/other-pc"})
        assert wrong.status_code == 403
        response = await client.post(MCP_TOKENS_PATH, headers={"Origin": BASE}, json={"name": "test", "device_id": DEVICE})
        assert response.status_code == 201
        token = response.json()
        assert "no-store" in response.headers["cache-control"]
        rows = (await client.get(MCP_TOKENS_PATH)).json()["tokens"]
        assert len(rows) == 1 and "token" not in rows[0] and "token_sha256" not in rows[0]
        client.cookies.update(session(app, other))
        assert (await client.get(MCP_TOKENS_PATH)).json()["tokens"] == []
        assert (await client.delete(MCP_TOKENS_PATH + "/" + token["id"], headers={"Origin": BASE})).status_code == 404
        client.cookies.update(session(app, owner))
        assert (await client.delete(MCP_TOKENS_PATH + "/" + token["id"], headers={"Origin": BASE})).status_code == 200
        assert await store.authenticate(token["token"]) is None
        output = capsys.readouterr()
        assert FAKE_SECRET not in output.out + output.err + caplog.text


@pytest.mark.asyncio
async def test_shared_login_without_legacy_cookie_still_requires_same_origin():
    db, owner, _, store = setup()
    app = account_app(db, owner, store)
    request = SimpleNamespace(app=app, cookies={}, headers={"origin": "https://other.example.test"},
                              state=SimpleNamespace(padiem_shared_user_id=owner))
    assert (await mcp_tokens_post(request)).status_code == 403
    request.headers = {}
    assert (await mcp_tokens_post(request)).status_code == 403
    assert await store.list_tokens(user_id=owner) == []


@pytest.mark.asyncio
async def test_owner_ui_confirmation_needs_session_same_origin_and_displayed_digest():
    db, owner, other, store = setup()
    app = account_app(db, owner, store)
    _, identity = await issued(store, owner)
    pending = await store.create_approval(identity=identity, tool_name="pc_write", arguments={"path": "a.txt", "content": "review this"})
    path = MCP_APPROVALS_PATH + "/" + pending["id"]
    body = {"decision": "approve", "request_digest": pending["request_digest"]}
    async with client_for(app) as client:
        assert (await client.post(path, json=body)).status_code == 401
        client.cookies.update(session(app, other))
        assert (await client.get(MCP_APPROVALS_PATH)).json()["approvals"] == []
        assert (await client.post(path, headers={"Origin": BASE}, json=body)).status_code == 404
        client.cookies.update(session(app, owner))
        assert (await client.post(path, headers={"Origin": "https://other.example.test"}, json=body)).status_code == 403
        mismatch = await client.post(path, headers={"Origin": BASE}, json={**body, "request_digest": "f" * 64})
        assert mismatch.status_code == 409
        response = await client.post(path, headers={"Origin": BASE}, json=body)
        assert response.status_code == 200 and response.json()["approval"]["status"] == "approved"
        assert (await client.post(path, headers={"Origin": BASE}, json=body)).status_code == 409
