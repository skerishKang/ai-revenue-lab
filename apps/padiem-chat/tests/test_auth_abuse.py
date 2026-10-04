from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.auth_abuse import (
    AuthAbuseGate,
    D1AuthAbuseStore,
    GLOBAL_DAILY_FAILURE_LIMIT,
    IDENTIFIER_DAILY_FAILURE_LIMIT,
    NETWORK_DAILY_FAILURE_LIMIT,
    UNAVAILABLE_WINDOW,
    InMemoryAuthAbuseStore,
)
from app.config import Settings


SESSION_SECRET = "auth-abuse-test-session-secret-not-real-credential-000001"
FIXED_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
DAY = "2026-10-04T00:00:00Z"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret=SESSION_SECRET,
    )


class RecordingStore:
    def __init__(self, result=None) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def record_failure(self, **kwargs):
        self.calls.append(dict(kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        if self.result is not None:
            return self.result
        return UNAVAILABLE_WINDOW


def test_gate_persists_only_opaque_identifier_and_network_keys() -> None:
    store = RecordingStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    window = asyncio.run(
        gate.record_failure_window(
            identifier="owner@example.test",
            raw_ip="203.0.113.42",
        )
    )

    assert isinstance(window.identifier_failures, int)
    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["identifier_key"].startswith("aab_identifier_")
    assert call["network_key"].startswith("aab_network_")
    rendered = repr(call)
    assert "owner@example.test" not in rendered
    assert "203.0.113.42" not in rendered
    assert SESSION_SECRET not in rendered


def test_identifier_window_keeps_metering_past_its_budget() -> None:
    # The identifier scope is a rate meter, not a switch. It must keep counting
    # after the daily budget is spent, otherwise the lock escalation floor can
    # never rise and a frozen count would silently hand the attacker the base
    # window back.
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    counts = [
        asyncio.run(
            gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
        ).identifier_failures
        for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT + 5)
    ]

    assert counts == list(range(1, IDENTIFIER_DAILY_FAILURE_LIMIT + 6))


def test_identifier_admission_flag_flips_only_at_the_budget() -> None:
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    windows = [
        asyncio.run(
            gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
        )
        for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT + 1)
    ]

    assert all(item.identifier_admitted for item in windows[:IDENTIFIER_DAILY_FAILURE_LIMIT])
    assert windows[IDENTIFIER_DAILY_FAILURE_LIMIT].identifier_admitted is False
    assert windows[IDENTIFIER_DAILY_FAILURE_LIMIT].reason == "identifier_budget_spent"


def test_network_saturation_does_not_reach_unrelated_identifiers() -> None:
    # Regression: saturating the network scope must not stop a different
    # identifier's own accounting. Under the previous chained design this
    # returned False before the identifier take ever ran, which silently
    # disabled brute-force protection for unrelated accounts.
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    for _ in range(NETWORK_DAILY_FAILURE_LIMIT + 5):
        asyncio.run(
            gate.record_failure_window(identifier="spray.test", raw_ip="203.0.113.42")
        )

    bystander = [
        asyncio.run(
            gate.record_failure_window(identifier="bystander.test", raw_ip="203.0.113.42")
        )
        for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT)
    ]

    assert [item.identifier_failures for item in bystander] == [1, 2, 3, 4, 5]
    assert all(item.identifier_admitted for item in bystander)


def test_global_saturation_does_not_reach_identifier_accounting() -> None:
    # Regression: a global budget must never become a global fail-open. Even
    # with the global scope spent, per-identifier counting continues.
    store = InMemoryAuthAbuseStore()
    store.counts[("global", "global", DAY)] = GLOBAL_DAILY_FAILURE_LIMIT
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)

    windows = [
        asyncio.run(
            gate.record_failure_window(identifier=f"subject-{index}.test", raw_ip=None)
        )
        for index in range(3)
    ]

    assert [item.identifier_failures for item in windows] == [1, 1, 1]
    assert all(item.identifier_admitted for item in windows)
    assert all(item.global_admitted is False for item in windows)


def test_advisory_scopes_never_drive_identifier_outcome() -> None:
    # Structural guarantee: identifier state is identical whether or not the
    # advisory network/global scopes are admitted. A zero limit forces both
    # advisory scopes to refuse from the first attempt.
    def run(network_limit: int, global_limit: int) -> list[int]:
        store = InMemoryAuthAbuseStore()
        gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)
        original = gate.store.record_failure

        async def scoped(**kwargs):
            kwargs["network_limit"] = network_limit
            kwargs["global_limit"] = global_limit
            return await original(**kwargs)

        gate.store.record_failure = scoped
        return [
            asyncio.run(
                gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
            ).identifier_failures
            for _ in range(4)
        ]

    assert run(0, 0) == run(1, 1) == [1, 2, 3, 4]


def test_daily_window_resets_without_clearing_authentication_state() -> None:
    current = [FIXED_NOW]
    store = InMemoryAuthAbuseStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: current[0])

    for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT + 3):
        asyncio.run(
            gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
        )

    # A spent day must recover: the escalation floor returns to base.
    current[0] = FIXED_NOW + timedelta(days=1)
    window = asyncio.run(
        gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
    )
    assert window.identifier_failures == 1
    assert window.identifier_admitted is True


def test_missing_store_degrades_to_base_window_not_a_disabled_gate() -> None:
    # Regression: a missing dedicated store must leave the caller's base lock
    # policy in force. Returning a window the caller cannot read would let an
    # outage silently change throttle strength.
    gate = AuthAbuseGate(_settings(), None, clock=lambda: FIXED_NOW)
    window = asyncio.run(
        gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
    )
    assert window is UNAVAILABLE_WINDOW
    assert window.reason == "authority_unavailable"
    assert window.identifier_failures == 0


def test_store_outage_degrades_to_base_window() -> None:
    gate = AuthAbuseGate(
        _settings(),
        RecordingStore(result=RuntimeError("simulated outage")),
        clock=lambda: FIXED_NOW,
    )
    window = asyncio.run(
        gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
    )
    assert window is UNAVAILABLE_WINDOW
    assert window.identifier_failures == 0


def test_unknown_source_ip_is_keyed_as_one_shared_network() -> None:
    store = RecordingStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)
    asyncio.run(gate.record_failure_window(identifier="owner.test", raw_ip=None))
    asyncio.run(gate.record_failure_window(identifier="other.test", raw_ip="not-an-ip"))
    assert store.calls[0]["network_key"] == store.calls[1]["network_key"]


def test_network_keys_are_domain_separated_per_address() -> None:
    store = RecordingStore()
    gate = AuthAbuseGate(_settings(), store, clock=lambda: FIXED_NOW)
    asyncio.run(
        gate.record_failure_window(identifier="owner.test", raw_ip="203.0.113.42")
    )
    asyncio.run(
        gate.record_failure_window(identifier="owner.test", raw_ip="198.51.100.7")
    )
    assert store.calls[0]["network_key"] != store.calls[1]["network_key"]


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
    """Model of the durable store that records what the batch actually did.

    Mirrors real SQLite: a `WHERE failure_count < ?` guard on the upsert makes
    the statement a no-op once the budget is spent, an unguarded upsert always
    increments, and a `WHERE (SELECT changes()) > 0` guard makes a statement a
    no-op when the previous statement in the same batch changed no row.
    """

    def __init__(self) -> None:
        self.counts: dict[tuple[str, str, str], int] = {}
        self.batch_calls = 0
        self.cleanup_calls = 0
        self.seen_sql: list[str] = []

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)

    async def batch(self, statements: list[FakeStatement]) -> list[dict]:
        self.batch_calls += 1
        results: list[dict] = []
        previous_changes = 0
        for stmt in statements:
            assert stmt.sql.startswith("INSERT INTO auth_login_abuse_buckets")
            self.seen_sql.append(stmt.sql)
            subject_type, subject_key, bucket_start, *rest = stmt.params
            limited = "failure_count < ?" in stmt.sql
            chained = "(SELECT changes()) > 0" in stmt.sql
            key = (subject_type, subject_key, bucket_start)
            current = self.counts.get(key, 0)
            rows: list[dict] = []
            if chained and previous_changes == 0:
                results.append({"results": rows})
                continue
            if limited:
                assert len(rest) == 2, "a guarded take must bind its limit"
                if current >= rest[1]:
                    results.append({"results": rows})
                    continue
            else:
                assert len(rest) == 1, "the identifier meter must not bind a limit"
            current += 1
            self.counts[key] = current
            previous_changes = 1
            rows = [{"failure_count": current}]
            results.append({"results": rows})
        return results


def _kwargs(identifier_limit: int = 2, network_limit: int = 10, global_limit: int = 100):
    return dict(
        identifier_key="aab_identifier_deadbeef",
        network_key="aab_network_deadbeef",
        day_bucket=DAY,
        identifier_limit=identifier_limit,
        network_limit=network_limit,
        global_limit=global_limit,
        updated_at="2026-10-04T12:00:00Z",
    )


def test_d1_store_meters_identifier_past_its_budget_and_reports_it() -> None:
    db = FakeD1()
    store = D1AuthAbuseStore(db)

    assert asyncio.run(store.record_failure(**_kwargs())).identifier_failures == 1
    assert asyncio.run(store.record_failure(**_kwargs())).identifier_failures == 2
    # Past the budget the meter keeps rising while admission reports False, so
    # the caller's escalation floor can still see the real spend.
    spent = asyncio.run(store.record_failure(**_kwargs(identifier_limit=2)))
    assert spent.identifier_failures == 3
    assert spent.identifier_admitted is False
    assert spent.reason == "identifier_budget_spent"
    later = asyncio.run(store.record_failure(**_kwargs(identifier_limit=2)))
    assert later.identifier_failures == 4
    assert db.counts[("identifier", "aab_identifier_deadbeef", DAY)] == 4
    assert db.batch_calls == 4
    assert db.cleanup_calls == 4


def test_d1_statements_are_never_chained_to_each_other() -> None:
    # Regression (D1 atomicity): a chained take lets one saturated scope skip
    # a later scope's row entirely. That is what turned a single attacker into
    # a global brute-force fail-open. No statement may read a previous
    # statement's row count.
    db = FakeD1()
    store = D1AuthAbuseStore(db)
    asyncio.run(store.record_failure(**_kwargs()))

    assert db.seen_sql, "expected at least one INSERT statement"
    for sql in db.seen_sql:
        assert "changes()" not in sql
        assert "SELECT ?, ?, ?, 1, ?" not in sql


def test_d1_network_saturation_does_not_stop_identifier_metering() -> None:
    db = FakeD1()
    store = D1AuthAbuseStore(db)
    saturated = _kwargs(identifier_limit=2, network_limit=1)
    for _ in range(4):
        window = asyncio.run(store.record_failure(**saturated))

    assert window.network_admitted is False
    assert window.identifier_failures == 4
    assert db.counts[("identifier", "aab_identifier_deadbeef", DAY)] == 4


def test_d1_global_saturation_does_not_stop_identifier_metering() -> None:
    db = FakeD1()
    store = D1AuthAbuseStore(db)
    spent = _kwargs(identifier_limit=2, network_limit=10, global_limit=1)
    for _ in range(4):
        window = asyncio.run(store.record_failure(**spent))

    assert window.global_admitted is False
    assert window.identifier_failures == 4
    assert db.counts[("global", "global", DAY)] == 1


def test_d1_distinct_identifiers_have_independent_counters() -> None:
    db = FakeD1()
    store = D1AuthAbuseStore(db)
    for index in range(3):
        kwargs = _kwargs()
        kwargs["identifier_key"] = f"aab_identifier_{index}"
        window = asyncio.run(store.record_failure(**kwargs))
        assert window.identifier_failures == 1

    exhausted = _kwargs()
    exhausted["identifier_key"] = "aab_identifier_0"
    for _ in range(4):
        asyncio.run(store.record_failure(**exhausted))

    other = _kwargs()
    other["identifier_key"] = "aab_identifier_1"
    assert asyncio.run(store.record_failure(**other)).identifier_failures == 2


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


def test_login_never_suppresses_failure_accounting() -> None:
    # Load-bearing source contract for the blocker itself: the previous design
    # gated record_password_failure() on an allow_failure_accounting decision.
    root = Path(__file__).resolve().parents[1]
    auth_source = (root / "app" / "auth_routes.py").read_text(encoding="utf-8")
    assert "allow_failure_accounting" not in auth_source
    assert "authorize_failure_accounting" not in auth_source
    # ...and the failure record itself is unconditional for a real, unlocked
    # credential, so no gate outcome can remove brute-force protection.
    body = auth_source.split("async def password_login", 1)[1]
    guarded = body.split("if credential is not None and not locked:", 1)[1]
    assert "await store.record_password_failure(" in guarded.split(
        "return _auth_error", 1
    )[0]