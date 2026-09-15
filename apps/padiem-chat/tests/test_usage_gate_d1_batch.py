from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.usage_gate import (
    D1UsageCounterStore,
    InMemoryUsageCounterStore,
    UsageDecision,
    UsageGate,
)

FIXED_NOW = datetime(2026, 8, 26, 1, 2, 3, tzinfo=timezone.utc)
QUOTA_SALT = "b62-unit-test-quota-salt-not-a-real-secret-0001"


class FakeStatement:
    def __init__(self, db: "FakeD1", sql: str):
        self.db = db
        self.sql = sql
        self.params: tuple = ()

    def bind(self, *params):
        self.params = params
        return self

    async def first(self):
        raise AssertionError("consume path must not use per-statement first() round trips")

    async def run(self):
        self.db._run_single(self)


class FakeD1:
    """In-memory D1 double that models the changes()-chained batch semantics
    proven for #2543 V2 in the local D1-compatible runtime."""

    def __init__(self):
        self.counts: dict[tuple[str, str, str, str], int] = {}
        self.updated: dict[tuple[str, str, str, str], str] = {}
        self.round_trips = 0
        self.batch_calls = 0
        self.batch_statements: list[list[tuple[str, tuple]]] = []
        self.refund_order: list[tuple[str, str, str, str]] = []
        self.batch_fail_at: int | None = None
        self.refund_raises_at: set[int] = set()
        self.cleanup_raises = False
        self._refund_calls = 0

    def prepare(self, sql: str) -> FakeStatement:
        return FakeStatement(self, sql)

    async def batch(self, statements: list[FakeStatement]) -> list[dict]:
        self.round_trips += 1
        self.batch_calls += 1
        self.batch_statements.append([(stmt.sql, stmt.params) for stmt in statements])
        staged: dict[tuple[str, str, str, str], int] = {}

        def current(key) -> int:
            return staged.get(key, self.counts.get(key, 0))

        prev_changes = 0
        results: list[dict] = []
        for index, stmt in enumerate(statements):
            if self.batch_fail_at == index:
                raise RuntimeError(f"injected batch failure at statement {index}")
            sql = stmt.sql
            if not sql.startswith("INSERT INTO live_usage_buckets"):
                raise AssertionError(f"unexpected batch statement: {sql[:60]}")
            stype, skey, btype, bstart, updated_at, limit = stmt.params
            key = (stype, skey, btype, bstart)
            guarded = "SELECT ?, ?, ?, ?, 1, ?" in sql
            changes = 0
            rows: list[dict] = []
            if not (guarded and prev_changes <= 0):
                value = current(key)
                if value < limit:
                    staged[key] = value + 1
                    self.updated[key] = updated_at
                    rows = [{"request_count": value + 1}]
                    changes = 1
            prev_changes = changes
            results.append({"results": rows})
        self.counts.update(staged)
        return results

    def _run_single(self, stmt: FakeStatement) -> None:
        self.round_trips += 1
        sql = stmt.sql
        if sql.startswith("UPDATE live_usage_buckets SET request_count=request_count - 1"):
            updated_at, stype, skey, btype, bstart = stmt.params
            key = (stype, skey, btype, bstart)
            self.refund_order.append(key)
            if self._refund_calls in self.refund_raises_at:
                self._refund_calls += 1
                raise RuntimeError("injected refund failure")
            self._refund_calls += 1
            value = self.counts.get(key, 0)
            if value > 0:
                self.counts[key] = value - 1
                self.updated[key] = updated_at
            return
        if sql.startswith("DELETE FROM live_usage_buckets WHERE updated_at < ?"):
            if self.cleanup_raises:
                raise RuntimeError("injected cleanup failure")
            cutoff = stmt.params[0]
            for key in list(self.counts):
                if self.updated.get(key, "") < cutoff:
                    del self.counts[key]
                    self.updated.pop(key, None)
            return
        raise AssertionError(f"unexpected standalone statement: {sql[:60]}")

    def statement_run(self, stmt: FakeStatement):
        return self._run_single(stmt)


def _consume_args(**overrides):
    values = {
        "subject_type": "user",
        "subject_key": "usr_0123456789abcdef0123456789abcdef",
        "minute_bucket": "2026-08-26T01:02:00Z",
        "day_bucket": "2026-08-26T00:00:00Z",
        "burst_limit": 4,
        "daily_limit": 20,
        "global_daily_limit": 1000,
        "updated_at": "2026-08-26T01:02:03Z",
    }
    values.update(overrides)
    return values


def _positive(counts: dict) -> dict:
    return {key: value for key, value in counts.items() if value > 0}


def _decision_tuple(decision: UsageDecision):
    return (
        decision.allowed,
        decision.code,
        decision.status_code,
        decision.user_message,
        decision.subject_type,
        decision.bucket_type,
        decision.count,
        decision.limit,
        decision.retry_after_seconds,
    )


async def _run_scenario(store, scenario):
    decisions = []
    for request in scenario:
        decisions.append(await store.consume(**_consume_args(**request)))
    return decisions


SCENARIOS: dict[str, list[dict]] = {
    "all_allow": [{}, {}, {}],
    "minute_boundary": [
        {"burst_limit": 2},
        {"burst_limit": 2},
        {"burst_limit": 2},
    ],
    "day_boundary": [
        {"daily_limit": 2},
        {"daily_limit": 2},
        {"daily_limit": 2},
    ],
    "global_boundary": [
        {"global_daily_limit": 1},
        {"global_daily_limit": 1},
    ],
    "mixed": [
        {"burst_limit": 3, "daily_limit": 2, "global_daily_limit": 10},
        {"burst_limit": 3, "daily_limit": 2, "global_daily_limit": 10},
        {"burst_limit": 1, "daily_limit": 5, "global_daily_limit": 10},
        {"burst_limit": 3, "daily_limit": 2, "global_daily_limit": 1},
        {"burst_limit": 3, "daily_limit": 2, "global_daily_limit": 1},
    ],
    "two_subjects": [
        {"subject_key": "usr_0123456789abcdef0123456789aaaa"},
        {"subject_key": "usr_0123456789abcdef0123456789bbbb"},
        {"subject_key": "usr_0123456789abcdef0123456789aaaa", "daily_limit": 1},
        {"subject_key": "usr_0123456789abcdef0123456789bbbb", "daily_limit": 1},
    ],
}


@pytest.mark.parametrize("scenario_name", sorted(SCENARIOS))
async def test_batch_store_matches_in_memory_oracle(scenario_name):
    scenario = SCENARIOS[scenario_name]
    oracle = InMemoryUsageCounterStore()
    d1 = D1UsageCounterStore(FakeD1())

    oracle_decisions = await _run_scenario(oracle, scenario)
    d1_decisions = await _run_scenario(d1, scenario)

    assert [_decision_tuple(d) for d in d1_decisions] == [_decision_tuple(d) for d in oracle_decisions]
    assert _positive(d1.db.counts) == _positive(oracle.counts)


async def test_allow_uses_exactly_two_round_trips():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    decision = await store.consume(**_consume_args())
    assert decision.allowed is True
    assert db.round_trips == 2  # one batch + one best-effort cleanup
    assert db.batch_calls == 1


async def test_minute_deny_uses_exactly_one_round_trip():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(burst_limit=1))
    db.round_trips = 0
    decision = await store.consume(**_consume_args(burst_limit=1))
    assert decision.allowed is False
    assert decision.code == "rate_limited"
    assert db.round_trips == 1  # batch only: nothing acquired, no refund, no cleanup
    assert db.refund_order == []


async def test_day_deny_uses_exactly_two_round_trips_and_refunds_minute():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(daily_limit=1))
    db.round_trips = 0
    decision = await store.consume(**_consume_args(daily_limit=1))
    assert decision.allowed is False
    assert decision.code == "quota_exhausted"
    assert db.round_trips == 2  # batch + one sequential refund
    assert db.refund_order == [("user", "usr_0123456789abcdef0123456789abcdef", "minute", "2026-08-26T01:02:00Z")]


async def test_global_deny_uses_exactly_three_round_trips_and_refunds_in_reverse():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(global_daily_limit=1))
    db.round_trips = 0
    decision = await store.consume(**_consume_args(global_daily_limit=1))
    assert decision.allowed is False
    assert decision.code == "service_limit_reached"
    assert db.round_trips == 3  # batch + two sequential refunds
    subject_key = "usr_0123456789abcdef0123456789abcdef"
    assert db.refund_order == [
        ("user", subject_key, "day", "2026-08-26T00:00:00Z"),
        ("user", subject_key, "minute", "2026-08-26T01:02:00Z"),
    ]


async def test_exact_limit_boundary_semantics():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    args = _consume_args(burst_limit=2, daily_limit=3, global_daily_limit=5)
    assert (await store.consume(**args)).allowed is True
    assert (await store.consume(**args)).allowed is True
    denied = await store.consume(**args)
    assert denied.allowed is False
    assert denied.code == "rate_limited"
    assert denied.limit == 2
    assert denied.retry_after_seconds == 60
    # denied take left no residue beyond the refunded state
    assert db.counts[("user", args["subject_key"], "minute", args["minute_bucket"])] == 2
    assert db.counts[("user", args["subject_key"], "day", args["day_bucket"])] == 2
    assert db.counts[("global", "global", "global_day", args["day_bucket"])] == 2


async def test_cold_start_absent_rows_are_created_by_batch():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    decision = await store.consume(**_consume_args())
    assert decision.allowed is True
    assert decision.count == 1
    assert _positive(db.counts) == {
        ("user", "usr_0123456789abcdef0123456789abcdef", "minute", "2026-08-26T01:02:00Z"): 1,
        ("user", "usr_0123456789abcdef0123456789abcdef", "day", "2026-08-26T00:00:00Z"): 1,
        ("global", "global", "global_day", "2026-08-26T00:00:00Z"): 1,
    }


async def test_denied_minute_creates_no_phantom_day_or_global_rows():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    subject_key = "usr_0123456789abcdef0123456789abcdef"
    # cold start: only the minute row exists, already pinned at its limit
    db.counts[("user", subject_key, "minute", "2026-08-26T01:02:00Z")] = 1
    db.updated[("user", subject_key, "minute", "2026-08-26T01:02:00Z")] = "2026-08-26T01:02:03Z"
    decision = await store.consume(**_consume_args(burst_limit=1))
    assert decision.allowed is False
    assert decision.code == "rate_limited"
    assert ("user", subject_key, "day", "2026-08-26T00:00:00Z") not in db.counts
    assert ("global", "global", "global_day", "2026-08-26T00:00:00Z") not in db.counts


async def test_intermediate_day_noop_chains_to_global_noop():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(daily_limit=1))
    db.counts[("global", "global", "global_day", "2026-08-26T00:00:00Z")] = 0
    decision = await store.consume(**_consume_args(daily_limit=1))
    assert decision.allowed is False
    assert decision.code == "quota_exhausted"
    # day denied inside the batch -> global take must be a no-op inside the same batch
    assert db.counts[("global", "global", "global_day", "2026-08-26T00:00:00Z")] == 0
    assert db.counts[("user", "usr_0123456789abcdef0123456789abcdef", "minute", "2026-08-26T01:02:00Z")] == 1


async def test_injected_statement_failure_rolls_back_whole_batch():
    db = FakeD1()
    db.batch_fail_at = 2
    store = D1UsageCounterStore(db)
    with pytest.raises(RuntimeError):
        await store.consume(**_consume_args())
    assert db.counts == {}


async def test_statement_failure_surfaces_as_fail_closed_503_via_gate():
    db = FakeD1()
    db.batch_fail_at = 1
    gate = UsageGate(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            quota_salt=QUOTA_SALT,
            anonymous_burst_limit=4,
            anonymous_daily_limit=20,
            user_burst_limit=8,
            user_daily_limit=100,
            global_daily_limit=1000,
        ),
        D1UsageCounterStore(db),
        clock=lambda: FIXED_NOW,
    )
    decision = await gate.authorize(raw_ip=None, user_id="usr_0123456789abcdef0123456789abcdef")
    assert decision.allowed is False
    assert decision.code == "live_abuse_gate_unavailable"
    assert decision.status_code == 503
    assert db.counts == {}


async def test_concurrent_limit_one_requests_yield_exactly_one_winner():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    args = _consume_args(burst_limit=1)
    decisions = await asyncio.gather(store.consume(**args), store.consume(**args))
    allowed = [decision.allowed for decision in decisions]
    assert allowed == [True, False] or allowed == [False, True]
    subject_key = args["subject_key"]
    assert db.counts[("user", subject_key, "minute", args["minute_bucket"])] == 1
    assert db.counts[("user", subject_key, "day", args["day_bucket"])] == 1
    assert db.counts[("global", "global", "global_day", args["day_bucket"])] == 1


async def test_cleanup_failure_does_not_flip_allowed_request():
    db = FakeD1()
    db.cleanup_raises = True
    store = D1UsageCounterStore(db)
    decision = await store.consume(**_consume_args())
    assert decision.allowed is True
    assert db.batch_calls == 1


async def test_refund_partial_failure_still_refunds_remaining_prefix():
    db = FakeD1()
    db.refund_raises_at = {0}  # first refund (global deny path: day) fails
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(global_daily_limit=1))
    db.round_trips = 0
    decision = await store.consume(**_consume_args(global_daily_limit=1))
    assert decision.allowed is False
    assert decision.code == "service_limit_reached"
    subject_key = "usr_0123456789abcdef0123456789abcdef"
    assert db.refund_order == [
        ("user", subject_key, "day", "2026-08-26T00:00:00Z"),
        ("user", subject_key, "minute", "2026-08-26T01:02:00Z"),
    ]
    # failed refund is conservative over-counting: day stays incremented,
    # the surviving minute refund still applies
    assert db.counts[("user", subject_key, "day", "2026-08-26T00:00:00Z")] == 2
    assert db.counts[("user", subject_key, "minute", "2026-08-26T01:02:00Z")] == 1


async def test_subject_isolation_between_user_anonymous_and_global():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    assert (await store.consume(**_consume_args(subject_type="user", subject_key="usr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"))).allowed
    assert (await store.consume(**_consume_args(subject_type="anonymous", subject_key="anon_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"))).allowed
    assert db.counts[("global", "global", "global_day", "2026-08-26T00:00:00Z")] == 2


async def test_raw_ip_never_reaches_d1_store_keys():
    db = FakeD1()
    gate = UsageGate(
        Settings.from_values(
            runtime_mode="b14",
            b14_base_url="https://b14.example",
            quota_salt=QUOTA_SALT,
            anonymous_burst_limit=4,
            anonymous_daily_limit=20,
            user_burst_limit=8,
            user_daily_limit=100,
            global_daily_limit=1000,
        ),
        D1UsageCounterStore(db),
        clock=lambda: FIXED_NOW,
    )
    raw_ip = "203.0.113.10"
    decision = await gate.authorize(raw_ip=raw_ip, user_id=None)
    assert decision.allowed is True
    joined = " ".join(str(part) for key in db.counts for part in key)
    joined += " " + " ".join(str(param) for stmts in db.batch_statements for _sql, params in stmts for param in params)
    assert raw_ip not in joined
    assert any(key[0] == "anonymous" and key[1].startswith("anon_") for key in db.counts)


async def test_bind_parameters_never_contain_raw_ip():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args(subject_type="anonymous", subject_key="anon_" + "a" * 64))
    for sql, params in db.batch_statements[-1]:
        assert "203.0.113" not in sql
        assert "203.0.113" not in " ".join(str(param) for param in params)


async def test_batch_contains_exactly_three_take_statements():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    await store.consume(**_consume_args())
    statements = [sql for sql, _params in db.batch_statements[0]]
    assert len(statements) == 3
    assert "VALUES" in statements[0]
    assert statements[0].count("(SELECT changes())") == 0
    assert "SELECT ?, ?, ?, ?, 1, ?" in statements[1]
    assert "SELECT ?, ?, ?, ?, 1, ?" in statements[2]
    assert statements[1].count("(SELECT changes())") == 2
    assert statements[2].count("(SELECT changes())") == 2
    joined = " ".join(statements)
    assert "updated_at=excluded.updated_at" in joined
    assert "request_count=live_usage_buckets.request_count + 1" in joined


async def test_quota_policy_fields_unchanged_on_denials():
    db = FakeD1()
    store = D1UsageCounterStore(db)
    minute = None
    day = None
    glob = None
    await store.consume(**_consume_args(burst_limit=1))
    minute = await store.consume(**_consume_args(burst_limit=1))
    await store.consume(**_consume_args(daily_limit=1))
    day = await store.consume(**_consume_args(daily_limit=1))
    await store.consume(**_consume_args(global_daily_limit=1))
    glob = await store.consume(**_consume_args(global_daily_limit=1))

    assert (minute.code, minute.status_code, minute.retry_after_seconds) == ("rate_limited", 429, 60)
    assert (day.code, day.status_code, day.retry_after_seconds) == ("quota_exhausted", 429, None)
    assert (glob.code, glob.status_code, glob.retry_after_seconds) == ("service_limit_reached", 429, None)
    assert minute.user_message == "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요."
    assert day.user_message == "오늘 사용할 수 있는 AI 요청 한도에 도달했습니다."
    assert glob.user_message == "오늘의 서비스 사용 한도에 도달했습니다. 다음에 다시 이용해 주세요."
    assert (minute.bucket_type, minute.limit) == ("minute", 1)
    assert (day.bucket_type, day.limit) == ("day", 1)
    assert (glob.bucket_type, glob.limit) == ("global_day", 1)
