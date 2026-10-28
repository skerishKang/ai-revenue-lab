"""#5997 — a live claim is renewed, so a long command keeps its own result.

The 2026-10-28 production evidence: a PC command ran 379,943 ms, and because the
one-minute lease ran out meanwhile the lane re-delivered the work to a poll with a new
nonce; the first executor's submission then carried the old nonce, was refused on every
retry, and was quarantined. The fix is renewal, and these tests drive the real
`D1HistoryStore` SQL against the real committed schema with a frozen clock:

* a ten-minute command that renews stays held and its (old) nonce still submits;
* an executor that stops renewing is re-delivered by the same lease as before;
* a stale nonce after a re-claim is still refused — renewal does not widen anything.
"""
from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

import app.history as history_module
from app.history import D1HistoryStore, ORACLE_MESH_CLAIM_LEASE_SECONDS
from test_4139_mesh_original import _dispatch_kwargs, fixture

OWNER = "usr_owner_4139"
RUN = "chat_pcq_" + "a" * 32
START = datetime(2026, 10, 28, 5, 0, 0, tzinfo=timezone.utc)


class _Clock:
    """A frozen `datetime` the store reads for every now() it takes."""

    instant = START

    @classmethod
    def now(cls, tz=None):
        return cls.instant if tz is None else cls.instant.astimezone(tz)

    def __class_getitem__(cls, item):  # pragma: no cover - typing only
        return cls

    def __getattr__(self, name):  # pragma: no cover - only now() is used
        raise AttributeError(name)


class _FrozenDatetime(datetime):
    pass


@pytest.fixture
def clock(monkeypatch):
    class Frozen(_FrozenDatetime):
        instant = START

        @classmethod
        def now(cls, tz=None):
            return cls.instant if tz is None else cls.instant.astimezone(tz)

    monkeypatch.setattr(history_module, "datetime", Frozen)
    return Frozen


def _nonce(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _stage(store) -> str:
    tail = RUN[-4:]
    asyncio.run(store.record_claw_run(
        user_id=OWNER, run_id=RUN, channel="web", action="pc_files_query",
        title="PC 파일: 견적", status="pending", conversation_id="chat_" + "c" * 32,
        workspace_id="ws-1",
    ))
    row = asyncio.run(store.create_oracle_mesh_dispatch(**_dispatch_kwargs(
        run_id=RUN, user_id=OWNER, command_text="Get-ChildItem -Recurse",
        tool_call_ref="call-" + tail, tool_request_ref="call-" + tail,
        request_id="r-" + tail, revision_ref="rev-" + tail,
    )))
    return row["dispatch_id"]


def _claim(store, dispatch_id, presented):
    return asyncio.run(store.claim_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(presented)))


def _renew(store, dispatch_id, presented):
    return asyncio.run(store.renew_oracle_mesh_claim(
        dispatch_id=dispatch_id, nonce_sha256=_nonce(presented)))


def _yielded(store):
    row = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    return None if row is None else row["dispatch_id"]


def test_a_ten_minute_command_keeps_its_claim_through_renewal(tmp_path, clock):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _stage(store)
    assert _claim(store, dispatch_id, "first") is True

    # The executor renews every third of the lease; the command runs ten minutes.
    for step in range(1, 31):
        clock.instant = START + timedelta(seconds=20 * step)
        assert _renew(store, dispatch_id, "first") is not None
        assert _yielded(store) is None, step

    clock.instant = START + timedelta(minutes=10, seconds=5)
    consumed = asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="first"))
    assert consumed is not None and consumed["claim"] == "first"


def test_an_executor_that_stops_renewing_is_re_delivered(tmp_path, clock):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _stage(store)
    assert _claim(store, dispatch_id, "first") is True

    clock.instant = START + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS + 1)
    assert _yielded(store) == dispatch_id
    # Once the lane has handed it to a new round, the old executor cannot renew its
    # way back in: the nonce it names is no longer the one the row carries.
    assert _claim(store, dispatch_id, "second") is True
    assert _renew(store, dispatch_id, "first") is None
    assert _renew(store, dispatch_id, "second") is not None


def test_a_stale_nonce_submission_is_still_refused_after_a_reclaim(tmp_path, clock):
    store, _bucket = fixture(tmp_path)
    dispatch_id = _stage(store)
    assert _claim(store, dispatch_id, "first") is True

    clock.instant = START + timedelta(seconds=ORACLE_MESH_CLAIM_LEASE_SECONDS + 1)
    assert _claim(store, dispatch_id, "second") is True
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="first")) is None
    assert asyncio.run(store.consume_oracle_mesh_dispatch(
        dispatch_id=dispatch_id, nonce="second")) is not None
