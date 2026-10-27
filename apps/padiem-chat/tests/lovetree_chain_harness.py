"""ASGI harness that serves the REAL LoveTree handoff routes for a cross-repo chain test.

This is test scaffolding, not a product entry point. It composes the same modules the
deployed Chat worker composes — `app.lovetree_auth_routes.lovetree_handoff_start`,
`app.auth_routes.google_callback`, `app.auth_routes.password_login`, and
`app.lovetree_auth_store.D1LoveTreeLoginHandoffStore` — over a SQLite file that the
LoveTree repository's test opens directly, so one set of rows is written by the real
producer SQL and consumed by the real relay SQL.

Three things are substituted, and all are outside the handoff chain:

* Google's token and userinfo endpoints (httpx MockTransport). The OAuth exchange, state
  signing, upsert call and bind all run as real code.
* The B62 canonical-session shadow helpers, which are the other product's outcome.
* Nothing else. The identity authority is substituted on the LoveTree side only, and is
  reported as such.

Environment: CHAIN_SQLITE_PATH, CHAIN_SESSION_SECRET, CHAIN_GOOGLE_SUBJECT,
CHAIN_GOOGLE_EMAIL, CHAIN_PASSWORD, CHAIN_PASSWORD_EMAIL, CHAIN_PROFILE_ID,
CHAIN_AUTH_MODE ("hybrid" drives the Google leg, "password" the dialog leg),
CHAIN_PUBLIC_BASE_URL.
"""

from __future__ import annotations

import json
import os
import sqlite3
import types
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs

import httpx
from starlette.requests import Request

from app import auth_routes
from app.auth import GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL, GoogleOAuthClient
from app.config import Settings
from app.lovetree_auth_routes import lovetree_handoff_start
from app.lovetree_auth_store import D1LoveTreeLoginHandoffStore
from app.password_auth import hash_password, normalize_email

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "073_lovetree_login_handoff.sql"


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if not value:
        raise RuntimeError(f"{name} is required by the chain harness")
    return value


class _SqliteD1:
    """The same D1-shaped surface the production store is built on."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def prepare(self, sql: str):
        return _SqliteStatement(self.connection, sql)


class _SqliteStatement:
    def __init__(self, connection: sqlite3.Connection, sql: str):
        self.connection = connection
        self.sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        cursor = self.connection.execute(self.sql, self.params)
        row = cursor.fetchone()
        self.connection.commit()
        return dict(row) if row is not None else None


class _Profile:
    def __init__(self, identifier: str):
        self.id = identifier

    def public_dict(self) -> dict:
        return {"id": self.id, "name": "Chain User"}


class _HistoryStore:
    """The verified-login outcomes the real routes ask for."""

    def __init__(self, *, profile_id: str, password: str, email: str) -> None:
        self.profile_id = profile_id
        self.email = normalize_email(email)
        self.password_hash = hash_password(password)
        self.google_upserts: list[tuple] = []

    async def upsert_google_user(self, subject, email, name, picture):
        self.google_upserts.append((subject, email, name, picture))
        return _Profile(self.profile_id)

    async def find_password_credential(self, identifier):
        if identifier != self.email:
            return None
        return types.SimpleNamespace(
            user=_Profile(self.profile_id),
            username=self.email,
            password_hash=self.password_hash,
            failed_attempts=0,
            locked_until=None,
        )

    async def find_password_credential_by_user_id(self, user_id):
        return None

    async def register_password_user(self, *args, **kwargs):
        raise AssertionError("not used by the chain")

    async def update_password_credential(self, *args, **kwargs):
        raise AssertionError("not used by the chain")

    async def record_password_failure(self, user_id, failures, lock_until):
        return None

    async def reset_password_failures(self, user_id):
        return None


def _google_transport(subject: str, email: str) -> httpx.MockTransport:
    """Google's two HTTP calls only. Everything above them is the real client."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == GOOGLE_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "chain-at", "token_type": "Bearer", "expires_in": 3600})
        if str(request.url) == GOOGLE_USERINFO_URL:
            return httpx.Response(
                200,
                json={"id": subject, "email": email, "verified_email": True, "name": "Chain User", "picture": ""},
            )
        raise AssertionError(f"unexpected outbound call: {request.url}")

    return httpx.MockTransport(handler)


def build():
    settings = Settings(
        runtime_mode="test",
        auth_mode=_env("CHAIN_AUTH_MODE", "hybrid"),
        public_base_url=_env("CHAIN_PUBLIC_BASE_URL", "http://127.0.0.1"),
        google_client_id="chain-client",
        google_client_secret="chain-secret",
        session_secret=_env("CHAIN_SESSION_SECRET"),
        cookie_secure=False,
    )
    connection = sqlite3.connect(_env("CHAIN_SQLITE_PATH"), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.executescript(MIGRATION.read_text(encoding="utf-8"))

    history = _HistoryStore(
        profile_id=_env("CHAIN_PROFILE_ID", "usr_chain_profile"),
        password=_env("CHAIN_PASSWORD"),
        email=_env("CHAIN_PASSWORD_EMAIL"),
    )
    store = D1LoveTreeLoginHandoffStore(_SqliteD1(connection))

    async def _noop(*_args, **_kwargs):
        return None

    auth_routes._write_identity_shadow_after_login = _noop
    auth_routes.establish_b54_canonical_session_after_google_login = _noop
    auth_routes.establish_b54_canonical_session_after_login = _noop
    auth_routes.deliver_after_signup = _noop

    state = types.SimpleNamespace(
        settings=settings,
        google_oauth=GoogleOAuthClient(settings, transport=_google_transport(_env("CHAIN_GOOGLE_SUBJECT"), history.email)),
        history_store=history,
        android_handoff_store=None,
        lovetree_handoff_store=store,
    )
    app = types.SimpleNamespace(state=state)

    async def send_json(send, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})

    async def peek(ticket: str) -> dict:
        record = await store.get(ticket)
        return {"record": asdict(record) if record else None}

    async def expire(ticket: str) -> dict:
        row = await store._first(
            "UPDATE lovetree_login_handoffs SET expires_at=? WHERE ticket_id=? RETURNING ticket_id",
            "2000-01-01T00:00:00Z", ticket,
        )
        record = await store.get(ticket)
        return {"ok": row is not None, "digest": record.state_sha256 if record else None}

    async def dispatch(scope, receive, send):
        if scope["type"] != "http":
            return
        event = await receive()
        body = event.get("body", b"")
        path = scope["path"]
        query = parse_qs(scope.get("query_string", b"").decode())
        scope = {**scope, "app": app}

        async def replay():
            return {"type": "http.request", "body": body, "more_body": False}

        if path == "/healthz":
            await send_json(send, 200, {"ok": True, "service": "lovetree-chain-harness"})
            return
        if path == "/chain/peek":
            await send_json(send, 200, await peek((query.get("ticket") or [""])[0]))
            return
        if path == "/chain/expire":
            await send_json(send, 200, await expire((query.get("ticket") or [""])[0]))
            return

        if path == "/auth/lovetree/start":
            response = await lovetree_handoff_start(Request(scope, replay))
        elif path == "/auth/google/callback":
            response = await auth_routes.google_callback(Request(scope, replay))
        elif path == "/api/auth/password/login":
            response = await auth_routes.password_login(Request(scope, replay))
        else:
            await send_json(send, 404, {"ok": False, "error": {"code": "not_found"}})
            return

        payload = getattr(response, "body", None)
        if payload is None:
            payload = b"".join([chunk async for chunk in response.iter_raw()])
        await send({"type": "http.response.start", "status": response.status_code,
                    "headers": [(key.lower(), value) for key, value in response.raw_headers]})
        await send({"type": "http.response.body", "body": payload})

    return dispatch


app = build()
