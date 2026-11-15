"""#7543 5단계 두-프로세스 확인용 워커 하나 — 캐시 4종 중 하나만 다룬다.

이 스크립트는 부모 시험과 **같은 SQLite 파일**의 세대 번호 표를 쓰는 **별도
프로세스**다. 부모는 단계 목록을 주고, 표준출력의 JSON 한 줄로 단계마다 "원본을 몇
번 불렀는가"를 돌려받는다. 두 프로세스를 번갈아 세워 A가 무효화한 뒤 B의 다음
조회가 캐시를 버리는지를 본다.

대상(``cache``):

* ``identity``    — ``CachedIdentityAuthority`` 의 세션 답(authsession:)
* ``owner_scope`` — ``CachedIdentityAuthority`` 의 PC 소유 범위 답(ownerscope:)
* ``subject``     — identity Worker 어댑터의 subject→계정 매핑
* ``pc_scope``    — ``app/pc_scope_cache.py`` 의 Claw 커넥터 범위 창
* ``grant``       — ``app/chat_connector_tools.py`` 의 커넥터 도구 허용 판단

단계(``script`` 는 쉼표로 잇는다):

* ``prime`` / ``read`` — 같은 조회를 한 번 한다(원본 호출 수를 돌려준다).
* ``invalidate``       — 이 프로세스의 무효화 함수를 부른다(번호도 올린다).
* ``invalidate_other`` — 다른 사용자의 무효화 함수를 부른다(번호도 올린다).
  이 프로세스가 캐시한 첫 사용자의 항목은 로컬로 지우지 않는다.
* ``bumpall``          — 다른 프로세스가 무효화한 것처럼 표의 모든 범위를 올린다.
* ``wait:<name>``      — 폴더에 그 이름의 파일이 생길 때까지 기다린다.
* ``mark:<name>``      — 그 이름의 파일을 만든다.

비밀값·계정 값은 전부 가짜이고, 네트워크 소켓은 열지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PRODUCT = "b62"
OWNER = "usr_" + "1" * 32
OTHER_OWNER = "usr_" + "2" * 32
SESSION = "authsession:b62:worker-generation"
WORKSPACE = "tenant_" + "3" * 32
SUBJECT = "sub_worker_generation"
PRODUCT_USER = "puser_worker_generation"


class CountingIdentity:
    """The authority stand-in of the identity call cache; counts source reads."""

    def __init__(self) -> None:
        self.session_calls = 0
        self.scope_calls = 0

    async def resolve_current_auth_session(self, *, product_id, product_user_id):
        self.session_calls += 1
        return SimpleNamespace(session_id=f"{SESSION}:{self.session_calls}")

    async def resolve_connector_owner_scope(self, *, session_id):
        self.scope_calls += 1
        return {"account_ref": OWNER, "workspace_ref": f"ws:{self.scope_calls}"}


class CountingBinding:
    """The identity Worker service binding stand-in; counts RPC calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def resolve_product_user_for_subject(self, payload):
        self.calls += 1
        return {"ok": True, "product_user_id": PRODUCT_USER}


class ScopeAuthority:
    """The loader the Claw connector-scope window wraps; counts source reads."""

    def __init__(self) -> None:
        self.calls = 0

    async def resolve_connector_owner_scope(self, *, owner_id, workspace_id):
        self.calls += 1
        return SimpleNamespace(ready=True, workspace_ref=f"ws:{self.calls}")


def _scope_state(store) -> SimpleNamespace:
    return SimpleNamespace(worker_cache_generation=store)


class Worker:
    """One process: holds its own caches and reads/writes the shared table."""

    def __init__(self, store) -> None:
        from app.identity_call_cache import CachedIdentityAuthority

        self.store = store
        self.identity_authority = CountingIdentity()
        self.identity = CachedIdentityAuthority(
            self.identity_authority, generation_store=store
        )
        self.binding = CountingBinding()
        self.scope_authority = ScopeAuthority()
        # The window keys on (app state, authority) identity, so both are built
        # once per process — the way a served app holds them.
        self.state = _scope_state(store)
        self.grant_calls = 0

    # -- cache 1: identity call cache (session answers) --------------------
    async def _identity(self) -> int:
        before = self.identity_authority.session_calls
        await self.identity.resolve_current_auth_session(
            product_id=PRODUCT, product_user_id=OWNER
        )
        return self.identity_authority.session_calls - before

    # -- cache 1b: identity call cache (PC owner scope answers) ------------
    async def _owner_scope(self) -> int:
        before = self.identity_authority.scope_calls
        await self.identity.resolve_connector_owner_scope(session_id=SESSION)
        return self.identity_authority.scope_calls - before

    # -- cache 2: subject -> account mapping -------------------------------
    async def _subject(self) -> int:
        from app.control_plane_identity_worker import (
            CloudflareControlPlaneIdentityAuthority,
        )

        authority = CloudflareControlPlaneIdentityAuthority(self.binding)
        before = self.binding.calls
        await authority.resolve_product_user_for_subject(
            product_id=PRODUCT, canonical_subject_id=SUBJECT
        )
        return self.binding.calls - before

    # -- cache 3: Claw connector scope window ------------------------------
    async def _pc_scope(self) -> int:
        from app import pc_scope_cache

        before = self.scope_authority.calls

        async def loader():
            return await self.scope_authority.resolve_connector_owner_scope(
                owner_id=OWNER, workspace_id=WORKSPACE
            )

        await pc_scope_cache.cached_connector_scope(
            state=self.state, authority=self.scope_authority,
            owner_id=OWNER, workspace_id=WORKSPACE, loader=loader,
        )
        return self.scope_authority.calls - before

    # -- cache 4: connector tool grant decision ----------------------------
    async def _grant(self) -> int:
        from app import chat_connector_tools as tools

        before = self.grant_calls

        async def truth(*_args, **_kwargs):
            self.grant_calls += 1
            return tools.ConnectorToolGrant(
                reason=tools.GRANT_REASON_GRANTED, drive=True, calendar=True,
            )

        original = tools._grant_decision_for_uid
        tools._grant_decision_for_uid = truth
        try:
            request = SimpleNamespace(app=SimpleNamespace(state=self.state))
            await tools._bounded_grant_decision(request, uid=OWNER)
        finally:
            tools._grant_decision_for_uid = original
        return self.grant_calls - before

    async def read(self, cache: str) -> int:
        return await {
            "identity": self._identity,
            "owner_scope": self._owner_scope,
            "subject": self._subject,
            "pc_scope": self._pc_scope,
            "grant": self._grant,
        }[cache]()

    # -- invalidation entry points ----------------------------------------
    async def invalidate(self, cache: str, owner: str = OWNER) -> None:
        from app import chat_connector_tools as tools
        from app import pc_scope_cache
        from app.control_plane_identity_worker import _product_user_cache_invalidate

        if cache == "identity":
            self.identity.invalidate_user(owner)
        elif cache == "owner_scope":
            self.identity.invalidate_owner_scope_of_user(owner)
        elif cache == "subject":
            _product_user_cache_invalidate(PRODUCT, SUBJECT)
        elif cache == "pc_scope":
            pc_scope_cache.invalidate_owner_scope(owner, store=self.store)
        elif cache == "grant":
            tools.invalidate_connector_tool_grant_cache(owner, store=self.store)
        else:
            raise SystemExit("unknown cache " + cache)


async def _run(database: Path, cache: str, script: list[str], work: Path) -> dict:
    from app import worker_cache_generation as generation
    from app.d1_sqlite import SqliteD1, connect

    connection = connect(str(database))
    store = generation.D1WorkerCacheGenerationStore(SqliteD1(connection, threaded=True))
    generation.reset_default_store()
    generation.set_default_store(store)
    worker = Worker(store)
    steps: list[dict] = []
    try:
        for step in script:
            if step in {"prime", "read"}:
                steps.append({"step": step, "calls": await worker.read(cache)})
            elif step == "invalidate":
                await worker.invalidate(cache)
                await generation.drain_pending()
                steps.append({"step": step, "calls": 0})
            elif step == "invalidate_other":
                await worker.invalidate(cache, OTHER_OWNER)
                await generation.drain_pending()
                steps.append({"step": step, "calls": 0})
            elif step == "bumpall":
                for scope in generation.SCOPES:
                    await store.bump(scope)
                steps.append({"step": step, "calls": 0})
            elif step.startswith("wait:"):
                target = work / step.split(":", 1)[1]
                deadline = time.monotonic() + 120
                while not target.exists():
                    if time.monotonic() > deadline:
                        raise SystemExit("wait timeout " + target.name)
                    time.sleep(0.005)
                steps.append({"step": step, "calls": 0})
            elif step.startswith("mark:"):
                (work / step.split(":", 1)[1]).touch()
                steps.append({"step": step, "calls": 0})
            else:
                raise SystemExit("unknown step " + step)
        numbers = {scope: await store.read(scope) for scope in generation.SCOPES}
        return {"steps": steps, "numbers": numbers}
    finally:
        connection.close()


if __name__ == "__main__":
    database, cache, script, ready, work = sys.argv[1:6]
    Path(ready).touch()
    print(json.dumps(asyncio.run(_run(Path(database), cache, script.split(","), Path(work)))),
          flush=True)
