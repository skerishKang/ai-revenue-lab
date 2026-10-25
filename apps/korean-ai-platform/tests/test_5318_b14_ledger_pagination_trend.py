"""#5318 read surface: walking a long history and a date-bucketed trend.

The merged ledger answers "what ran" for a page of rows. The owner console needs
two more things without a second query path: a way to walk past the first page of
a filtered range, and a trend that is computed over the *whole* filtered range
rather than over whatever happened to fit in 200 rows. Both stay inside the same
allowlist discipline: a grouping name is looked up in a constant table, never
interpolated from a query string.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pilot.call_ledger_store import (
    AGGREGATE_DIMENSIONS,
    AGGREGATE_EXPRESSIONS,
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGE_OFFSET,
    CallLedgerStore,
)


class _Statement:
    def __init__(self, recorder, sql):
        self._recorder = recorder
        self._sql = sql
        self._params = ()

    def bind(self, *params):
        self._params = params
        return self

    async def run(self):
        self._recorder.append(("run", self._sql, self._params))
        return SimpleNamespace(results=[], success=True, meta={})

    async def all(self):
        self._recorder.append(("all", self._sql, self._params))
        return {"results": []}

    async def first(self):
        self._recorder.append(("first", self._sql, self._params))
        return None


class RecordingBinding:
    """A fake D1 handle that keeps the exact SQL text and bound parameters."""

    def __init__(self):
        self.calls = []

    def prepare(self, sql):
        return _Statement(self.calls, sql)


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


@pytest.fixture()
def binding():
    return RecordingBinding()


def test_offset_is_bound_not_interpolated(binding):
    store = CallLedgerStore(binding)
    _run(store.list_calls(filters={"product": "chat"}, since="2026-10-01T00:00:00Z",
                          until="2026-10-20T00:00:00Z", limit=25, offset=75))
    kind, sql, params = binding.calls[-1]
    assert sql.endswith("LIMIT ? OFFSET ?")
    # The page values travel as parameters, after the filter and range values.
    assert params == ("chat", "2026-10-01T00:00:00Z", "2026-10-20T00:00:00Z", 25, 75)
    assert "75" not in sql and "25" not in sql


def test_the_history_order_is_stable_across_pages(binding):
    # `started_at` alone repeats inside one second, so an OFFSET walk would
    # otherwise show a row twice on one page and skip it on the next.
    store = CallLedgerStore(binding)
    _run(store.list_calls(limit=10))
    _, sql, params = binding.calls[-1]
    assert "ORDER BY started_at DESC, log_id DESC" in sql
    assert params == (10, 0)


def test_a_page_without_an_offset_stays_the_first_page(binding):
    store = CallLedgerStore(binding)
    _run(store.list_calls())
    _, sql, params = binding.calls[-1]
    assert sql.endswith("LIMIT ? OFFSET ?")
    assert params == (DEFAULT_PAGE_LIMIT, 0)


def test_day_is_a_constant_expression_not_a_column(binding):
    assert "day" in AGGREGATE_DIMENSIONS
    assert AGGREGATE_EXPRESSIONS == {"day": "substr(started_at, 1, 10)"}
    store = CallLedgerStore(binding)
    _run(store.aggregate("day", since="2026-10-01T00:00:00Z", limit=MAX_PAGE_LIMIT))
    _, sql, params = binding.calls[-1]
    assert f"SELECT {AGGREGATE_EXPRESSIONS['day']} AS dimension" in sql
    assert "GROUP BY substr(started_at, 1, 10)" in sql
    # A trend is read in time order, a ranking by weight.
    assert "ORDER BY dimension ASC LIMIT ?" in sql
    assert params == ("2026-10-01T00:00:00Z", MAX_PAGE_LIMIT)
    # The bucket counts logical requests, so a fallback still counts once.
    assert "SUM(total_tokens) AS total_tokens" in sql


def test_a_column_dimension_still_groups_by_that_column(binding):
    store = CallLedgerStore(binding)
    _run(store.aggregate("selected_provider"))
    _, sql, params = binding.calls[-1]
    assert "SELECT selected_provider AS dimension" in sql
    assert "ORDER BY calls DESC LIMIT ?" in sql
    assert params == (DEFAULT_PAGE_LIMIT,)


def test_an_unknown_dimension_never_reaches_sql(binding):
    store = CallLedgerStore(binding)
    for attempt in ("started_at", "subject_ref; DROP TABLE b14_model_call", "log_id"):
        with pytest.raises(ValueError):
            _run(store.aggregate(attempt))
    assert binding.calls == []


def test_the_page_bounds_stay_inside_the_merged_contract():
    # The merged page ceiling is unchanged; only a cursor was added.
    assert MAX_PAGE_LIMIT == 200
    assert MAX_PAGE_OFFSET == 100_000


@pytest.mark.parametrize("offset", [-1, MAX_PAGE_OFFSET + 1, 1])
def test_a_store_page_never_escapes_its_bounds(offset, binding):
    store = CallLedgerStore(binding)
    _run(store.list_calls(limit=10, offset=offset))
    _, _sql, params = binding.calls[-1]
    assert 0 <= params[-1] <= MAX_PAGE_OFFSET


def test_the_admin_surface_refuses_an_out_of_range_cursor():
    # The route layer is the one that refuses rather than clamps, so an operator
    # typo does not silently read a different page.
    from starlette.requests import Request
    from starlette.routing import Router

    if not hasattr(Router, "route"):
        # The admin module mounts itself through the Router decorator. The
        # pinned CI Starlette has it; a newer local Starlette does not, and the
        # route layer must not be approximated here.
        pytest.skip("this Starlette build cannot mount the admin router")
    from app.pilot.call_ledger_admin import CallLedgerError, _query

    def query(raw):
        return _query(Request({
            "type": "http", "http_version": "1.1", "method": "GET", "path": "/x",
            "query_string": raw.encode(), "headers": [], "scheme": "https",
            "server": ("test", 443), "client": ("127.0.0.1", 1), "root_path": "",
        }))

    with pytest.raises(CallLedgerError):
        query("offset=-5")
    with pytest.raises(CallLedgerError):
        query(f"offset={MAX_PAGE_OFFSET + 1}")
    with pytest.raises(CallLedgerError):
        query("offset=abc")
    assert query("offset=40")[4] == 40
