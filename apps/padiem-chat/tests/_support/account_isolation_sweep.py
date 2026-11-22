"""#8061 21차: shared setup for the account isolation sweep tests.

The thread-safe D1 handle (starlette's TestClient runs the app on a portal
thread), the all-migrations loader and the two-client app harness are what
seven test files share. The isolation contracts themselves stay with the tests
that exercise them.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from starlette.testclient import TestClient

from _support import account_selection as account_harness
from _support.account_selection import BASE, seed_db, session
from app.byok_credentials import D1CustomProviderCredentialStore
from app.history import D1HistoryStore
from app.main import create_app
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from test_5002_byok_product_e2e import FakeAuthenticatedCipher

ROOT = Path(__file__).resolve().parents[2]


class ThreadSafeStatement(account_harness.Statement):
    """5222 Statement에 `.all()`을 보강한다(회의장부 등이 사용)."""

    def bind(self, *params):
        return ThreadSafeStatement(self.db, self.sql, params)

    async def all(self):
        cursor = self.db.conn.execute(self.sql, self.params)
        return [dict(row) for row in cursor.fetchall()]


class ThreadSafeSqliteD1(account_harness.SqliteD1):
    """#5222 하네스와 같은 D1 모양이지만 두 가지만 고친다.

    1. 스레드 제한: starlette TestClient는 앱을 포털 스레드에서 돌리고, 5222의
       sqlite 연결은 생성 스레드에 묶여 있어 요청마다 `SQLite objects created
       in a thread...` 예외로 503이 났다. 운영 COM2 어댑터
       (`app/d1_sqlite.py::connect`)가 이미 그렇듯 check_same_thread=False로만
       푼다 — 제품 코드 변경은 없다.
    2. `.all()`: 회의장부 같은 D1 스토어가 쓰는 나머지 읽기 표면.
    """

    def __init__(self):
        self.conn = sqlite3.connect(":memory:", isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")

    def prepare(self, sql):
        return ThreadSafeStatement(self, sql)

    async def batch(self, statements):
        # D1 배치 응답 형태: 문장별 {"results": [...], "meta": {...}} —
        # 북AI 병합이 결과를 dict 첨자로 읽는다(5222 하네스는 SimpleNamespace).
        out = []
        for statement in statements:
            cursor = self.conn.execute(statement.sql, statement.params)
            out.append({
                "results": [dict(row) for row in cursor.fetchall()],
                "meta": {"changes": cursor.rowcount},
            })
        return out


def apply_all_migrations(db) -> None:
    for path in sorted((ROOT / "migrations").glob("*.sql")):
        db.conn.executescript(path.read_text(encoding="utf-8"))


def isolation_app(db):
    app = create_app(
        account_harness.settings(),
        d1_binding=db,
        b66_admin_google_email="admin@example.test",
        # BYOK custom credential은 WebCrypto 암호화를 쓴다 — 로컬 CPython에서는
        # 결정론 가짜 암호로만 동작한다(test_5002가 정립한 계약).
        custom_credential_store=D1CustomProviderCredentialStore(
            db,
            key_secret="c" * 48,
            session_secret="s" * 48,
            cipher=FakeAuthenticatedCipher(),
        ),
    )
    app.state.history_store = D1HistoryStore(db)
    app.state.project_file_store = D1ProjectFileStore(db)
    app.state.saved_output_store = D1SavedOutputStore(db)
    return app


def clients():
    """(app, A 클라이언트, B 클라이언트) — A=PLUS, B=FREE 회원."""
    original = account_harness.SqliteD1
    account_harness.SqliteD1 = ThreadSafeSqliteD1
    try:
        db, _admin, a, b = seed_db()
    finally:
        account_harness.SqliteD1 = original
    apply_all_migrations(db)
    app = isolation_app(db)
    client_a = TestClient(app, base_url=BASE)
    client_b = TestClient(app, base_url=BASE)
    client_a.cookies.update(session(app, a))
    client_b.cookies.update(session(app, b))
    # 브라우저와 같은 same-origin 표시(검토된 출처 = public_base_url) —
    # 회의록 같은 상태 변경 경로가 요구하는 값이다.
    client_a.headers.update({"Origin": BASE})
    client_b.headers.update({"Origin": BASE})
    return app, client_a, client_b, a, b
