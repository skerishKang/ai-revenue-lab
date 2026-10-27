"""LoveTree 4.0 sign-in handoff: one-time rows, real SQL, and the relay's contract.

These tests pin the load-bearing properties of migration 073 and
``app.lovetree_auth_store``: the row is bound to one product, one recipient, and one
login request; the verified identity is written only by the login side and only once;
the claim is a single conditional UPDATE so a replayed or expired ticket can never be
advanced; and the ``lovetree-auth-caller`` relay still speaks exactly this table,
these statuses, and these pinned constants.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.lovetree_auth_store import (
    D1LoveTreeLoginHandoffStore,
    HANDOFF_STATUS_AWAITING_LOGIN,
    HANDOFF_STATUS_CLAIMED,
    HANDOFF_STATUS_READY,
    InMemoryLoveTreeLoginHandoffStore,
    LOVETREE_HANDOFF_PRODUCT_ID,
    LOVETREE_HANDOFF_RECIPIENT,
)

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "073_lovetree_login_handoff.sql"
RELAY_WORKER_PATH = MIGRATION_PATH.parents[2] / "lovetree-auth-caller" / "worker.mjs"

NOW = "2026-10-27T00:00:00Z"
LATER = "2026-10-27T00:05:00Z"
EXPIRES = "2026-10-27T00:10:00Z"
PAST = "2026-10-26T23:59:59Z"
STATE = "a" * 64
OTHER_STATE = "b" * 64
TICKET = "lovt_0123456789abcdef"


class _SqliteD1:
    """Minimal D1-shaped adapter so the migration and guards run as real SQL."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def prepare(self, sql: str) -> "_SqliteStatement":
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


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    return connection


def _d1_store() -> tuple[D1LoveTreeLoginHandoffStore, sqlite3.Connection]:
    connection = _connection()
    return D1LoveTreeLoginHandoffStore(_SqliteD1(connection)), connection


async def _ready(store, *, ticket: str = TICKET, state: str = STATE, now_iso: str = NOW) -> bool:
    await store.create(ticket_id=ticket, state_sha256=state, now_iso=now_iso, expires_at_iso=EXPIRES)
    return await store.bind_verified_identity(
        ticket,
        user_id="usr_lovetree_1",
        auth_provider="google",
        provider_subject="provider-subject-1",
        state_sha256=state,
        now_iso=now_iso,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", [
    lambda: _d1_store()[0],
    lambda: InMemoryLoveTreeLoginHandoffStore(),
])
async def test_claim_is_single_use_and_carries_only_the_verified_identity(store_factory) -> None:
    store = store_factory()
    assert await _ready(store) is True

    claimed = await store.claim(TICKET, now_iso=LATER)
    assert claimed is not None
    assert claimed.status == HANDOFF_STATUS_CLAIMED
    assert (claimed.pending_user_id, claimed.auth_provider, claimed.provider_subject) == (
        "usr_lovetree_1", "google", "provider-subject-1"
    )
    assert claimed.product_id == LOVETREE_HANDOFF_PRODUCT_ID
    assert claimed.recipient == LOVETREE_HANDOFF_RECIPIENT

    # 같은 표로 두 번 발급할 수 없다. 두 번째는 아무것도 받지 않는다.
    assert await store.claim(TICKET, now_iso=LATER) is None
    assert await store.claim("lovt_unknown", now_iso=LATER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", [
    lambda: _d1_store()[0],
    lambda: InMemoryLoveTreeLoginHandoffStore(),
])
async def test_unbound_expired_and_foreign_requests_never_reach_ready(store_factory) -> None:
    store = store_factory()

    # 로그인 요청(state)이 다른 번들에는 신원을 쓸 수 없다.
    await store.create(ticket_id=TICKET, state_sha256=STATE, now_iso=NOW, expires_at_iso=EXPIRES)
    assert await store.bind_verified_identity(
        TICKET, user_id="usr_x", auth_provider="google", provider_subject="p", state_sha256=OTHER_STATE, now_iso=NOW
    ) is False
    assert await store.claim(TICKET, now_iso=NOW) is None
    assert (await store.get(TICKET)).status == HANDOFF_STATUS_AWAITING_LOGIN

    # 검증되지 않은 번들은 발급 대상이 아니다.
    await store.create(ticket_id="lovt_unbound", state_sha256=STATE, now_iso=NOW, expires_at_iso=EXPIRES)
    assert await store.claim("lovt_unbound", now_iso=LATER) is None

    # 만료된 표는 신원을 써도 발급되지 않는다.
    await store.create(ticket_id="lovt_old", state_sha256=STATE, now_iso=PAST, expires_at_iso=NOW)
    assert await store.bind_verified_identity(
        "lovt_old", user_id="usr_x", auth_provider="google", provider_subject="p", state_sha256=STATE, now_iso=PAST
    ) is True
    assert await store.claim("lovt_old", now_iso=LATER) is None
    assert (await store.get("lovt_old")).status == HANDOFF_STATUS_READY

    # reviewed provider 밖은 신원을 쓸 수 없다.
    with pytest.raises(ValueError):
        await store.bind_verified_identity(
            TICKET, user_id="usr_x", auth_provider="email", provider_subject="p", state_sha256=STATE, now_iso=NOW
        )


def test_migration_073_guards_are_real_sql() -> None:
    connection = _connection()
    columns = {row[1] for row in connection.execute("PRAGMA table_info(lovetree_login_handoffs)")}
    assert {
        "ticket_id", "product_id", "recipient", "state_sha256", "status", "pending_user_id",
        "auth_provider", "provider_subject", "created_at", "updated_at", "expires_at"
    } <= columns

    def insert(**overrides):
        values = {
            "ticket_id": "lovt_guard",
            "product_id": LOVETREE_HANDOFF_PRODUCT_ID,
            "recipient": LOVETREE_HANDOFF_RECIPIENT,
            "state_sha256": STATE,
            "status": HANDOFF_STATUS_AWAITING_LOGIN,
            "created_at": NOW,
            "updated_at": NOW,
            "expires_at": EXPIRES,
            **overrides,
        }
        connection.execute(
            f"INSERT INTO lovetree_login_handoffs ({','.join(values)}) VALUES ({','.join('?' * len(values))})",
            tuple(values.values()),
        )

    # 다른 제품·다른 수신자·정체 없는 상태 값·신원 없는 ready는 테이블 자체가 거부한다.
    for bad in (
        {"product_id": "b62"},
        {"recipient": "someone-else"},
        {"state_sha256": "not-a-digest"},
        {"status": HANDOFF_STATUS_READY},
        {"status": "cancelled"},
    ):
        with pytest.raises(sqlite3.IntegrityError):
            insert(**bad)
        connection.rollback()

    insert()
    connection.commit()
    assert connection.execute("SELECT count(*) FROM lovetree_login_handoffs").fetchone()[0] == 1


def test_relay_and_store_agree_on_the_same_handoff() -> None:
    source = RELAY_WORKER_PATH.read_text(encoding="utf-8")
    assert LOVETREE_HANDOFF_PRODUCT_ID in source
    assert LOVETREE_HANDOFF_RECIPIENT in source
    for fragment in (
        "lovetree_login_handoffs",
        "status='ready'",
        "status='claimed'",
        "expires_at >",
        "product_id = ?",
        "recipient = ?",
        "handoff_ticket",
    ):
        assert fragment in source, fragment
