"""Offline MCP gateway account and approval fixtures."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from starlette.routing import Route

from app.mcp_gateway_account_routes import (
    MCP_APPROVAL_PATH, MCP_APPROVALS_PATH, MCP_TOKEN_PATH, MCP_TOKENS_PATH,
    mcp_approval_post, mcp_approvals_get, mcp_token_delete, mcp_tokens_get,
    mcp_tokens_post,
)
from app.mcp_gateway_store import D1McpGatewayStore
from _support.account_selection import (
    BASE as BASE, build_app, client_for as client_for, seed_db, session as session,
)


MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "085_mcp_gateway.sql"
SHELL_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "094_mcp_shell_audit.sql"
OAUTH_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "095_mcp_oauth.sql"
COMMON_JOB_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "099_mcp_common_job_receipts.sql"
SCOPE_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "100_mcp_token_device_scope.sql"
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
DEVICE = "node//test-owner-pc"
FAKE_SECRET = "fixed-test-material-not-a-live-credential"



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
