"""#8061 18차: shared setup for the email recovery / password find tests."""
from __future__ import annotations

import asyncio
import json
import secrets
import sqlite3
from pathlib import Path

from _support.migrated_db_template import migrated_connection

import httpx

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.history import D1HistoryStore
from app.main import create_app
from app.password_auth import PasswordAuthError, validate_password
from test_password_rpc_261106 import proof_headers

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://chat.example.test"
# 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
SECRET = secrets.token_urlsafe(32)
EMAIL = "returning@example.test"
ACCOUNT = "sub_existing_account_7606"
EPOCH = "2026-10-01T10:00:00+00:00"
SOURCE = "a" * 64
PREFIX = "/internal/password-recovery/"


def fixture_password(identifier: str = EMAIL) -> str:
    # 비밀번호는 실행 때 만든다 — 길이·제어문자·아이디 미포함 규칙을 지키며 비밀값처럼 보이는 글자를 남기지 않는다.
    while True:
        candidate = "pw-" + secrets.token_urlsafe(24)
        try:
            return validate_password(candidate, identifier=identifier)
        except PasswordAuthError:
            continue


PASSWORD = fixture_password()


class Mail:
    def __init__(self):
        self.messages = []
        self.result = True

    async def send(self, **message):
        self.messages.append(message)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def token(self):
        return self.messages[-1]["text"].split("#token=", 1)[1].split()[0]


def build(*, enabled=True, before_recovery_migration=False):
    connection = migrated_connection(
        ":memory:", ROOT / "migrations", isolation_level=None,
        check_same_thread=False, row_factory=sqlite3.Row,
        exclude_prefixes=("114_",) if before_recovery_migration else (),
    )
    db = SqliteD1(connection)
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        # 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
        session_secret=secrets.token_urlsafe(32),
        password_rpc_secret=SECRET,
    )
    # Also works against the pre-change Settings, making the baseline failure
    # the missing real route rather than an unknown constructor argument.
    object.__setattr__(settings, "email_recovery_enabled", enabled)
    delivery = Mail()
    app = create_app(settings=settings, d1_binding=db, history_store=D1HistoryStore(db),
                     password_reset_delivery=delivery)
    return app, db, delivery


async def send(app, action, payload, *, secret=SECRET, headers=None):
    path = PREFIX + action
    body = json.dumps(payload, separators=(",", ":")).encode()
    signed = proof_headers(secret, path, body) if headers is None else headers
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        return await client.post(path, content=body, headers=signed)


def rpc(app, action, payload, **kwargs):
    return asyncio.run(send(app, action, payload, **kwargs))


def issue(app, *, email=EMAIL, source=SOURCE, account=ACCOUNT, epoch=EPOCH):
    return rpc(app, "request", {"email": email, "source_digest": source,
        "account_id": account, "credential_epoch": epoch})


def complete(app, token, *, password=PASSWORD, account=ACCOUNT, epoch=EPOCH):
    return rpc(app, "complete", {"token": token, "new_password": password,
        "account_id": account, "credential_epoch": epoch})


