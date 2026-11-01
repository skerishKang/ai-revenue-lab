"""perf/model-choices-roster-261102: the roster window must not block a load.

Measured on the claw-perf temp instance (261102):
/api/claw/verified-model-choices was ~10.8 ms warm, but every 30 s roster
expiry made the first request pay two serial B14 catalog GETs -- 1.2~1.5 s.
These tests pin the fix: the two reads go out together; an expired-but-recent
roster is served as-is while exactly one background task revalidates it; a
failed revalidation keeps the last good rows and is recorded; past the stale
ceiling the requester waits for a fresh read again.
"""
from __future__ import annotations

import asyncio
import json
import time

import pytest

from app import owner_model_preview_routes as models
from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from test_b66_b14_free_first_resolver import records

_MODELS_PATH = "/api/pilot/models"
_READINESS_PATH = "/api/pilot/provider-readiness"


class _TimedTransport:
    def __init__(self, registry, readiness, delay=0.10):
        self.registry = registry
        self.readiness = readiness
        self.delay = delay
        self.spans: list[tuple[str, float, float]] = []

    async def get_json(self, path):
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        self.spans.append((path, start, time.monotonic()))
        if path == _MODELS_PATH:
            return 200, json.dumps(self.registry).encode("utf-8")
        if path == _READINESS_PATH:
            return 200, json.dumps(self.readiness).encode("utf-8")
        raise AssertionError("unknown path")


def test_the_two_catalog_reads_go_out_together():
    registry, readiness = records()
    fake = _TimedTransport(registry, readiness, delay=0.10)
    started = time.monotonic()
    rows = asyncio.run(
        B14FreeFirstQuoteModelResolver(fake).list_selectable_models())
    elapsed = time.monotonic() - started
    assert rows, "the fixture registry must still yield the ready route"
    assert [span[0] for span in fake.spans] == [_MODELS_PATH, _READINESS_PATH]
    # Serial reads would need ~2*delay plus overhead; overlapping halves it.
    assert elapsed < 0.17
    models_end = fake.spans[0][2]
    readiness_start = fake.spans[1][1]
    assert readiness_start < models_end, (
        "readiness must start before models finishes")


class _Roster:
    def __init__(self, *, delay=0.01, rows=None, fail_after=None):
        self.delay = delay
        self.rows = rows if rows is not None else [
            {"model_id": "provider/one", "name": "One"}]
        self.fail_after = fail_after
        self.calls = 0

    async def list_selectable_models(self):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("simulated B14 outage")
        await asyncio.sleep(self.delay)
        return [dict(row) for row in self.rows]


def _rows(name):
    return [{"model_id": "provider/one", "name": name}]


def test_expired_entry_is_served_stale_then_refreshed_in_background(
        monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0.05")
    models.clear_roster_cache()
    roster = _Roster(delay=0.08)
    fn = roster.list_selectable_models

    async def scenario():
        first = await models._model_roster(fn)
        assert roster.calls == 1
        await asyncio.sleep(0.07)  # window expired, far inside the ceiling
        started = time.monotonic()
        stale = await models._model_roster(fn)
        served_in_ms = time.monotonic() - started
        assert stale == first, "an expired-but-recent entry is served as-is"
        assert served_in_ms < 0.04, "the read must not wait on the 0.08 s fetch"
        await asyncio.sleep(0.005)  # let the background task take its first step
        assert roster.calls == 2, "the read scheduled one background revalidation"
        # The refresh is in flight; a newer admin change lands through it.
        roster.rows = _rows("Two")
        await models._ROSTER_REFRESH[id(roster)][1]
        fresh = await models._model_roster(fn)
        assert fresh == (("provider/one", "Two"),)
        assert roster.calls == 2, "the refreshed window is served without a new read"

    asyncio.run(scenario())


def test_concurrent_expired_reads_refresh_only_once(monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0.05")
    models.clear_roster_cache()
    roster = _Roster(delay=0.08)
    fn = roster.list_selectable_models

    async def scenario():
        initial = await models._model_roster(fn)
        await asyncio.sleep(0.07)
        results = await asyncio.gather(
            *(models._model_roster(fn) for _ in range(5)))
        assert all(rows == initial for rows in results)
        await asyncio.sleep(0.005)  # the shared refresh has taken its first step
        assert roster.calls == 2, "five expired reads must share one refresh"
        await models._ROSTER_REFRESH[id(roster)][1]
        assert roster.calls == 2

    asyncio.run(scenario())


def test_failed_refresh_keeps_last_good_rows_and_is_recorded(
        monkeypatch, capsys):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0.05")
    models.clear_roster_cache()
    roster = _Roster(delay=0.02, rows=_rows("One"), fail_after=1)
    fn = roster.list_selectable_models

    async def scenario():
        initial = await models._model_roster(fn)
        await asyncio.sleep(0.07)
        stale = await models._model_roster(fn)
        assert stale == initial
        await models._ROSTER_REFRESH[id(roster)][1]  # swallowed, not raised
        assert roster.calls == 2, "the outage was attempted once"
        entry = models._ROSTER_CACHE[id(roster)]
        assert entry[1] == initial, "the failed refresh never overwrote the cache"
        # Inside the ceiling, expired reads keep serving the last good rows.
        again = await models._model_roster(fn)
        assert again == initial

    asyncio.run(scenario())
    logged = capsys.readouterr().out
    assert "ROSTER_REFRESH_FAILED" in logged
    assert "_Roster" in logged and "RuntimeError" in logged
    assert "simulated B14 outage" not in logged, "failure detail is not logged"


def test_past_the_stale_ceiling_the_read_blocks_again(monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0.05")
    monkeypatch.setattr(models, "_ROSTER_MAX_STALE_SECONDS", 0.02)
    models.clear_roster_cache()
    roster = _Roster(delay=0.08, rows=_rows("One"))
    fn = roster.list_selectable_models

    async def scenario():
        await models._model_roster(fn)
        roster.rows = _rows("Two")
        await asyncio.sleep(0.07)  # expired and past the stale ceiling
        started = time.monotonic()
        rows = await models._model_roster(fn)
        waited = time.monotonic() - started
        assert rows == (("provider/one", "Two"),)
        assert waited >= 0.06, "beyond the ceiling the caller waits for fresh"
        assert roster.calls == 2

    asyncio.run(scenario())


def test_ttl_off_never_caches_and_never_goes_stale(monkeypatch):
    monkeypatch.setenv(models.ROSTER_CACHE_TTL_ENV, "0")
    models.clear_roster_cache()
    roster = _Roster(delay=0.01)
    fn = roster.list_selectable_models

    async def scenario():
        for _ in range(2):
            assert await models._model_roster(fn) == (("provider/one", "One"),)
        assert roster.calls == 2
        assert id(roster) not in models._ROSTER_CACHE

    asyncio.run(scenario())
