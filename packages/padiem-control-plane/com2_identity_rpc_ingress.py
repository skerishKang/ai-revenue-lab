"""CPython identity RPC ingress; no identity authority or schema is created here.

Callers must supply the existing canonical identity authority bound to its
authoritative storage.  This adapter must not be deployed as a new authority.

The signed-request policy and replay memory (#6417) are composed here, against
a durable local SQLite file: this host has no Durable Object storage, and a
process-local set would forget every id on restart, which is the one thing a
replay guard must not do. The table is the same shape as the Worker's, and the
database path is configuration — ``PADIEM_COM2_IDENTITY_REPLAY_DB``, never a
default inside the repository. Without a path the ingress behaves exactly as
it did before v2: a v1 request still passes, and a v2 request is refused
``503 rpc_replay_guard_unavailable`` rather than served unguarded.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from internal_rpc_ingress import (
    SERVICE_ID_POLICY_ENV,
    handle_internal_rpc,
    service_id_policy_from_env,
)

# The 9 existing identity ingress calls plus the three private enrollment
# methods needed by the connector pairing flow. This is a CPython-only set.
COM2_IDENTITY_RPC_METHODS = frozenset({
    "resolve_or_create_product_link", "establish_auth_session",
    "resolve_auth_session", "resolve_current_auth_session",
    "revoke_auth_session", "revoke_all_auth_sessions",
    "resolve_product_user_for_subject", "resolve_connector_workspace",
    "resolve_connector_context",
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
    "issue_google_connect_ticket", "create_tenant", "get_tenant",
    "assign_tenant_membership", "revoke_tenant_membership",
    "resolve_active_memberships", "resolve_active_tenant_membership",
    "install_connector_enrollment_schema", "resolve_connector_owner_scope",
    "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
})

SERVICE_ID_REPLAY_DB_ENV = "PADIEM_COM2_IDENTITY_REPLAY_DB"

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS service_request_ids ("
    "service_id TEXT PRIMARY KEY, expires_at INTEGER NOT NULL)"
)
_PRUNE = "DELETE FROM service_request_ids WHERE expires_at<=?"
_INSERT = "INSERT INTO service_request_ids (service_id, expires_at) VALUES (?, ?)"


class SqliteServiceIdReplayStore:
    """One durable row per consumed request id, pruned after its clock window.

    ``claim`` is one ``BEGIN IMMEDIATE`` transaction, so two processes sharing
    the file cannot both take the same id; the primary key makes the insert
    itself the decision.
    """

    def __init__(self, path: str, *, clock=None) -> None:
        text = "" if path is None else str(path).strip()
        if not text or text == ":memory:":
            raise ValueError("durable service-id replay database path required")
        self._path = text
        self._clock = clock or (lambda: int(time.time()))
        with closing(self._connect()) as db:
            db.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5, isolation_level=None)

    async def claim(self, service_id: str, *, expires_at: int) -> bool:
        current = int(self._clock())
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(_PRUNE, (current,))
            try:
                db.execute(
                    _INSERT,
                    (service_id, max(int(expires_at), current + 1)),
                )
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return False
            db.execute("COMMIT")
        return True


def _replay_guard(replay_db: str | None, policy: str):
    """The guard for the configured database, or None when none is configured."""

    path = replay_db if replay_db is not None else os.environ.get(SERVICE_ID_REPLAY_DB_ENV)
    text = "" if path is None else str(path).strip()
    if not text:
        if policy == "required":
            # Required ids without memory for them refuses every v2 request;
            # failing at composition names the missing setting once.
            raise ValueError(f"{SERVICE_ID_REPLAY_DB_ENV} is required for the required policy")
        return None
    return SqliteServiceIdReplayStore(text)


def create_app(
    *,
    authority,
    secret: str,
    service_id_policy: str | None = None,
    replay_db: str | None = None,
) -> Starlette:
    """Construct the private ingress over an already configured authority.

    This is an injected composition seam, not a standalone production service;
    startup, loopback binding and state ownership must be wired separately.
    """
    if authority is None:
        raise ValueError("canonical identity authority required")
    if not isinstance(secret, str) or len(secret.strip()) < 32:
        raise ValueError("identity ingress secret is required")

    configured_policy = (
        service_id_policy
        if service_id_policy is not None
        else os.environ.get(SERVICE_ID_POLICY_ENV)
    )
    policy = service_id_policy_from_env(configured_policy)
    guard = _replay_guard(replay_db, policy)

    async def rpc(request: Request) -> JSONResponse:
        result = await handle_internal_rpc(
            request, secret=secret, allowed_methods=COM2_IDENTITY_RPC_METHODS,
            dispatcher=authority, service_id_policy=policy, replay_guard=guard,
        )
        if result is None:
            return JSONResponse({"ok": False, "error": {"code": "not_found", "message": "Not Found"}}, status_code=404)
        status, payload, headers = result
        return JSONResponse(payload, status_code=status, headers=headers)

    return Starlette(routes=[Route("/internal/rpc/{method}", rpc, methods=["POST"])])
