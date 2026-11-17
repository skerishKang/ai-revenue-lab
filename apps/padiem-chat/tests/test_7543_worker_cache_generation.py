"""#7543 5단계 — 워커별 캐시의 무효화 신호를 프로세스 사이에서 공유한다.

네 캐시는 지금처럼 각 워커의 메모리에 있고, 무효화 신호만 SQLite 의
``worker_cache_generation`` 표(범위 이름 → 정수 번호)로 공유한다. 이 파일은 그
약속을 네 캐시 각각에 대해 **실제 별도 프로세스**로 고정한다:

* A 프로세스가 무효화하면 B 프로세스의 **다음 조회**가 캐시를 버리고 원본을 다시
  부른다(``tests/fixtures/worker_cache_generation_7543.py`` 를 두 번 띄운다).
* 프로세스 하나일 때는 적중·무효화 결과가 지금과 같다(무효화하지 않은 다른 사용자의
  항목은 계속 적중한다).
* 표가 없으면(마이그레이션 121 미적용) 지금 동작이 그대로다 — 캐시를 버리지도,
  예외를 올리지도 않는다.
* 번호는 요청당 한 번만 읽는다.

시각은 고정하지 않는다: 이 캐시들의 만료는 단조 시계이고, 표에 쓰는 갱신 시각은
사람이 읽는 값일 뿐 판정에 쓰이지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import chat_connector_tools as tools
from app import control_plane_identity_worker as identity_worker
from app import pc_scope_cache
from app import worker_cache_generation as generation
from app.auth_validation_cache import drop_cached_owner_scope_of, invalidate_auth_cache
from app.control_plane_identity_worker import (
    CloudflareControlPlaneIdentityAuthority,
    _product_user_cache,
    _product_user_cache_invalidate,
)
from app.d1_sqlite import SqliteD1, connect
from app.identity_call_cache import CachedIdentityAuthority
from app.local_cpython import apply_migrations

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MIGRATION = "121_worker_cache_generation.sql"
FIXTURE = Path(__file__).parent / "fixtures" / "worker_cache_generation_7543.py"

OWNER = "usr_" + "1" * 32
OTHER_OWNER = "usr_" + "2" * 32
SESSION = "authsession:b62:worker-generation"
WORKSPACE = "tenant_" + "3" * 32
SUBJECT = "sub_worker_generation"
PRODUCT = "b62"
PRODUCT_USER = "puser_worker_generation"


def _database(tmp_path: Path, *, with_table: bool = True) -> Path:
    """The host's startup path: every shipped migration, in order."""

    path = tmp_path / "chat.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        apply_migrations(connection, MIGRATIONS)
        if not with_table:
            connection.execute("DROP TABLE worker_cache_generation")
    finally:
        connection.close()
    return path


def _store(path: Path):
    connection = connect(str(path))
    return connection, generation.D1WorkerCacheGenerationStore(
        SqliteD1(connection, threaded=True)
    )


def _numbers(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return {
            scope: number for scope, number in connection.execute(
                "SELECT scope, generation FROM worker_cache_generation"
            )
        }
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def _clean_process_caches():
    """Every test starts as a process that has cached nothing."""

    pc_scope_cache.clear_scope_cache()
    _product_user_cache.clear()
    tools._GRANT_CACHE.clear()
    generation.reset_default_store()
    identity_worker._generation_store[0] = None
    generation._LAST_KNOWN.clear()
    generation._PENDING.clear()
    yield
    pc_scope_cache.clear_scope_cache()
    _product_user_cache.clear()
    tools._GRANT_CACHE.clear()
    generation.reset_default_store()
    identity_worker._generation_store[0] = None
    generation._LAST_KNOWN.clear()
    generation._PENDING.clear()


# ---------------------------------------------------------------------------
# Two real processes over one database file
# ---------------------------------------------------------------------------


class Process:
    """One worker process of the two-process check, started from the fixture."""

    def __init__(self, work: Path, database: Path, cache: str, script: str, tag: str):
        self._ready = work / f"ready-{tag}"
        self._process = subprocess.Popen(
            [sys.executable, str(FIXTURE), str(database), cache, script,
             str(self._ready), str(work)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
        )
        self._tag = tag

    def wait_ready(self) -> "Process":
        deadline = time.monotonic() + 60
        while not self._ready.exists():
            if time.monotonic() > deadline or self._process.poll() is not None:
                raise AssertionError(f"worker {self._tag} did not start")
            time.sleep(0.005)
        return self

    def result(self) -> dict:
        out, err = self._process.communicate(timeout=120)
        assert self._process.returncode == 0, err[-2000:]
        return json.loads(out.strip().splitlines()[-1])

    def calls(self) -> list[int]:
        """The source-read counts of the read steps only."""
        return [step["calls"] for step in self.result()["steps"]
                if step["step"] in {"prime", "read"}]


def _wait_for(path: Path, *, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {path.name}")
        time.sleep(0.005)


def _two_processes(database: Path, work: Path, cache: str) -> list[int]:
    """B primes and keeps its cache warm; A invalidates; B's next read re-reads.

    B is one process that stays up across A's invalidation — that is what a
    second worker with a warm cache is. Returns B's source-read counts.
    """

    primed = work / f"{cache}-b-primed"
    invalidated = work / f"{cache}-a-invalidated"
    b = Process(work, database, cache,
                f"prime,mark:{primed.name},wait:{invalidated.name},read",
                f"{cache}-b").wait_ready()
    _wait_for(primed)
    # A is a second process: it runs its invalidation function and exits.
    a = Process(work, database, cache, f"invalidate,mark:{invalidated.name}",
                f"{cache}-a").wait_ready()
    a.result()
    return b.calls()


def _control_without_invalidation(database: Path, work: Path, cache: str) -> list[int]:
    """The same warm B, released without any invalidation: the cache answers."""

    primed = work / f"{cache}-c-primed"
    go = work / f"{cache}-c-go"
    b = Process(work, database, cache,
                f"prime,mark:{primed.name},wait:{go.name},read",
                f"{cache}-c").wait_ready()
    _wait_for(primed)
    go.touch()
    return b.calls()


def test_identity_call_cache_drops_on_another_processes_invalidation(tmp_path):
    """S02: the identity authority answers (session and PC owner scope answers)."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _control_without_invalidation(database, work, "identity") == [1, 0]
    assert _two_processes(database, work, "identity") == [1, 1]


def test_identity_owner_scope_answer_drops_on_another_processes_invalidation(tmp_path):
    """S02: the PC owner-scope half of the same cache (pairing, disconnect)."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _control_without_invalidation(database, work, "owner_scope") == [1, 0]
    assert _two_processes(database, work, "owner_scope") == [1, 1]


def test_pc_scope_cache_drops_on_another_processes_invalidation(tmp_path):
    """S05: the Claw PC connector scope window."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _control_without_invalidation(database, work, "pc_scope") == [1, 0]
    assert _two_processes(database, work, "pc_scope") == [1, 1]


def test_connector_tool_grant_drops_on_another_processes_invalidation(tmp_path):
    """S06: the per-user connector tool grant decision."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _control_without_invalidation(database, work, "grant") == [1, 0]
    assert _two_processes(database, work, "grant") == [1, 1]


def test_subject_mapping_drops_on_another_processes_invalidation(tmp_path):
    """S10: the subject→account mapping of the identity Worker adapter."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _control_without_invalidation(database, work, "subject") == [1, 0]
    assert _two_processes(database, work, "subject") == [1, 1]


def test_a_bumped_number_alone_drops_the_next_read(tmp_path):
    """The signal is the number: another worker's bump discards the entry."""

    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    b = Process(work, database, "pc_scope", "prime,bumpall,read", "bump").wait_ready()
    # The second read is a miss because the number moved, not because the
    # process started cold: the same process answers the first read from memory.
    assert b.calls() == [1, 1]
    fetch = Process(work, database, "pc_scope", "prime,read", "bumpless").wait_ready()
    assert fetch.calls() == [1, 0]


# ---------------------------------------------------------------------------
# Restamp must not resurrect another worker's invalidation (defect 1)
# ---------------------------------------------------------------------------


def _restamp_resurrection_calls(database: Path, work: Path, cache: str) -> list[int]:
    """A primes U2, B invalidates U2, A invalidates U1, A reads U2 again.

    A stays up across B's invalidation, exactly like a second worker with a
    warm cache. A's own invalidation of a different user must not restamp
    A's U2 entry to the new number: A's next U2 read must re-read the source.
    """

    primed = work / f"{cache}-a-primed"
    invalidated = work / f"{cache}-b-invalidated"
    a = Process(
        work, database, cache,
        f"prime,mark:{primed.name},wait:{invalidated.name},invalidate_other,read",
        f"{cache}-a-restamp",
    ).wait_ready()
    _wait_for(primed)
    b = Process(
        work, database, cache,
        f"wait:{primed.name},invalidate,mark:{invalidated.name}",
        f"{cache}-b-restamp",
    ).wait_ready()
    b.result()
    return a.calls()


def test_restamp_does_not_resurrect_another_workers_invalidation_identity(tmp_path):
    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _restamp_resurrection_calls(database, work, "identity") == [1, 1]
    assert _numbers(database)["identity_auth_session"] == 2


def test_restamp_does_not_resurrect_another_workers_invalidation_pc_scope(tmp_path):
    database = _database(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert _restamp_resurrection_calls(database, work, "pc_scope") == [1, 1]
    assert _numbers(database)["pc_connector_scope"] == 2


# ---------------------------------------------------------------------------
# An entry stored without a number is dropped when a number appears (defect 2)
# ---------------------------------------------------------------------------


def test_entry_without_generation_is_dropped_when_number_appears_identity(tmp_path):
    from app.identity_call_cache import _hash_key

    database = _database(tmp_path)
    connection, store = _store(database)
    inner = CountingIdentity()
    try:
        wrapped = CachedIdentityAuthority(inner, generation_store=store)
        key = "authsession:" + PRODUCT + ":" + _hash_key(OWNER)
        wrapped._entries[key] = (
            time.monotonic() + 60, SimpleNamespace(session_id="stale"), OWNER, None)

        async def scenario() -> None:
            # Another process bumps the scope after the entry was stored.
            await store.bump(generation.IDENTITY_AUTH_SESSION)
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OWNER)

        asyncio.run(scenario())
        assert inner.session_calls == 1
    finally:
        connection.close()


def test_entry_without_generation_is_dropped_when_number_appears_grant(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    calls: list[str] = []
    truth_decision = tools.ConnectorToolGrant(
        reason=tools.GRANT_REASON_GRANTED, drive=True, calendar=False)

    async def truth(*_args, **_kwargs):
        calls.append("truth")
        return truth_decision

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        worker_cache_generation=store)))
    try:
        tools._GRANT_CACHE[OWNER] = (
            time.monotonic(),
            tools.ConnectorToolGrant(
                reason=tools.GRANT_REASON_GRANTED, drive=False, calendar=False),
            None,
        )

        async def scenario() -> None:
            await store.bump(generation.CONNECTOR_TOOL_GRANT)
            original = tools._grant_decision_for_uid
            tools._grant_decision_for_uid = truth
            try:
                decision, _elapsed, _timed_out = await tools._bounded_grant_decision(
                    request, uid=OWNER)
            finally:
                tools._grant_decision_for_uid = original
            assert decision is truth_decision

        asyncio.run(scenario())
        assert calls == ["truth"]
    finally:
        connection.close()


def test_entry_without_generation_is_dropped_when_number_appears_subject(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)

    class Binding:
        calls = 0

        async def resolve_product_user_for_subject(self, payload):
            Binding.calls += 1
            return {"ok": True, "product_user_id": PRODUCT_USER}

    authority = CloudflareControlPlaneIdentityAuthority(Binding())
    generation.set_default_store(store)
    generation._LAST_KNOWN.clear()
    _product_user_cache[(PRODUCT, SUBJECT)] = (
        time.monotonic(), PRODUCT_USER, None)
    try:
        async def scenario() -> None:
            await store.bump(generation.IDENTITY_SUBJECT_MAPPING)
            assert await authority.resolve_product_user_for_subject(
                product_id=PRODUCT, canonical_subject_id=SUBJECT) == PRODUCT_USER

        asyncio.run(scenario())
        assert Binding.calls == 1
    finally:
        connection.close()


def test_entry_without_generation_is_dropped_when_number_appears_pc_scope(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    state = SimpleNamespace(worker_cache_generation=store)
    authority = SimpleNamespace()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return SimpleNamespace(ready=True)

    key = (id(state), id(authority), pc_scope_cache.KIND_CONNECTOR_SCOPE,
           OWNER, WORKSPACE)
    pc_scope_cache._CACHE[key] = (
        time.monotonic() + 30, state, authority, SimpleNamespace(ready=True), None)
    try:
        async def scenario() -> None:
            await store.bump(generation.PC_CONNECTOR_SCOPE)
            await pc_scope_cache.cached_connector_scope(
                state=state, authority=authority, owner_id=OWNER,
                workspace_id=WORKSPACE, loader=loader)

        asyncio.run(scenario())
        assert calls == 1
    finally:
        connection.close()


def test_entry_without_generation_is_kept_when_there_is_no_number(tmp_path):
    """No table at all: a number-less entry keeps today's behaviour."""

    from app.identity_call_cache import _hash_key

    database = _database(tmp_path, with_table=False)
    connection, store = _store(database)
    inner = CountingIdentity()

    class Binding:
        calls = 0

        async def resolve_product_user_for_subject(self, payload):
            Binding.calls += 1
            return {"ok": True, "product_user_id": PRODUCT_USER}

    try:
        wrapped = CachedIdentityAuthority(inner, generation_store=store)
        key = "authsession:" + PRODUCT + ":" + _hash_key(OWNER)
        wrapped._entries[key] = (
            time.monotonic() + 60, SimpleNamespace(session_id="kept"), OWNER, None)
        seeded = tools.ConnectorToolGrant(
            reason=tools.GRANT_REASON_GRANTED, drive=True, calendar=True)
        tools._GRANT_CACHE[OWNER] = (time.monotonic(), seeded, None)
        generation._LAST_KNOWN.clear()
        generation.set_default_store(store)
        _product_user_cache[(PRODUCT, SUBJECT)] = (
            time.monotonic(), PRODUCT_USER, None)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            worker_cache_generation=store)))

        async def scenario() -> None:
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OWNER)
            assert inner.session_calls == 0
            decision, _elapsed, _timed_out = await tools._bounded_grant_decision(
                request, uid=OWNER)
            assert decision is seeded
            authority = CloudflareControlPlaneIdentityAuthority(Binding())
            assert await authority.resolve_product_user_for_subject(
                product_id=PRODUCT, canonical_subject_id=SUBJECT) == PRODUCT_USER

        asyncio.run(scenario())
        assert Binding.calls == 0
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# One process: the hit and invalidation results are today's
# ---------------------------------------------------------------------------


class CountingIdentity:
    def __init__(self) -> None:
        self.session_calls = 0
        self.scope_calls = 0

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.session_calls += 1
        return SimpleNamespace(session_id=SESSION)

    async def resolve_connector_owner_scope(self, *, session_id):
        self.scope_calls += 1
        return {"account_ref": OWNER, "workspace_ref": "ws"}


def test_one_process_keeps_todays_hits_and_invalidation(tmp_path):
    """A single worker: hit, then the local invalidation, exactly as before."""

    database = _database(tmp_path)
    connection, store = _store(database)
    inner = CountingIdentity()
    try:
        wrapped = CachedIdentityAuthority(inner, generation_store=store)

        async def scenario() -> None:
            for _ in range(3):
                await wrapped.resolve_current_auth_session(
                    product_id=PRODUCT, product_user_id=OWNER)
            assert inner.session_calls == 1, "the repeated read is served from memory"
            # Another account's answer stays standing across the invalidation.
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OTHER_OWNER)
            assert inner.session_calls == 2
            wrapped.invalidate_user(OWNER)
            await generation.drain_pending()
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OWNER)
            assert inner.session_calls == 3, "the invalidated answer is re-read"
            for _ in range(2):
                await wrapped.resolve_current_auth_session(
                    product_id=PRODUCT, product_user_id=OTHER_OWNER)
            assert inner.session_calls == 3, "the other account kept its entry"

        asyncio.run(scenario())
        assert _numbers(database)["identity_auth_session"] == 1
    finally:
        connection.close()


def test_pc_scope_hit_and_invalidation_are_unchanged_in_one_process(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    state = SimpleNamespace(worker_cache_generation=store)
    authority = SimpleNamespace(calls=0)

    async def loader():
        authority.calls += 1
        return SimpleNamespace(ready=True)

    async def scenario() -> None:
        for _ in range(3):
            await pc_scope_cache.cached_connector_scope(
                state=state, authority=authority, owner_id=OWNER,
                workspace_id=WORKSPACE, loader=loader,
            )
        assert authority.calls == 1
        pc_scope_cache.invalidate_owner_scope(OWNER, store=store)
        await generation.drain_pending()
        await pc_scope_cache.cached_connector_scope(
            state=state, authority=authority, owner_id=OWNER,
            workspace_id=WORKSPACE, loader=loader,
        )
        assert authority.calls == 2
        # A different account in the same window was never invalidated.
        await pc_scope_cache.cached_connector_scope(
            state=state, authority=authority, owner_id=OTHER_OWNER,
            workspace_id=WORKSPACE, loader=loader,
        )
        await pc_scope_cache.cached_connector_scope(
            state=state, authority=authority, owner_id=OTHER_OWNER,
            workspace_id=WORKSPACE, loader=loader,
        )
        assert authority.calls == 3

    try:
        asyncio.run(scenario())
        assert _numbers(database)["pc_connector_scope"] == 1
    finally:
        connection.close()


def test_grant_decision_hit_and_invalidation_are_unchanged_in_one_process(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    calls: list[str] = []

    async def truth(*_args, **_kwargs):
        calls.append("truth")
        return tools.ConnectorToolGrant(
            reason=tools.GRANT_REASON_GRANTED, drive=True, calendar=True)

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        worker_cache_generation=store)))

    async def scenario() -> None:
        original = tools._grant_decision_for_uid
        tools._grant_decision_for_uid = truth
        try:
            for _ in range(3):
                await tools._bounded_grant_decision(request, uid=OWNER)
            assert calls == ["truth"], "the repeated turn reads the cached decision"
            tools.invalidate_connector_tool_grant_cache(OWNER, store=store)
            await generation.drain_pending()
            await tools._bounded_grant_decision(request, uid=OWNER)
            assert calls == ["truth", "truth"]
            tools.seed_connector_grant_cache(
                OTHER_OWNER,
                tools.ConnectorToolGrant(reason=tools.GRANT_REASON_GRANTED,
                                        drive=True, calendar=True),
            )
            await tools._bounded_grant_decision(request, uid=OTHER_OWNER)
            assert calls == ["truth", "truth"], "another account's entry kept"
        finally:
            tools._grant_decision_for_uid = original

    try:
        asyncio.run(scenario())
        assert _numbers(database)["connector_tool_grant"] == 1
    finally:
        connection.close()


def test_subject_mapping_hit_and_invalidation_are_unchanged_in_one_process(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)

    class Binding:
        calls = 0

        async def resolve_product_user_for_subject(self, payload):
            Binding.calls += 1
            return {"ok": True, "product_user_id": PRODUCT_USER}

    authority = CloudflareControlPlaneIdentityAuthority(Binding())
    generation.set_default_store(store)

    async def scenario() -> None:
        for _ in range(3):
            assert await authority.resolve_product_user_for_subject(
                product_id=PRODUCT, canonical_subject_id=SUBJECT) == PRODUCT_USER
        assert Binding.calls == 1
        _product_user_cache_invalidate(PRODUCT, SUBJECT)
        await generation.drain_pending()
        await authority.resolve_product_user_for_subject(
            product_id=PRODUCT, canonical_subject_id=SUBJECT)
        assert Binding.calls == 2

    try:
        asyncio.run(scenario())
        assert _numbers(database)["identity_subject_mapping"] == 1
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# The two invalidation functions of auth_validation_cache also bump
# ---------------------------------------------------------------------------


def test_invalidate_auth_cache_bumps_every_identity_scope(tmp_path):
    from app.auth_validation_cache import SqliteAuthValidationCache

    database = _database(tmp_path)
    connection, store = _store(database)
    cached = SqliteAuthValidationCache(store.db)
    wrapped = CachedIdentityAuthority(SimpleNamespace(), generation_store=store)
    state = SimpleNamespace(
        worker_cache_generation=store,
        control_plane_identity_authority=wrapped,
        auth_validation_cache=cached,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def scenario() -> None:
        await invalidate_auth_cache(request, user_id=OWNER, session_id=SESSION)
        await generation.drain_pending()

    try:
        asyncio.run(scenario())
        numbers = _numbers(database)
        assert numbers["identity_auth_session"] == 1
        assert numbers["identity_owner_scope"] == 1
        assert numbers["identity_subject_mapping"] == 1
        assert numbers["pc_connector_scope"] == 0
        assert numbers["connector_tool_grant"] == 0
    finally:
        connection.close()


def test_drop_cached_owner_scope_of_bumps_only_the_owner_scope(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    state = SimpleNamespace(
        worker_cache_generation=store,
        control_plane_identity_authority=SimpleNamespace(
            invalidate_owner_scope_of_user=lambda user_id: None),
        auth_validation_cache=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def scenario() -> None:
        drop_cached_owner_scope_of(request, OWNER)
        await generation.drain_pending()

    try:
        asyncio.run(scenario())
        numbers = _numbers(database)
        assert numbers["identity_owner_scope"] == 1
        assert numbers["identity_auth_session"] == 0
    finally:
        connection.close()


def test_invalidate_auth_cache_keeps_other_users_identity_hit_in_one_process(tmp_path):
    from app.auth_validation_cache import SqliteAuthValidationCache

    database = _database(tmp_path)
    connection, store = _store(database)
    inner = CountingIdentity()
    wrapped = CachedIdentityAuthority(inner, generation_store=store)
    state = SimpleNamespace(
        worker_cache_generation=store,
        control_plane_identity_authority=wrapped,
        auth_validation_cache=SqliteAuthValidationCache(store.db),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    try:
        async def scenario() -> None:
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OWNER)
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OTHER_OWNER)
            assert inner.session_calls == 2
            await invalidate_auth_cache(request, user_id=OWNER)
            await generation.drain_pending()
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OTHER_OWNER)
            assert inner.session_calls == 2, "the other user's entry still hits"
            await wrapped.resolve_current_auth_session(
                product_id=PRODUCT, product_user_id=OWNER)
            assert inner.session_calls == 3, "the invalidated entry is re-read"

        asyncio.run(scenario())
    finally:
        connection.close()


def test_drop_cached_owner_scope_of_keeps_other_users_identity_hit_in_one_process(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)

    class ScopedIdentity:
        def __init__(self) -> None:
            self.scope_calls = 0

        async def resolve_connector_owner_scope(self, *, session_id):
            self.scope_calls += 1
            account = OWNER if session_id == "sess-u2" else OTHER_OWNER
            return {"account_ref": account, "workspace_ref": "ws"}

    inner = ScopedIdentity()
    wrapped = CachedIdentityAuthority(inner, generation_store=store)
    state = SimpleNamespace(
        worker_cache_generation=store,
        control_plane_identity_authority=wrapped,
        auth_validation_cache=None,
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    try:
        async def scenario() -> None:
            await wrapped.resolve_connector_owner_scope(session_id="sess-u2")
            await wrapped.resolve_connector_owner_scope(session_id="sess-u1")
            assert inner.scope_calls == 2
            drop_cached_owner_scope_of(request, OTHER_OWNER)
            await generation.drain_pending()
            await wrapped.resolve_connector_owner_scope(session_id="sess-u2")
            assert inner.scope_calls == 2, "the other user's entry still hits"
            await wrapped.resolve_connector_owner_scope(session_id="sess-u1")
            assert inner.scope_calls == 3, "the dropped entry is re-read"

        asyncio.run(scenario())
    finally:
        connection.close()


def test_a_route_helper_without_the_request_reaches_the_service_app_state(tmp_path):
    """The pairing/consent/logout call sites pass no request: the request context
    carries the application they are running in (``_CURRENT_APP``)."""

    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from app.request_telemetry import RequestTelemetryMiddleware

    database = _database(tmp_path)
    connection, store = _store(database)

    async def handler(_request):
        pc_scope_cache.invalidate_owner_scope(OWNER)
        tools.invalidate_connector_tool_grant_cache(OWNER)
        await generation.drain_pending()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/x", handler)])
    app.state.worker_cache_generation = store
    app.add_middleware(RequestTelemetryMiddleware, emitter=lambda event: None)
    try:
        with TestClient(app) as client:
            assert client.get("/x").status_code == 200
        numbers = _numbers(database)
        assert numbers["pc_connector_scope"] == 1
        assert numbers["connector_tool_grant"] == 1
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# No table: today's behaviour, no exception
# ---------------------------------------------------------------------------


def test_without_the_table_the_caches_keep_todays_behaviour(tmp_path):
    database = _database(tmp_path, with_table=False)
    connection, store = _store(database)
    inner = CountingIdentity()

    async def scenario() -> None:
        # Reading a missing table reports "no number" rather than raising.
        assert await generation.read_current(store, generation.IDENTITY_AUTH_SESSION) is None
        wrapped = CachedIdentityAuthority(inner, generation_store=store)
        await wrapped.resolve_current_auth_session(product_id=PRODUCT, product_user_id=OWNER)
        await wrapped.resolve_current_auth_session(product_id=PRODUCT, product_user_id=OWNER)
        assert inner.session_calls == 1, "no signal means the entry is kept"
        # An invalidation still drops locally and raises nothing.
        wrapped.invalidate_user(OWNER)
        await generation.drain_pending()
        await wrapped.resolve_current_auth_session(product_id=PRODUCT, product_user_id=OWNER)
        assert inner.session_calls == 2

    try:
        asyncio.run(scenario())
    finally:
        connection.close()


def test_without_the_table_the_scope_and_grant_caches_are_unchanged(tmp_path):
    database = _database(tmp_path, with_table=False)
    connection, store = _store(database)
    state = SimpleNamespace(worker_cache_generation=store)
    authority = SimpleNamespace(calls=0)

    async def loader():
        authority.calls += 1
        return SimpleNamespace(ready=True)

    async def scenario() -> None:
        for _ in range(2):
            await pc_scope_cache.cached_connector_scope(
                state=state, authority=authority, owner_id=OWNER,
                workspace_id=WORKSPACE, loader=loader,
            )
        assert authority.calls == 1
        pc_scope_cache.invalidate_owner_scope(OWNER, store=store)
        await generation.drain_pending()
        await pc_scope_cache.cached_connector_scope(
            state=state, authority=authority, owner_id=OWNER,
            workspace_id=WORKSPACE, loader=loader,
        )
        assert authority.calls == 2
        # The grant cache behaves the same way without any table.
        tools.seed_connector_grant_cache(
            OWNER, tools.ConnectorToolGrant(
                reason=tools.GRANT_REASON_GRANTED, drive=True, calendar=True))
        assert OWNER in tools._GRANT_CACHE

    try:
        asyncio.run(scenario())
    finally:
        connection.close()


def test_a_store_without_the_table_never_raises_on_bump(tmp_path):
    database = _database(tmp_path, with_table=False)
    connection, store = _store(database)

    async def scenario() -> None:
        assert await store.bump(generation.PC_CONNECTOR_SCOPE) is None
        await generation.bump_many(store, generation.SCOPES)
        assert generation.is_missing_generation_table(
            sqlite3.OperationalError("no such table: worker_cache_generation"))
        assert not generation.is_missing_generation_table(
            sqlite3.OperationalError("database is locked"))

    try:
        asyncio.run(scenario())
    finally:
        connection.close()


def test_no_store_at_all_keeps_every_cache_local(tmp_path):
    """A host with no database (Worker composition, unit tests): nothing changes."""

    inner = CountingIdentity()

    async def scenario() -> None:
        assert await generation.read_current(None, generation.PC_CONNECTOR_SCOPE) is None
        assert generation.is_stale(None, None) is False
        wrapped = CachedIdentityAuthority(inner)
        await wrapped.resolve_current_auth_session(product_id=PRODUCT, product_user_id=OWNER)
        await wrapped.resolve_current_auth_session(product_id=PRODUCT, product_user_id=OWNER)
        assert inner.session_calls == 1
        wrapped.invalidate_user(OWNER)   # no store to tell; must not raise
        await generation.drain_pending()

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# The number is read once per request
# ---------------------------------------------------------------------------


def test_the_number_is_read_once_per_request(tmp_path):
    database = _database(tmp_path)
    connection, store = _store(database)
    reads: list[str] = []

    class Counting(generation.D1WorkerCacheGenerationStore):
        async def read(self, scope):
            reads.append(scope)
            return await super().read(scope)

    counting = Counting(store.db)

    async def scenario() -> None:
        from app.request_telemetry import _CURRENT_REQUEST_ID

        token = _CURRENT_REQUEST_ID.set("req-7543-generation")
        try:
            for _ in range(3):
                await generation.read_current(counting, generation.PC_CONNECTOR_SCOPE)
                await generation.read_current(counting, generation.CONNECTOR_TOOL_GRANT)
        finally:
            _CURRENT_REQUEST_ID.reset(token)
        assert reads == [generation.PC_CONNECTOR_SCOPE, generation.CONNECTOR_TOOL_GRANT]

    try:
        asyncio.run(scenario())
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# Composition and the shipped migration
# ---------------------------------------------------------------------------


def test_the_host_composition_binds_the_generation_store(tmp_path):
    """create_app puts the store on the app state, on the same canonical database."""

    from starlette.applications import Starlette

    from app.app_factory import create_app
    from app.config import Settings

    database = _database(tmp_path)
    connection, store = _store(database)
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="issue7543.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret="issue7543-generation-session-secret-not-a-real-key",
        session_max_age_seconds=3600,
        web_provider="off",
    )
    try:
        app = create_app(settings=settings, d1_binding=store.db)
        assert isinstance(app, Starlette)
        assert isinstance(
            app.state.worker_cache_generation,
            generation.D1WorkerCacheGenerationStore,
        )
        assert app.state.worker_cache_generation.db is store.db
    finally:
        connection.close()


def test_the_migration_is_additive_and_carries_no_identity_values():
    text = (MIGRATIONS / MIGRATION).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS worker_cache_generation" in text
    assert "INSERT OR IGNORE INTO worker_cache_generation" in text
    lowered = text.lower()
    for forbidden in ("user_id", "session_id", "token", "secret", "cookie", "email"):
        assert forbidden not in lowered
    assert "generation INTEGER NOT NULL" in text
    # Scope names are the only thing stored beside the number.
    assert "'identity_auth_session'" in text and "'connector_tool_grant'" in text
