"""LoveTree 4.0 sign-in handoff: one-time rows, real SQL, and the relay's contract.

These tests pin the load-bearing properties of migration 076 and
``app.lovetree_auth_store``: the row is bound to one product, one recipient, one login
request, and one return origin; the verified identity is written only by the login side
and only once; a claim is a single conditional UPDATE that requires the *same* login
request and leaves the row untouched when the request does not match; and the
``lovetree-auth-caller`` relay still speaks exactly this table, these statuses, and these
pinned constants.
"""

from __future__ import annotations

import asyncio
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
    checked_origin,
    handoff_digest,
)

MIGRATION_PATH = Path(__file__).resolve().parents[1] / "migrations" / "076_lovetree_login_handoff.sql"
RELAY_WORKER_PATH = MIGRATION_PATH.parents[2] / "lovetree-auth-caller" / "worker.mjs"

NOW = "2026-10-27T00:00:00Z"
LATER = "2026-10-27T00:05:00Z"
EXPIRES = "2026-10-27T00:10:00Z"
PAST = "2026-10-26T23:59:59Z"
REQUEST_A = "login-request-A"
REQUEST_B = "login-request-B"
TICKET = "lovt_0123456789abcdef"
ORIGIN = "https://lovetree-4-0.pages.dev"


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


STORES = [
    pytest.param(lambda: _d1_store()[0], id="d1-sql"),
    pytest.param(InMemoryLoveTreeLoginHandoffStore, id="in-memory-oracle"),
]


async def _created(store, *, ticket: str = TICKET, request: str = REQUEST_A, now_iso: str = NOW) -> None:
    await store.create(
        ticket_id=ticket,
        login_request=request,
        return_origin=ORIGIN,
        now_iso=now_iso,
        expires_at_iso=EXPIRES if now_iso < EXPIRES else now_iso[:18] + "59Z",
    )


async def _ready(store, **kwargs) -> bool:
    request = kwargs.get("request", REQUEST_A)
    await _created(store, **kwargs, request=request)
    return await store.bind_verified_identity(
        kwargs.get("ticket", TICKET),
        user_id="usr_lovetree_1",
        auth_provider="google",
        provider_subject="provider-subject-1",
        state_sha256=handoff_digest(request),
        now_iso=kwargs.get("now_iso", NOW),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", STORES)
async def test_claim_is_single_use_and_carries_only_the_verified_identity(store_factory) -> None:
    store = store_factory()
    assert await _ready(store) is True

    claimed = await store.claim(TICKET, login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER)
    assert claimed is not None
    assert claimed.status == HANDOFF_STATUS_CLAIMED
    assert (claimed.pending_user_id, claimed.auth_provider, claimed.provider_subject) == (
        "usr_lovetree_1", "google", "provider-subject-1"
    )
    assert claimed.product_id == LOVETREE_HANDOFF_PRODUCT_ID
    assert claimed.recipient == LOVETREE_HANDOFF_RECIPIENT
    assert claimed.return_origin == ORIGIN

    assert await store.claim(TICKET, login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER) is None
    assert await store.claim("lovt_unknown", login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", STORES)
async def test_a_ticket_is_consumable_only_by_the_login_request_that_created_it(store_factory) -> None:
    store = store_factory()
    assert await _ready(store) is True

    # B의 콜백이 A의 표를 들고 와도 발급되지 않고, 표는 소비되지 않는다.
    crossed = await store.claim(TICKET, login_request_sha256=handoff_digest(REQUEST_B), now_iso=LATER)
    assert crossed is None
    record = await store.get(TICKET)
    assert record.status == HANDOFF_STATUS_READY, "거부된 클레임은 행을 소모하지 않는다"

    # A는 그대로 성공한다 — 남의 실패가 정상 요청을 방해하지 않는다.
    rightful = await store.claim(TICKET, login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER)
    assert rightful is not None and rightful.status == HANDOFF_STATUS_CLAIMED

    # 원본 값이 아니라 해시만 비교한다 — 원본을 끼워 보내면 SQL에 닿기도 전에 닫힌다.
    with pytest.raises(ValueError):
        await store.claim(TICKET, login_request_sha256=REQUEST_A, now_iso=LATER)
    assert (await store.get(TICKET)).status == HANDOFF_STATUS_CLAIMED


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", STORES)
async def test_unbound_expired_and_foreign_requests_never_reach_ready(store_factory) -> None:
    store = store_factory()

    await _created(store, request=REQUEST_A)
    # 로그인 요청(state)이 다르면 신원을 쓸 수 없다.
    assert await store.bind_verified_identity(
        TICKET, user_id="usr_x", auth_provider="google", provider_subject="p",
        state_sha256=handoff_digest(REQUEST_B), now_iso=NOW
    ) is False
    assert await store.claim(TICKET, login_request_sha256=handoff_digest(REQUEST_A), now_iso=NOW) is None
    assert (await store.get(TICKET)).status == HANDOFF_STATUS_AWAITING_LOGIN

    # 검증되지 않은 행은 발급 대상이 아니다.
    await _created(store, ticket="lovt_unbound")
    assert await store.claim("lovt_unbound", login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER) is None

    # 만료된 표는 신원을 써도 발급되지 않는다.
    await store.create(
        ticket_id="lovt_old", login_request=REQUEST_A, return_origin=ORIGIN,
        now_iso=PAST, expires_at_iso=NOW
    )
    assert await store.bind_verified_identity(
        "lovt_old", user_id="usr_x", auth_provider="google", provider_subject="p",
        state_sha256=handoff_digest(REQUEST_A), now_iso=PAST
    ) is True
    assert await store.claim("lovt_old", login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER) is None
    assert (await store.get("lovt_old")).status == HANDOFF_STATUS_READY

    # reviewed provider 밖은 신원을 쓸 수 없다.
    with pytest.raises(ValueError):
        await store.bind_verified_identity(
            TICKET, user_id="usr_x", auth_provider="email", provider_subject="p",
            state_sha256=handoff_digest(REQUEST_A), now_iso=NOW
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("store_factory", STORES)
async def test_two_logins_started_together_keep_separate_tickets(store_factory) -> None:
    store = store_factory()
    await _created(store, ticket="lovt_a", request=REQUEST_A)
    await _created(store, ticket="lovt_b", request=REQUEST_B)
    for ticket, request in (("lovt_a", REQUEST_A), ("lovt_b", REQUEST_B)):
        assert await store.bind_verified_identity(
            ticket, user_id="usr_lovetree_1", auth_provider="google", provider_subject="provider-subject-1",
            state_sha256=handoff_digest(request), now_iso=NOW
        ) is True

    raced = await asyncio.gather(
        store.claim("lovt_a", login_request_sha256=handoff_digest(REQUEST_B), now_iso=LATER),
        store.claim("lovt_b", login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER),
    )
    assert raced == [None, None], "서로 다른 요청의 표를 맞바꿔도 발급되지 않는다"

    mine = await asyncio.gather(
        store.claim("lovt_a", login_request_sha256=handoff_digest(REQUEST_A), now_iso=LATER),
        store.claim("lovt_b", login_request_sha256=handoff_digest(REQUEST_B), now_iso=LATER),
    )
    assert [record.status for record in mine] == [HANDOFF_STATUS_CLAIMED, HANDOFF_STATUS_CLAIMED]


def test_login_request_never_lands_in_the_table_as_plaintext() -> None:
    connection = _connection()
    store = D1LoveTreeLoginHandoffStore(_SqliteD1(connection))

    async def create() -> None:
        await _created(store, request="super-secret-login-request")

    asyncio.run(create())
    rows = connection.execute("SELECT state_sha256 FROM lovetree_login_handoffs").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == handoff_digest("super-secret-login-request")
    dumped = " ".join(str(value) for row in rows for value in tuple(row))
    assert "super-secret-login-request" not in dumped


def test_origin_rules_are_enforced() -> None:
    assert checked_origin(ORIGIN) == ORIGIN
    assert checked_origin("http://127.0.0.1:8788") == "http://127.0.0.1:8788"
    for bad in (
        "http://evil.example", "https://evil.example/path", "https://evil.example?next=1",
        "https://user@evil.example", "//evil.example", "https://", ORIGIN + "#frag", ""
    ):
        with pytest.raises(ValueError):
            checked_origin(bad)


def test_migration_076_guards_are_real_sql() -> None:
    connection = _connection()
    columns = {row[1] for row in connection.execute("PRAGMA table_info(lovetree_login_handoffs)")}
    assert {
        "ticket_id", "product_id", "recipient", "state_sha256", "return_origin", "status",
        "pending_user_id", "auth_provider", "provider_subject", "created_at", "updated_at",
        "bound_at", "claimed_at", "expires_at"
    } <= columns

    def insert(**overrides):
        values = {
            "ticket_id": "lovt_guard",
            "product_id": LOVETREE_HANDOFF_PRODUCT_ID,
            "recipient": LOVETREE_HANDOFF_RECIPIENT,
            "state_sha256": handoff_digest(REQUEST_A),
            "return_origin": ORIGIN,
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

    for bad in (
        {"product_id": "b62"},
        {"recipient": "someone-else"},
        {"state_sha256": "not-a-digest"},
        {"status": HANDOFF_STATUS_READY},
        {"status": "cancelled"},
        {"return_origin": "https://evil.example/steal"},
        {"return_origin": "http://evil.example"},
        {"return_origin": "https://lovetree-4-0.pages.dev?next=1"},
        {"return_origin": "ftp://lovetree-4-0.pages.dev"},
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
        "state_sha256 = ?",
        "handoff_ticket",
        "login_request_sha256",
    ):
        assert fragment in source, fragment
