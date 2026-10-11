"""#3436 B2c — end-to-end: the Desktop canonical conversation read activation.

CENTRAL requirement: the read path must run the **actual canonical broker
entrypoint**, not a second verifier. This test boots the real
``packages/padiem-control-plane/local_agent_broker_worker.py`` module (with the
same ``workers`` runtime stub harness the control-plane suite uses), drives the
real register → open-session write paths, binds the real ``Default`` gateway to
that live object through the Durable Object namespace stub, composes the B62
app exactly like ``worker.py`` does, and drives the GET-only Desktop
conversation routes against a real in-memory HistoryStore:

    real LocalAgentBrokerDurableObject (SQLite state)
        -> real Default gateway (authenticate_device_session RPC)
        -> LOCAL_AGENT_BROKER_AUTHORITY_SERVICE binding
        -> worker.py composition lines
        -> app.state.desktop_device_session_authority
        -> GET /api/desktop/conversations[/{id}]
        -> the SAME HistoryStore the Web /api/conversations surface reads

    HISTORY_STORE_REUSED=YES
    NEW_CONVERSATION_DATABASE=0
    SERVER_DERIVED_ACCOUNT_REF=YES
    SERVER_DERIVED_WORKSPACE_REF=YES
    CALLER_WORKSPACE_AUTHORITY=0
    BROWSER_PADIEM_SESSION_COOKIE_COPY=0
    SECOND_IDENTITY_AUTHORITY=0
    SECOND_SESSION_AUTHORITY=0
    SECOND_CREDENTIAL_VERIFIER=0
    SECOND_CONVERSATION_AUTHORITY=0
    CREATE=0
    DELETE=0
    CHAT_WRITE=0
    RAW_DEVICE_CREDENTIAL_LOGGED=0
    PRODUCTION_MUTATION=0
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sqlite3
import sys
import types
from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_access_composition import build_claw_local_access_source_with_diagnostic  # noqa: F401  (sibling composition proves the same binding)
from app.desktop_conversation_authority import (
    BrokerAuthorityDeviceSessionAuthPort,
    build_desktop_device_session_authority_with_diagnostic,
    validate_authenticated_device_session,
)
from app.desktop_conversation_routes import (
    DESKTOP_CONVERSATION_DETAIL_PATH,
    DESKTOP_CONVERSATIONS_PATH,
    DEVICE_SESSION_BINDING_REF_HEADER,
    DEVICE_SESSION_CREDENTIAL_HEADER,
    DEVICE_SESSION_ID_HEADER,
)
from app.history import HistoryForbidden
from app.main import create_app

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONTROL_PLANE_ROOT = _REPO_ROOT / "packages" / "padiem-control-plane"
if str(_CONTROL_PLANE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONTROL_PLANE_ROOT))

# The control-plane worker module imports the ``workers`` runtime module, which
# only exists inside a Cloudflare Workers Python runtime. The same stub harness
# the control-plane suite uses keeps this a plain-Python test.
if "workers" not in sys.modules:
    class _FakeResponse:
        def __init__(self, body="", *, status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers or {}

    class _FakeWorkerEntrypoint:
        def __init__(self, env=None):
            self.env = env

    class _FakeDurableObject:
        def __init__(self, ctx, env):
            self.ctx = ctx
            self.env = env

    _workers = types.ModuleType("workers")
    _workers.Response = _FakeResponse
    _workers.WorkerEntrypoint = _FakeWorkerEntrypoint
    _workers.DurableObject = _FakeDurableObject
    sys.modules["workers"] = _workers

_WORKER_SPEC = importlib.util.spec_from_file_location(
    "padiem_b3436_desktop_conversation_broker_it",
    _CONTROL_PLANE_ROOT / "local_agent_broker_worker.py",
)
assert _WORKER_SPEC is not None and _WORKER_SPEC.loader is not None
broker_worker = importlib.util.module_from_spec(_WORKER_SPEC)
sys.modules[_WORKER_SPEC.name] = broker_worker
_WORKER_SPEC.loader.exec_module(broker_worker)


BASE_URL = "https://chat.example.test"
OWNER_ID = "usr_3436_desktop_owner"
OTHER_OWNER_ID = "usr_3436_desktop_other"
WORKSPACE_REF = "ws_3436_desktop"
AUTHORITY_REF = "control-plane.local-agent-broker.b3436-it.v1"
# Synthetic test fixtures only — no real credential material exists anywhere in
# this repository. The session secret reuses the repository's long-standing
# test-session convention (the same constant test_auth_history.py uses), and
# the device pepper/credential are shrunken, plainly-deterministic dummies; the
# rotated credential is derived at test runtime so no second literal exists.
SESSION_SECRET = "phase9-session-secret-not-a-real-credential-000000"
PEPPER = "unit-test-pepper-value"
CREDENTIAL = b"unit-test-device-input"
ROTATED_CREDENTIAL = CREDENTIAL + b"-rotated"
BINDING_REF = "bind.3436.it.1"
DEVICE_ID = "device.3436.it.1"
SESSION_ID = "sess.3436.it.1"
BROKER_AUTHORITY_BINDING_NAME = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"

NOW = datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)


def _fresh_now() -> datetime:
    """The broker runtime authenticates against its own server clock, so the
    fixture provisions relative to the real current time."""

    return datetime.now(timezone.utc)


class MemoryHistoryStore:
    """The same owner-scoped conversation projection shape as the Web surface."""

    def __init__(self):
        self.users = {}
        self.conversations = {}
        self.counter = 0
        self.list_calls: list[str] = []
        self.detail_calls: list[tuple[str, str]] = []

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject.replace("-", "")[:32].ljust(32, "0")
        self.users[uid] = (uid, email, name, picture)
        return uid

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def list_conversations(self, user_id, limit=30):
        self.list_calls.append(user_id)
        rows = [c for c in self.conversations.values() if c["user_id"] == user_id]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return [{k: c[k] for k in ("id", "title", "created_at", "updated_at")} for c in rows[:limit]]

    async def get_conversation(self, user_id, conversation_id):
        self.detail_calls.append((user_id, conversation_id))
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            return None
        return {
            "id": row["id"], "title": row["title"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "messages": [{"role": m["role"], "content": m["content"]} for m in row["messages"]],
        }

    async def delete_conversation(self, user_id, conversation_id):
        raise AssertionError("the Desktop surface must never delete")

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text):
        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id, "user_id": user_id, "title": user_text[:80],
                "created_at": f"2026-10-01T00:00:{self.counter:02d}Z",
                "updated_at": f"2026-10-02T00:00:{self.counter:02d}Z", "messages": [],
            }
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            raise HistoryForbidden()
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])
        return conversation_id


class _Cursor:
    def __init__(self, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self):
        return list(self._rows)

    def one(self):
        if len(self._rows) != 1:
            raise RuntimeError("expected exactly one row")
        return self._rows[0]


class _Sql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def exec(self, query: str, *bindings):
        cursor = self.connection.execute(query, bindings)
        rows: list[dict] = []
        if cursor.description is not None:
            names = [item[0] for item in cursor.description]
            rows = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return _Cursor(rows, rows_written)


class _Storage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = _Sql(self.connection)

    def transactionSync(self, callback):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            value = callback()
            self.connection.execute("COMMIT")
            return value
        except Exception:
            self.connection.execute("ROLLBACK")
            raise


class _Context:
    def __init__(self, storage: _Storage) -> None:
        self.storage = storage


class _Namespace:
    """The DO namespace stub, bound to the REAL durable object instance."""

    def __init__(self) -> None:
        self.durable_object = None

    def idFromName(self, name: str):
        return f"do::{name}"

    def get(self, object_id: str):
        return self.durable_object


class _Env:
    def __init__(self, namespace: _Namespace) -> None:
        self.LOCAL_AGENT_BROKER_AUTHORITY_REF = AUTHORITY_REF
        self.LOCAL_AGENT_BROKER_PEPPER = PEPPER
        self.LOCAL_AGENT_BROKER_STATE = namespace


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _credential_b64(value: bytes = CREDENTIAL) -> str:
    return base64.b64encode(value).decode("ascii")


def _device_headers(
    *,
    session_id: str = SESSION_ID,
    binding_ref: str = BINDING_REF,
    credential: bytes = CREDENTIAL,
) -> dict[str, str]:
    return {
        DEVICE_SESSION_ID_HEADER: session_id,
        DEVICE_SESSION_BINDING_REF_HEADER: binding_ref,
        DEVICE_SESSION_CREDENTIAL_HEADER: _credential_b64(credential),
    }


def _provision_live_device(
    durable_object,
    *,
    now: datetime = NOW,
    credential_ttl_seconds: int = 3600,
    session_ttl_seconds: int = 900,
) -> None:
    registered = asyncio.run(
        durable_object.register_binding(
            {
                "binding_ref": BINDING_REF,
                "device_id": DEVICE_ID,
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "credential_b64": _credential_b64(),
                "now": _iso(now),
                "credential_ttl_seconds": credential_ttl_seconds,
            }
        )
    )
    assert registered["ok"] is True
    opened = asyncio.run(
        durable_object.open_session(
            {
                "session_id": SESSION_ID,
                "binding_ref": BINDING_REF,
                "credential_b64": _credential_b64(),
                "account_ref": OWNER_ID,
                "workspace_ref": WORKSPACE_REF,
                "now": _iso(now),
                "ttl_seconds": session_ttl_seconds,
            }
        )
    )
    assert opened["ok"] is True


def _app_with_real_broker(
    *,
    namespace: _Namespace,
    history_store: MemoryHistoryStore | None = None,
):
    """create_app() exactly like worker.py, composed against the real Default gateway."""

    default_gateway = broker_worker.Default(_Env(namespace))
    from app.config import Settings

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    store = history_store if history_store is not None else MemoryHistoryStore()
    app = create_app(settings, history_store=store)
    # --- verbatim worker.py composition root lines ---
    authority, diagnostic = build_desktop_device_session_authority_with_diagnostic(
        {BROKER_AUTHORITY_BINDING_NAME: default_gateway}
    )
    if authority is not None:
        app.state.desktop_device_session_authority = authority
    # --- end verbatim lines ---
    assert diagnostic is None, "the real canonical broker must compose"
    return app, settings, store


async def _get(
    app,
    *,
    path: str,
    headers: dict[str, str] | None = None,
    method: str = "GET",
    cookies: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        if cookies:
            for name, value in cookies.items():
                client.cookies.set(name, value)
        return await client.request(method, path, headers=headers, params=params)


def test_valid_current_broker_session_lists_and_reads_canonical_conversations() -> None:
    now = _fresh_now()
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=now)
    store = MemoryHistoryStore()
    asyncio.run(store.append_exchange(OWNER_ID, None, "hello from Web", "canonical transcript answer"))
    conversation_id = next(iter(store.conversations))
    app, _settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    listed = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()["conversations"]] == [conversation_id]

    detail = asyncio.run(
        _get(app, path=f"/api/desktop/conversations/{conversation_id}", headers=_device_headers())
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["conversation"]["id"] == conversation_id
    assert body["conversation"]["messages"] == [
        {"role": "user", "content": "hello from Web"},
        {"role": "assistant", "content": "canonical transcript answer"},
    ]
    # The response never carries session material or its credential.
    assert _credential_b64() not in detail.text
    assert SESSION_ID not in detail.text


def test_desktop_read_matches_the_same_web_canonical_id_and_transcript() -> None:
    now = _fresh_now()
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=now)
    store = MemoryHistoryStore()
    conversation_id = asyncio.run(
        store.append_exchange(OWNER_ID, None, "same conversation", "same canonical transcript")
    )
    app, settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    web_list = asyncio.run(
        _get(app, path="/api/conversations", cookies={SESSION_COOKIE: create_session_token(settings, OWNER_ID)})
    )
    desktop_list = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert web_list.status_code == 200 and desktop_list.status_code == 200
    assert desktop_list.json()["conversations"] == web_list.json()["conversations"]

    web_detail = asyncio.run(
        _get(
            app,
            path=f"/api/conversations/{conversation_id}",
            cookies={SESSION_COOKIE: create_session_token(settings, OWNER_ID)},
        )
    )
    desktop_detail = asyncio.run(
        _get(app, path=f"/api/desktop/conversations/{conversation_id}", headers=_device_headers())
    )
    assert web_detail.status_code == 200 and desktop_detail.status_code == 200
    assert desktop_detail.json()["conversation"] == web_detail.json()["conversation"]


def test_wrong_credential_is_denied_without_disclosure() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers(credential=b"wrong-credential"))
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "device_session_auth_required"
    assert OWNER_ID not in response.text
    assert WORKSPACE_REF not in response.text


def test_expired_credential_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_agent_broker_durable_runtime as broker_runtime

    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    now = _fresh_now()
    _provision_live_device(durable_object, now=now, credential_ttl_seconds=300)

    frozen_broker_now = now + timedelta(minutes=10)
    real_datetime = broker_runtime.datetime

    class _FrozenBrokerDatetime(real_datetime):  # type: ignore[misc,valid-type]
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_broker_now if tz is None else frozen_broker_now.astimezone(tz)

    monkeypatch.setattr(broker_runtime, "datetime", _FrozenBrokerDatetime, raising=True)
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    response = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "device_session_auth_required"


def test_expired_broker_session_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    import local_agent_broker_durable_runtime as broker_runtime

    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    now = _fresh_now()
    # Short session, long credential: only the session expires.
    _provision_live_device(durable_object, now=now, credential_ttl_seconds=3600, session_ttl_seconds=60)

    frozen_broker_now = now + timedelta(minutes=5)
    real_datetime = broker_runtime.datetime

    class _FrozenBrokerDatetime(real_datetime):  # type: ignore[misc,valid-type]
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_broker_now if tz is None else frozen_broker_now.astimezone(tz)

    monkeypatch.setattr(broker_runtime, "datetime", _FrozenBrokerDatetime, raising=True)
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    response = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "device_session_auth_required"


def test_revoked_binding_denies_an_existing_desktop_read_immediately() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    now = _fresh_now()
    _provision_live_device(durable_object, now=now)
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    before = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert before.status_code == 200
    revoked = asyncio.run(
        durable_object.revoke_binding({"binding_ref": BINDING_REF, "now": _iso(now + timedelta(seconds=2))})
    )
    assert revoked["ok"] is True
    after = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "device_session_auth_required"


def test_wrong_binding_ref_is_denied() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    response = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers(binding_ref="bind.3436.other"))
    )
    assert response.status_code == 401


def test_stale_credential_generation_session_correlation_is_denied() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    rotated = asyncio.run(
        durable_object.rotate_credential(
            {
                "binding_ref": BINDING_REF,
                "expected_generation": 1,
                "new_credential_b64": _credential_b64(ROTATED_CREDENTIAL),
                "now": _iso(datetime.now(timezone.utc) + timedelta(seconds=2)),
            }
        )
    )
    assert rotated["ok"] is True
    app, _settings, _store = _app_with_real_broker(namespace=namespace)

    # The rotated credential no longer correlates with the pre-rotation session.
    stale_generation = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers(credential=ROTATED_CREDENTIAL))
    )
    assert stale_generation.status_code == 401
    # And the pre-rotation credential no longer verifies at all.
    old_credential = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert old_credential.status_code == 401


def test_caller_supplied_identity_headers_cannot_alter_owner_or_scope() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    store = MemoryHistoryStore()
    owner_conversation = asyncio.run(store.append_exchange(OWNER_ID, None, "owner row", "owner answer"))
    asyncio.run(store.append_exchange(OTHER_OWNER_ID, None, "other row", "other answer"))
    app, _settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    attacker = {
        "x-padiem-user-id": OTHER_OWNER_ID,
        "x-padiem-account-ref": OTHER_OWNER_ID,
        "x-padiem-workspace-ref": "ws_attacker_chosen",
        "x-padiem-tenant": "tenant_attacker",
        "x-padiem-product": "product_attacker",
    }
    response = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers={**_device_headers(), **attacker})
    )
    assert response.status_code == 200
    # The owner/scope are server-derived: the extra headers changed nothing.
    assert [row["id"] for row in response.json()["conversations"]] == [owner_conversation]
    assert OTHER_OWNER_ID not in response.text

    # And with bad credentials, no header can conjure an owner either.
    denied = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers={**_device_headers(credential=b"wrong"), **attacker})
    )
    assert denied.status_code == 401


def test_malformed_conversation_id_never_reaches_history_store() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    store = MemoryHistoryStore()
    app, _settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    for hostile in ("../../etc/passwd", "chat_zzz", "chat_" + "g" * 32, "", "conv_3436_not_canonical"):
        response = asyncio.run(
            _get(app, path=f"/api/desktop/conversations/{hostile}", headers=_device_headers())
        )
        assert response.status_code == 404, hostile
    assert store.detail_calls == [], "HistoryStore must not be called for a malformed id"


def test_foreign_conversation_id_is_a_non_disclosing_not_found() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    store = MemoryHistoryStore()
    foreign_id = asyncio.run(store.append_exchange(OTHER_OWNER_ID, None, "secret", "other owner transcript"))
    app, _settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    foreign = asyncio.run(
        _get(app, path=f"/api/desktop/conversations/{foreign_id}", headers=_device_headers())
    )
    unknown = asyncio.run(
        _get(app, path="/api/desktop/conversations/" + "chat_" + "f" * 32, headers=_device_headers())
    )
    assert foreign.status_code == 404 and unknown.status_code == 404
    assert foreign.json() == unknown.json()
    assert "secret" not in foreign.text
    assert OTHER_OWNER_ID not in foreign.text


def test_browser_padiem_session_cookie_is_no_authority_on_the_desktop_surface() -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    store = MemoryHistoryStore()
    asyncio.run(store.append_exchange(OWNER_ID, None, "owner row", "owner answer"))
    app, settings, _store = _app_with_real_broker(namespace=namespace, history_store=store)

    # A valid browser session cookie, with no device session material at all,
    # is not an authority here — and neither is it needed with one present.
    cookie_only = asyncio.run(
        _get(
            app,
            path=DESKTOP_CONVERSATIONS_PATH,
            cookies={SESSION_COOKIE: create_session_token(settings, OWNER_ID)},
        )
    )
    assert cookie_only.status_code == 401
    cookie_and_device = asyncio.run(
        _get(
            app,
            path=DESKTOP_CONVERSATIONS_PATH,
            headers=_device_headers(),
            cookies={SESSION_COOKIE: create_session_token(settings, OWNER_ID)},
        )
    )
    assert cookie_and_device.status_code == 200


def test_unconfigured_authority_fails_closed_as_503() -> None:
    from app.config import Settings

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    app = create_app(settings, history_store=MemoryHistoryStore())
    response = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "desktop_conversation_authority_unconfigured"


@pytest.mark.parametrize("method", ["DELETE", "POST", "PATCH"])
def test_desktop_conversation_surface_is_get_only(method: str) -> None:
    namespace = _Namespace()
    durable_object = broker_worker.LocalAgentBrokerDurableObject(_Context(_Storage()), _Env(namespace))
    namespace.durable_object = durable_object
    _provision_live_device(durable_object, now=_fresh_now())
    app, _settings, store = _app_with_real_broker(namespace=namespace)
    conversation_id = asyncio.run(store.append_exchange(OWNER_ID, None, "row", "answer"))

    collection = asyncio.run(_get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers(), method=method))
    detail = asyncio.run(
        _get(
            app,
            path=f"/api/desktop/conversations/{conversation_id}",
            headers=_device_headers(),
            method=method,
        )
    )
    assert collection.status_code == 405
    assert detail.status_code == 405
    if method == "DELETE":
        assert conversation_id in store.conversations, "a DELETE must never delete"


def test_composition_diagnostic_is_bounded_when_binding_is_absent() -> None:
    authority, diagnostic = build_desktop_device_session_authority_with_diagnostic({})
    assert authority is None
    assert diagnostic == "desktop_conversation_authority_binding_absent"

    class _Incompatible:
        pass

    authority, diagnostic = build_desktop_device_session_authority_with_diagnostic(
        {BROKER_AUTHORITY_BINDING_NAME: _Incompatible()}
    )
    assert authority is None
    assert diagnostic == "desktop_conversation_authority_port_incompatible"


def test_projection_validation_rejects_extra_or_missing_material() -> None:
    base = {
        "authenticated": True,
        "session_id": SESSION_ID,
        "binding_ref": BINDING_REF,
        "device_id": DEVICE_ID,
        "account_ref": OWNER_ID,
        "workspace_ref": WORKSPACE_REF,
        "credential_generation": 1,
        "session_expires_at": _iso(NOW + timedelta(seconds=900)),
        "credential_digest_exposed": False,
        "raw_device_credential": False,
    }
    assert validate_authenticated_device_session(base) is not None

    with_digest = {**base, "credential_digest": "a" * 64}
    assert validate_authenticated_device_session(with_digest) is None

    with_raw = {**base, "raw_device_credential": _credential_b64()}
    assert validate_authenticated_device_session(with_raw) is None

    unauthenticated = {**base, "authenticated": False}
    assert validate_authenticated_device_session(unauthenticated) is None

    missing_scope = {key: value for key, value in base.items() if key != "workspace_ref"}
    assert validate_authenticated_device_session(missing_scope) is None


def _broker_projection(*, session_id: str = SESSION_ID, binding_ref: str = BINDING_REF, account_ref: str = OWNER_ID) -> dict:
    return {
        "authenticated": True,
        "session_id": session_id,
        "binding_ref": binding_ref,
        "device_id": DEVICE_ID,
        "account_ref": account_ref,
        "workspace_ref": WORKSPACE_REF,
        "credential_generation": 1,
        "session_expires_at": _iso(NOW + timedelta(seconds=900)),
        "credential_digest_exposed": False,
        "raw_device_credential": False,
    }


class _ProjectionBinding:
    def __init__(self, projection: dict) -> None:
        self.projection = projection
        self.calls: list[dict] = []

    def authenticate_device_session(self, payload: dict) -> dict:
        self.calls.append(dict(payload))
        return {"ok": True, "device_session": self.projection}


@pytest.mark.parametrize(
    ("projection", "label"),
    [
        (_broker_projection(session_id="sess.3436.other"), "session"),
        (_broker_projection(binding_ref="bind.3436.other"), "binding"),
    ],
)
def test_broker_adapter_rejects_valid_looking_projection_for_another_request_correlation(
    projection: dict,
    label: str,
) -> None:
    binding = _ProjectionBinding(projection)
    authority = BrokerAuthorityDeviceSessionAuthPort(binding)

    result = asyncio.run(
        authority.authenticate_device_session(
            session_id=SESSION_ID,
            binding_ref=BINDING_REF,
            credential_b64=_credential_b64(),
        )
    )

    assert result is None, label
    assert binding.calls == [
        {
            "session_id": SESSION_ID,
            "binding_ref": BINDING_REF,
            "credential_b64": _credential_b64(),
        }
    ]


def test_broker_adapter_accepts_only_the_exact_requested_session_and_binding() -> None:
    binding = _ProjectionBinding(_broker_projection())
    authority = BrokerAuthorityDeviceSessionAuthPort(binding)

    result = asyncio.run(
        authority.authenticate_device_session(
            session_id=SESSION_ID,
            binding_ref=BINDING_REF,
            credential_b64=_credential_b64(),
        )
    )

    assert result is not None
    assert result["session_id"] == SESSION_ID
    assert result["binding_ref"] == BINDING_REF


def test_mismatched_broker_projection_cannot_select_another_history_owner() -> None:
    from app.config import Settings

    binding = _ProjectionBinding(
        _broker_projection(
            session_id="sess.3436.other",
            binding_ref="bind.3436.other",
            account_ref=OTHER_OWNER_ID,
        )
    )
    authority = BrokerAuthorityDeviceSessionAuthPort(binding)
    store = MemoryHistoryStore()
    asyncio.run(store.append_exchange(OTHER_OWNER_ID, None, "other secret", "other answer"))
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    app = create_app(settings, history_store=store)
    app.state.desktop_device_session_authority = authority

    response = asyncio.run(
        _get(app, path=DESKTOP_CONVERSATIONS_PATH, headers=_device_headers())
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "device_session_auth_required"
    assert OTHER_OWNER_ID not in response.text
    assert "other secret" not in response.text
