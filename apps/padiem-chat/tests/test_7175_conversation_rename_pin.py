"""#7175: 최근 대화 이름 변경·상단 고정 — 서버 계약.

스토어는 실제 SQLite(마이그레이션 적용) 위의 D1HistoryStore로 검사한다.
라우트는 ASGI 클라이언트로 검사하며, conftest가 same-origin 브라우저처럼
Origin을 붙인다(NO_BROWSER_ORIGIN_MARKER로 의도적 누락도 검사).

계약:
  - 제목 수정은 본인 대화만. 다른 사용자/다른 제품 대화는 404(존재 여부 미노출).
  - 제목은 공백 정리 후 1..80자. 빈 값·초과·비문자열은 거부.
  - 고정은 서버에 저장되고 목록·검색이 pinned를 돌려준다. 정렬은 고정 먼저 → 최근 순.
  - 마이그레이션 104가 없는 DB에서도 기존 조회(목록·검색·상세·삭제)는 그대로 동작하고
    pinned=false. 고정 쓰기만 503 conversation_pin_unavailable.
  - 비로그인은 401.
"""
from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.history import (
    D1HistoryStore,
    HistoryError,
    HistoryPinUnavailable,
    PRODUCT_SCOPE_B66,
    PRODUCT_SCOPE_CHAT,
)
from app.main import create_app
from test_b66_conversation_isolation_4657 import (
    D1Sqlite,
    MIGRATIONS,
    OTHER_OWNER,
    OWNER,
    setup_database,
)

SESSION_SECRET = "phase9-session-secret-not-a-real-credential-000000"


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="phase9-client.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def database(with_pin: bool) -> sqlite3.Connection:
    db = setup_database()
    if with_pin:
        db.executescript((MIGRATIONS / "104_conversation_pinned.sql").read_text(encoding="utf8"))
    return db


def store(db: sqlite3.Connection) -> D1HistoryStore:
    return D1HistoryStore(D1Sqlite(db))


async def conversation(s: D1HistoryStore, owner: str, title: str) -> str:
    return await s.append_exchange(owner, None, title, "응답", product_scope=PRODUCT_SCOPE_CHAT)


# ---------------------------------------------------------------- 스토어 계약


@pytest.mark.asyncio
async def test_rename_collapses_whitespace_and_keeps_recency():
    db = database(True)
    s = store(db)
    cid = await conversation(s, OWNER, "원래 제목")
    before = await s.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT)
    updated = await s.update_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT, title="  새   제목 ")
    assert updated is not None
    assert updated["title"] == "새 제목"
    assert updated["pinned"] is False
    after = await s.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT)
    assert after["title"] == "새 제목"
    # 이름 변경은 최근 순서를 흔들지 않는다(최근성은 메시지 활동).
    assert after["updated_at"] == before["updated_at"]
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "   ", "가" * 81, 123, None])
async def test_rename_rejects_empty_overlong_and_non_text(bad):
    db = database(True)
    s = store(db)
    cid = await conversation(s, OWNER, "원래 제목")
    with pytest.raises(HistoryError):
        await s.update_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT, title=bad)
    assert (await s.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT))["title"] == "원래 제목"
    db.close()


@pytest.mark.asyncio
async def test_pin_orders_first_then_recency_and_unpin_restores():
    db = database(True)
    s = store(db)
    older = await conversation(s, OWNER, "오래된 대화")
    newer = await conversation(s, OWNER, "최근 대화")
    # 두 행이 같은 밀리초에 생기면 정렬이 임의가 된다. 최근성을 명시적으로 준다.
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", ("2026-11-08T09:00:00Z", older))
    db.execute("UPDATE conversations SET updated_at=? WHERE id=?", ("2026-11-08T10:00:00Z", newer))
    db.commit()
    listed = await s.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT)
    assert [c["id"] for c in listed] == [newer, older]
    assert all(c["pinned"] is False for c in listed)

    pinned = await s.update_conversation(OWNER, older, product_scope=PRODUCT_SCOPE_CHAT, pinned=True)
    assert pinned["pinned"] is True
    listed = await s.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT)
    assert [c["id"] for c in listed] == [older, newer]
    assert [c["pinned"] for c in listed] == [True, False]

    searched = await s.search_conversations(OWNER, "대화", product_scope=PRODUCT_SCOPE_CHAT)
    assert [c["id"] for c in searched] == [older, newer]
    assert [c["pinned"] for c in searched] == [True, False]

    await s.update_conversation(OWNER, older, product_scope=PRODUCT_SCOPE_CHAT, pinned=False)
    listed = await s.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT)
    assert [c["id"] for c in listed] == [newer, older]
    db.close()


@pytest.mark.asyncio
async def test_pin_rejects_non_boolean():
    db = database(True)
    s = store(db)
    cid = await conversation(s, OWNER, "제목")
    with pytest.raises(HistoryError):
        await s.update_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT, pinned="yes")
    db.close()


@pytest.mark.asyncio
async def test_foreign_owner_and_foreign_product_match_no_row():
    db = database(True)
    s = store(db)
    foreign = await conversation(s, OTHER_OWNER, "남의 대화")
    b66 = await s.append_exchange(OWNER, None, "B66 대화", "응답", product_scope=PRODUCT_SCOPE_B66)
    assert await s.update_conversation(OWNER, foreign, product_scope=PRODUCT_SCOPE_CHAT, title="침범") is None
    assert await s.update_conversation(OWNER, foreign, product_scope=PRODUCT_SCOPE_CHAT, pinned=True) is None
    assert await s.update_conversation(OWNER, b66, product_scope=PRODUCT_SCOPE_CHAT, title="침범") is None
    assert (await s.get_conversation(OTHER_OWNER, foreign, product_scope=PRODUCT_SCOPE_CHAT))["title"] == "남의 대화"
    assert (await s.get_conversation(OWNER, b66, product_scope=PRODUCT_SCOPE_B66))["title"] == "B66 대화"
    db.close()


@pytest.mark.asyncio
async def test_database_without_migration_104_still_reads_and_renames():
    db = database(False)
    s = store(db)
    cid = await conversation(s, OWNER, "기존 대화")
    listed = await s.list_conversations(OWNER, product_scope=PRODUCT_SCOPE_CHAT)
    assert listed and listed[0]["pinned"] is False
    searched = await s.search_conversations(OWNER, "기존", product_scope=PRODUCT_SCOPE_CHAT)
    assert searched and searched[0]["pinned"] is False
    detail = await s.get_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT)
    assert detail is not None
    renamed = await s.update_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT, title="새 이름")
    assert renamed["title"] == "새 이름" and renamed["pinned"] is False
    with pytest.raises(HistoryPinUnavailable):
        await s.update_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT, pinned=True)
    assert await s.delete_conversation(OWNER, cid, product_scope=PRODUCT_SCOPE_CHAT) is True
    db.close()


# ---------------------------------------------------------------- 라우트 계약


@pytest.fixture()
def app_with_pin():
    db = database(True)
    s = store(db)
    app = create_app(settings(), history_store=s)
    yield app, s, db
    db.close()


async def signed_in_client(app: httpx.ASGITransport, owner: str):
    client = httpx.AsyncClient(transport=app, base_url="https://chat.example.test")
    token = create_session_token(settings(), owner)
    client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")
    return client


@pytest.mark.asyncio
async def test_patch_rename_and_pin_are_owner_scoped(app_with_pin):
    app, s, db = app_with_pin
    cid = await conversation(s, OWNER, "내 대화")
    foreign = await conversation(s, OTHER_OWNER, "남의 대화")
    async with await signed_in_client(httpx.ASGITransport(app=app), OWNER) as client:
        renamed = await client.patch(f"/api/conversations/{cid}", json={"title": "  바꾼   이름 "})
        assert renamed.status_code == 200
        assert renamed.json()["updated"] is True
        assert renamed.json()["conversation"]["title"] == "바꾼 이름"
        pinned = await client.patch(f"/api/conversations/{cid}", json={"pinned": True})
        assert pinned.status_code == 200 and pinned.json()["conversation"]["pinned"] is True
        listed = await client.get("/api/conversations")
        assert listed.json()["conversations"][0]["id"] == cid
        assert listed.json()["conversations"][0]["pinned"] is True
        unpinned = await client.patch(f"/api/conversations/{cid}", json={"pinned": False})
        assert unpinned.status_code == 200 and unpinned.json()["conversation"]["pinned"] is False
        denied = await client.patch(f"/api/conversations/{foreign}", json={"title": "침범"})
        assert denied.status_code == 404
        deleted = await client.delete(f"/api/conversations/{cid}")
        assert deleted.status_code == 200 and deleted.json()["deleted"] is True
    db.close()


@pytest.mark.asyncio
async def test_patch_requires_login_and_rejects_bad_bodies(app_with_pin):
    app, s, db = app_with_pin
    cid = await conversation(s, OWNER, "내 대화")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as guest:
        anonymous = await guest.patch(f"/api/conversations/{cid}", json={"title": "익명"})
        assert anonymous.status_code == 401
    async with await signed_in_client(httpx.ASGITransport(app=app), OWNER) as client:
        for body in ({}, {"other": 1}, {"title": ""}, {"title": "  "}, {"title": "가" * 81},
                     {"title": 5}, {"pinned": "yes"}, {"pinned": None}):
            refused = await client.patch(f"/api/conversations/{cid}", json=body)
            assert refused.status_code == 400, body
        malformed = await client.patch("/api/conversations/not-a-conversation", json={"title": "x"})
        assert malformed.status_code == 404
        missing = await client.patch("/api/conversations/chat_" + "0" * 32, json={"title": "x"})
        assert missing.status_code == 404
    db.close()


@pytest.mark.asyncio
async def test_patch_without_browser_origin_is_denied(app_with_pin):
    from conftest import NO_BROWSER_ORIGIN_MARKER

    app, s, db = app_with_pin
    cid = await conversation(s, OWNER, "내 대화")
    async with await signed_in_client(httpx.ASGITransport(app=app), OWNER) as client:
        denied = await client.patch(
            f"/api/conversations/{cid}", json={"title": "x"},
            headers={NO_BROWSER_ORIGIN_MARKER: "1"},
        )
        assert denied.status_code == 403
    db.close()


@pytest.mark.asyncio
async def test_pin_write_refuses_on_pre_104_database_but_reads_still_work():
    db = database(False)
    s = store(db)
    cid = await conversation(s, OWNER, "기존 대화")
    app = create_app(settings(), history_store=s)
    async with await signed_in_client(httpx.ASGITransport(app=app), OWNER) as client:
        listed = await client.get("/api/conversations")
        assert listed.status_code == 200
        assert listed.json()["conversations"][0]["pinned"] is False
        refused = await client.patch(f"/api/conversations/{cid}", json={"pinned": True})
        assert refused.status_code == 503
        assert refused.json()["error"]["code"] == "conversation_pin_unavailable"
        renamed = await client.patch(f"/api/conversations/{cid}", json={"title": "새 이름"})
        assert renamed.status_code == 200
    db.close()
