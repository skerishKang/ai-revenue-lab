from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.auth_abuse import (
    AuthAbuseGate,
    D1AuthAbuseStore,
    IDENTIFIER_DAILY_FAILURE_LIMIT,
    InMemoryAuthAbuseStore,
)
from app.config import Settings


SESSION_SECRET = "auth-abuse-test-session-secret-not-real-credential-000001"
FIXED_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret=SESSION_SECRET,
    )


class RecordingStore:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def consume(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.result


def test_gate_persists_only_opaque_identifier_and_network_keys() -> None:
    store = RecordingStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    decision = asyncio.run(
        gate.authorize_failure_accounting(
            identifier="owner@example.test",
            raw_ip="203.0.113.42",
        )
    )

    assert decision.allow_failure_accounting is True
    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["identifier_key"].startswith("aab_identifier_")
    assert call["network_key"].startswith("aab_network_")
    rendered = repr(call)
    assert "owner@example.test" not in rendered
    assert "203.0.113.42" not in rendered
    assert SESSION_SECRET not in rendered


def test_identifier_daily_limit_suppresses_repeated_failure_accounting() -> None:
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    decisions = [
        asyncio.run(
            gate.authorize_failure_accounting(
                identifier="owner.test",
                raw_ip="203.0.113.42",
            )
        )
        for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT + 2)
    ]

    assert all(
        item.allow_failure_accounting
        for item in decisions[:IDENTIFIER_DAILY_FAILURE_LIMIT]
    )
    assert all(
        not item.allow_failure_accounting
        for item in decisions[IDENTIFIER_DAILY_FAILURE_LIMIT:]
    )


def test_daily_window_resets_without_clearing_authentication_state() -> None:
    current = [FIXED_NOW]
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: current[0])

    for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT):
        assert asyncio.run(
            gate.authorize_failure_accounting(
                identifier="owner.test",
                raw_ip="203.0.113.42",
            )
        ).allow_failure_accounting

    assert not asyncio.run(
        gate.authorize_failure_accounting(
            identifier="owner.test",
            raw_ip="203.0.113.42",
        )
    ).allow_failure_accounting

    current[0] = FIXED_NOW + timedelta(days=1)
    assert asyncio.run(
        gate.authorize_failure_accounting(
            identifier="owner.test",
            raw_ip="203.0.113.42",
        )
    ).allow_failure_accounting


def test_missing_store_fails_closed_for_failure_accounting() -> None:
    gate = AuthAbuseGate(_settings(), None, clock=lambda: FIXED_NOW)
    decision = asyncio.run(
        gate.authorize_failure_accounting(
            identifier="owner.test",
            raw_ip="203.0.113.42",
        )
    )
    assert decision.allow_failure_accounting is False
    assert decision.reason == "authority_unavailable"


class FakeStatement:
    def __init__(self, db: "FakeD1", sql: str) -> None:
        self.db = db
        self.sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def run(self):
        if self.sql.startswith(
            "DELETE FROM auth_login_abuse_buckets WHERE updated_at < ?"
        ):
            self.db.cleanup_calls += 1
            return
        raise AssertionError(f"unexpected standalone SQL: {self.sql[:80]}")


class FakeD1:
    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, str], int] = {}
        self.batch_calls = 0
        self.cleanup_calls = 0

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)

    async def batch(self, statements: list[FakeStatement]) -> list[dict]:
        self.batch_calls += 1
        prev_changes = 0
        results: list[dict] = []
        for stmt in statements:
            assert stmt.sql.startswith("INSERT INTO auth_login_abuse_buckets")
            subject_type, subject_key, bucket_start, _updated_at, limit = stmt.params
            chained = "SELECT ?, ?, ?, 1, ?" in stmt.sql
            rows: list[dict] = []
            changes = 0
            if not chained or prev_changes > 0:
                key = (subject_type, subject_key, bucket_start)
                current = self.counts.get(key, 0)
                if current < limit:
                    current += 1
                    self.counts[key] = current
                    rows = [{"failure_count": current}]
                    changes = 1
            prev_changes = changes
            results.append({"results": rows})
        return results


def test_d1_store_guards_identifier_counter_and_bounds_row_creation() -> None:
    db = FakeD1()
    store = D1AuthAbuseStore(db)
    kwargs = dict(
        identifier_key="aab_identifier_deadbeef",
        network_key="aab_network_deadbeef",
        day_bucket="2026-10-04T00:00:00Z",
        identifier_limit=2,
        network_limit=10,
        global_limit=100,
        updated_at="2026-10-04T12:00:00Z",
    )

    assert asyncio.run(store.consume(**kwargs)) is True
    assert asyncio.run(store.consume(**kwargs)) is True
    assert asyncio.run(store.consume(**kwargs)) is False
    assert db.counts[
        ("identifier", "aab_identifier_deadbeef", "2026-10-04T00:00:00Z")
    ] == 2
    assert db.batch_calls == 3
    assert db.cleanup_calls == 3


def test_source_contract_keeps_auth_abuse_separate_from_ai_usage_gate() -> None:
    root = Path(__file__).resolve().parents[1]
    abuse_source = (root / "app" / "auth_abuse.py").read_text(encoding="utf-8")
    auth_source = (root / "app" / "auth_routes.py").read_text(encoding="utf-8")
    factory_source = (root / "app" / "app_factory.py").read_text(encoding="utf-8")
    worker_source = (root / "worker.py").read_text(encoding="utf-8")
    migration = (root / "migrations" / "024_auth_login_abuse.sql").read_text(
        encoding="utf-8"
    )

    assert "from .usage_gate import" not in abuse_source
    assert "import usage_gate" not in abuse_source
    assert "usage_gate" not in auth_source
    assert "D1AuthAbuseStore(d1_binding)" in factory_source
    assert "d1_binding=db_binding" in worker_source
    assert "AUTH_ABUSE" not in worker_source
    assert "auth_login_abuse_buckets" in migration
    schema_sql = "\n".join(
        line for line in migration.splitlines()
        if not line.lstrip().startswith("--")
    ).lower()
    for forbidden in ("username", "email", "ip_address", "raw_ip", "password_hash"):
        assert forbidden not in schema_sql
