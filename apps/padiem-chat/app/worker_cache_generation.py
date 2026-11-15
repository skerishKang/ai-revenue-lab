"""#7543 5단계 — 워커별 캐시를 버리라는 신호를 프로세스 사이에서 공유한다.

네 캐시는 지금처럼 각 워커의 메모리에 둔다(identity 호출 결과, Claw 커넥터 범위,
커넥터 도구 허용 판단, canonical subject→계정 매핑). 값 자체를 SQLite로 옮기면 응답
객체 직렬화가 필요해 변경 범위가 커지므로, 공유하는 것은 "이 범위의 캐시를 버려라"는
신호 하나뿐이다. 이 모듈이 그 신호를 담는 작은 표(범위 이름 → 정수 번호)를 읽고 올린다.

동작
----
* 무효화하는 쪽은 :func:`bump_many` 로 해당 범위의 번호를 1 올린다.
* 캐시를 읽는 쪽은 값을 저장할 때 그때의 번호를 함께 두고, 조회할 때
  :func:`read_current` 로 지금 번호를 한 번(요청당 범위별 1회) 읽어 다르면 그 항목을
  버리고 원본을 다시 부른다.
* 표가 없거나(마이그레이션 미적용) 읽기가 실패하면 "번호 없음"(``None``)으로 보고
  지금 동작을 그대로 유지한다 — 캐시를 버리지도, 예외를 올리지도 않는다.
  번호를 올리지 못하는 것도 마찬가지로 조용히 넘어간다(무효화 자체는 각 캐시가
  이미 자기 프로세스에서 수행했다).

번호는 범위(scope)별로 하나이므로, 한 프로세스가 한 사용자의 무효화를 올리면 다른
프로세스는 그 범위의 모든 항목을 버린다. 버린 뒤 원본을 다시 부르는 쪽이 안전하고
무효화 이벤트 자체가 드물어, 사용자 단위로 나누지 않았다. 버려진 항목은 다음 조회가
권위에서 다시 받아 채운다.

저장 위치에는 범위 이름과 정수, 갱신 시각만 들어간다. 사용자 id·subject·세션·
자격 증명 값은 어느 열에도 쓰지 않는다.
"""
from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar
from typing import Any, Callable

from .request_telemetry import current_app, current_request_id

#: identity 호출 캐시의 세션 답(authsession:, authsess:) 범위.
IDENTITY_AUTH_SESSION = "identity_auth_session"
#: identity 호출 캐시의 PC 소유 범위 답(ownerscope:) 범위.
IDENTITY_OWNER_SCOPE = "identity_owner_scope"
#: subject→계정 매핑. identity 호출 캐시의 productuser: 와 identity Worker 어댑터의
#: 프로세스 캐시가 같은 범위를 쓴다.
IDENTITY_SUBJECT_MAPPING = "identity_subject_mapping"
#: Claw PC 커넥터 범위 창(``app/pc_scope_cache.py``).
PC_CONNECTOR_SCOPE = "pc_connector_scope"
#: 커넥터 도구 허용 판단 창(``app/chat_connector_tools.py``).
CONNECTOR_TOOL_GRANT = "connector_tool_grant"

SCOPES = (
    IDENTITY_AUTH_SESSION,
    IDENTITY_OWNER_SCOPE,
    IDENTITY_SUBJECT_MAPPING,
    PC_CONNECTOR_SCOPE,
    CONNECTOR_TOOL_GRANT,
)

TABLE = "worker_cache_generation"

_DEFAULT_STORE: list[Any] = [None]

#: 이 프로세스가 마지막으로 읽은(또는 올린) 범위별 번호. 비동기로 읽을 수 없는
#: 경로(이미 권위의 답을 받아 캐시에 넣는 자리)가 마지막으로 본 번호를 쓴다.
_LAST_KNOWN: dict[str, int] = {}

#: ``(요청 id, {범위: 번호})``. 요청 하나가 같은 범위를 두 번 읽지 않게 한다.
_READS: ContextVar[tuple[str, dict[str, int | None]] | None] = ContextVar(
    "padiem_worker_cache_generation_reads", default=None
)


def is_missing_generation_table(exc: BaseException) -> bool:
    """표가 없다는 실패인가(마이그레이션 121 미적용). 그 밖의 실패는 아니다."""

    text = str(exc).lower()
    return "no such table" in text and TABLE in text


def is_stale(stored: int | None, current: int | None) -> bool:
    """저장할 때의 번호와 지금 번호가 다른가.

    둘 중 하나라도 번호가 없으면(표가 없거나 읽기 실패, 이 프로세스가 아직 읽지
    않은 값으로 채운 항목) 신호를 쓸 수 없으므로 오늘 동작을 유지한다 — 버리지
    않는다. 번호는 오직 올라가므로, 이 프로세스가 마지막으로 읽은 번호를 저장해
    두었다면 그 뒤의 무효화는 반드시 다른 번호로 보인다.
    """

    return type(stored) is int and type(current) is int and stored != current


class D1WorkerCacheGenerationStore:
    """세대 번호 표를 읽고 올리는 저장소(상태 없음, 여러 워커가 같은 파일을 쓴다)."""

    def __init__(self, db: Any, *, clock: Callable[[], float] = time.time) -> None:
        if db is None or not callable(getattr(db, "prepare", None)):
            raise ValueError("D1 binding is required")
        self.db = db
        # 벽시계다. 갱신 시각은 프로세스 사이에서 비교·기록되는 값이다.
        self._clock = clock

    def _statement(self, sql: str, *values: Any) -> Any:
        return self.db.prepare(sql).bind(*values)

    def _now_ms(self) -> int:
        return int(self._clock() * 1000)

    async def read(self, scope: str) -> int | None:
        """범위의 지금 번호. 표가 없거나 읽지 못하면 ``None``."""

        if not isinstance(scope, str) or not scope:
            return None
        try:
            row = await self._statement(
                f"SELECT generation FROM {TABLE} WHERE scope = ?", scope
            ).first()
        except Exception:  # noqa: BLE001 - a missing signal never fails a request
            # No table (migration not applied), a locked database, a lost
            # connection: every failure means "no number", never an exception
            # and never a dropped cache.
            return None
        value = row.get("generation") if isinstance(row, dict) else None
        return value if type(value) is int and value >= 0 else None

    async def bump(self, scope: str) -> int | None:
        """범위의 번호를 1 올린다. 올리지 못하면 ``None``(예외 없음).

        무효화는 이미 이 프로세스에서 끝났고, 여기서 실패해도 사용자에게 보이는
        결과는 바뀌지 않는다. 다른 워커는 각 캐시의 만료 시간 안에서 따라온다.
        """

        if not isinstance(scope, str) or not scope:
            return None
        try:
            await self._statement(
                f"INSERT INTO {TABLE} (scope, generation, updated_at_ms) "
                "VALUES (?, 1, ?) "
                "ON CONFLICT(scope) DO UPDATE SET "
                f"generation = {TABLE}.generation + 1, "
                "updated_at_ms = excluded.updated_at_ms",
                scope,
                self._now_ms(),
            ).run()
        except Exception:  # noqa: BLE001 - see the method docstring
            return None
        return True


def default_store() -> Any:
    """이 프로세스가 여러 워커 호스트에서 조립될 때 정해진 저장소(없으면 ``None``).

    워커가 하나인 프로세스(시험 포함)와 Cloudflare Worker 조립에서는 정해지지
    않으므로, 저장소를 넘기지 않는 호출부는 오늘 동작 그대로다.
    """

    return _DEFAULT_STORE[0]


def set_default_store(store: Any) -> None:
    _DEFAULT_STORE[0] = store


def reset_default_store() -> None:
    _DEFAULT_STORE[0] = None


def store_for_state(state: Any) -> Any:
    """앱 상태에 붙은 저장소, 없으면 프로세스 기본 저장소."""

    store = getattr(state, "worker_cache_generation", None)
    if isinstance(store, D1WorkerCacheGenerationStore):
        return store
    return default_store()


def store_for_request(request: Any) -> Any:
    """요청이 실린 앱 상태의 저장소(없으면 프로세스 기본 저장소)."""

    return store_for_state(getattr(getattr(request, "app", None), "state", None))


def current_request_store() -> Any:
    """지금 요청이 실린 앱의 저장소(없으면 프로세스 기본 저장소).

    무효화 호출부 여럿이 요청 객체 없이 캐시만 비운다. 그 자리에서도 같은 앱
    상태의 번호 표를 올릴 수 있게, 요청 문맥이 들고 있는 앱을 쓴다.
    """

    store = store_for_state(getattr(current_app(), "state", None))
    return store if store is not None else default_store()


async def read_current(store: Any, scope: str) -> int | None:
    """지금 번호. 같은 요청 안에서는 범위마다 한 번만 표를 읽는다."""

    if store is None or not callable(getattr(store, "read", None)):
        return None
    request_id = current_request_id()
    if not isinstance(request_id, str) or not request_id:
        # No request around this call (a background path): read it, still only
        # once per call, and remember it for the callers that cannot await.
        value = await store.read(scope)
        note_known(scope, value)
        return value
    seen = _READS.get()
    if seen is not None and seen[0] == request_id and scope in seen[1]:
        return seen[1][scope]
    value = await store.read(scope)
    if isinstance(value, int):
        _LAST_KNOWN[scope] = value
    values = dict(seen[1]) if seen is not None and seen[0] == request_id else {}
    values[scope] = value
    _READS.set((request_id, values))
    return value


def last_known(scope: str) -> int | None:
    """이 프로세스가 마지막으로 본 그 범위의 번호(없으면 ``None``)."""

    return _LAST_KNOWN.get(scope)


def note_known(scope: str, value: int | None) -> None:
    if isinstance(value, int):
        _LAST_KNOWN[scope] = value


async def bump_many(store: Any, scopes: tuple[str, ...]) -> None:
    """여러 범위의 번호를 올린다. 실패는 조용히 넘긴다."""

    if store is None or not callable(getattr(store, "bump", None)):
        return
    for scope in scopes:
        await store.bump(scope)


#: 진행 중인 신호 쓰기. 참조를 잡아 두어 GC가 태스크를 거두지 않게 한다.
_PENDING: set[Any] = set()


def bump_soon(
    store: Any,
    scopes: tuple[str, ...],
    *,
    on_bump: Callable[[str, int], None] | None = None,
) -> None:
    """무효화 신호를 지금 루프의 태스크로 올린다(응답 경로를 막지 않는다).

    ``on_bump`` 는 그 범위의 새 번호를 받는다. 이 프로세스가 무효화하지 않은
    나머지 항목을 새 번호로 다시 표시해, 워커 1개일 때의 적중 결과를 유지한다.
    번호를 올리지 못하면 ``on_bump`` 를 부르지 않는다 — 남은 항목은 다음 조회에서
    원본을 다시 부르게 되고(보수적), 결과는 지금과 같다.
    """

    if store is None or not callable(getattr(store, "bump", None)) or not scopes:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 루프 밖(동기 조립·정리)에서는 이 프로세스 밖에 알릴 요청이 없다.
        return

    async def run() -> None:
        for scope in scopes:
            value = await store.read(scope)
            bumped = await store.bump(scope)
            if bumped is None:
                continue
            number = value + 1 if isinstance(value, int) else await store.read(scope)
            if isinstance(number, int):
                _LAST_KNOWN[scope] = number
                if on_bump is not None:
                    on_bump(scope, number)

    task = loop.create_task(run())
    _PENDING.add(task)

    def _finished(done: Any) -> None:
        _PENDING.discard(done)
        if not done.cancelled():
            done.exception()

    task.add_done_callback(_finished)


async def drain_pending() -> None:
    """진행 중인 신호 쓰기를 기다린다(시험·종료 경로에서만 쓴다)."""

    while _PENDING:
        await asyncio.gather(*list(_PENDING), return_exceptions=True)


__all__ = [
    "CONNECTOR_TOOL_GRANT",
    "D1WorkerCacheGenerationStore",
    "IDENTITY_AUTH_SESSION",
    "IDENTITY_OWNER_SCOPE",
    "IDENTITY_SUBJECT_MAPPING",
    "PC_CONNECTOR_SCOPE",
    "SCOPES",
    "bump_many",
    "bump_soon",
    "current_request_store",
    "default_store",
    "drain_pending",
    "is_missing_generation_table",
    "is_stale",
    "last_known",
    "note_known",
    "read_current",
    "reset_default_store",
    "set_default_store",
    "store_for_request",
    "store_for_state",
]
