"""#7035 재발 방지: 운영 설정 모양에서 Chat 기동 훅이 전부 끝난다.

11-07 05:38 컴2 저널: `80be22ee` 배포 직후 padiem-chat-com2가
`AttributeError: 'MaintenanceModeMiddleware' object has no attribute 'router'`로
`Application startup failed`. `build_app()`는 마지막에 `app = apply_write_freeze(app)`
로 지역 이름을 ASGI 래퍼로 다시 묶으므로, 래퍼가 씌워진 뒤 실행되는 startup 훅이
그 이름을 호출 시점에 읽으면 `.router`에서 죽는다.

기존 #7035 시험은 write-freeze 스위치 하나만 봤다. 이 시험은
`deploy/host-com2/chat/.env.example`과 `deploy/host-com2/chat/check_config.py`가
정의하는 운영 모양(CPython host, https 공개 주소, loopback B14, identity RPC 쌍)을
그대로 세우고, 쓰기 동결을 **센티널 파일 / 스위치 / 끔** 세 가지로 바꿔가며
`build_app()`이 등록한 startup·shutdown 훅을 전부 실행한다. 값은 전부 가짜이며
비밀 값은 저장소에도 로그에도 남지 않는다.
"""
from __future__ import annotations

import asyncio

import pytest

from app import local_cpython
from app.maintenance_mode import MaintenanceModeMiddleware

# 운영 .env가 켜는 이름들, 값은 전부 합성값이다 (#7035 계열 시험과 같은 규칙).
PRODUCTION_ENV = {
    "PADIEM_CHAT_CPYTHON_HOST": "1",
    "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2.padiem.net",
    "PADIEM_CHAT_AUTH_MODE": "password",
    "PADIEM_CHAT_COOKIE_SECURE": "true",
    "PADIEM_CHAT_SESSION_SECRET": "synthetic-session-secret-0123456789abcdef",
    "PADIEM_CHAT_RUNTIME_MODE": "b14",
    "PADIEM_CHAT_LIVE_ENABLED": "false",
    "PADIEM_CHAT_WEB_PROVIDER": "off",
    "PADIEM_CHAT_TIMEOUT_SECONDS": "600",
    "PADIEM_CHAT_COMPLETED_TIMEOUT_SECONDS": "600",
    "PADIEM_CHAT_WORKERS": "1",
    "B14_UPSTREAM_MODE": "loopback",
    "B14_UPSTREAM_URL": "http://127.0.0.1:8789",
    "PADIEM_B14_SERVICE_PROOF_SECRET": "synthetic-b14-proof-secret-0123456789abcdef",
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example.test",
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET": "synthetic-identity-secret-0123456789ab",
    # The warm cycle stays a full period away, so no RPC can leave this process
    # while the test runs; the shutdown hook still has to cancel it.
    "PADIEM_CHAT_IDENTITY_KEEPWARM_SECONDS": "600",
    "PADIEM_CHAT_LOOP_STALL_WATCHDOG": "off",
}

#: Names another lane or the developer's shell may carry; a host run must not
#: inherit them (PADIEM_LOCAL_DEV is refused next to the host flag).
CLEARED_ENV = (
    "PADIEM_LOCAL_DEV",
    "PADIEM_CHAT_WRITE_FREEZE",
    "PADIEM_CHAT_WRITE_FREEZE_PATHS",
    "PADIEM_CHAT_MAINTENANCE_SENTINEL",
    "PADIEM_CHAT_SHARED_LOGIN_ENABLED",
    "PADIEM_CHAT_MODEL_FIRST",
    "PADIEM_COM2_EDGE_PROOF_REQUIRED",
    "PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED",
    "PADIEM_COM2_EDGE_SECRET_FILE",
    "PADIEM_COM2_BROKER_RPC_SECRET_FILE",
    "PADIEM_CLAW_PUBLIC_WEB_SEARCH_ENABLED",
    "PC_QUEUE_BACKEND",
    "PC_QUEUE_ORIGIN",
    "PC_QUEUE_SERVICE_SECRET",
    "PC_QUEUE_SERVICE_SECRET_FILE",
    "ORACLE_MESH_EXECUTION_MODE",
    "ORACLE_MESH_CHANNEL_SECRET",
    "ORACLE_MESH_LEGACY_MAP_LANE",
    "ORACLE_MESH_OWNERSHIP_MAP",
    "CLAW_ENGINE_DESKTOP_SECRET",
    "PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN",
    "PADIEM_CHAT_LOCAL_B66_PDF_SECRET",
)

#: 쓰기 동결을 켜는 서로 다른 두 운영 방식과, 꺼진 상태(래퍼 없음).
FREEZE_COMBOS = ("sentinel_file", "switch", "off")


def _apply_production_env(monkeypatch, tmp_path, combo):
    for name in CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in PRODUCTION_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    if combo == "sentinel_file":
        # Production's stage-3 window: the file itself may or may not exist.
        monkeypatch.setenv(
            "PADIEM_CHAT_MAINTENANCE_SENTINEL", str(tmp_path / "MAINTENANCE")
        )
    elif combo == "switch":
        monkeypatch.setenv("PADIEM_CHAT_WRITE_FREEZE", "1")


def _run_lifespan(host):
    """Run every registered startup hook, then every shutdown hook, one loop."""
    from app import identity_cache_metrics

    starlette_app = host._app if isinstance(host, MaintenanceModeMiddleware) else host
    started = []

    async def scenario():
        for handler in list(starlette_app.router.on_startup):
            result = handler()
            if asyncio.iscoroutine(result):
                await result
            started.append(handler)
        # The keepwarm hook ran its body against the Starlette app: the minute
        # counter timer is armed and the WAL loop owns state.
        assert identity_cache_metrics._timer is not None
        assert getattr(starlette_app.state, "wal_checkpoint_task", None) is not None
        for handler in list(starlette_app.router.on_shutdown):
            result = handler()
            if asyncio.iscoroutine(result):
                await result

    asyncio.run(scenario())
    assert started  # the app really registered startup hooks
    assert identity_cache_metrics._timer is None
    assert getattr(starlette_app.state, "wal_checkpoint_task", None) is None


@pytest.mark.parametrize("combo", FREEZE_COMBOS)
def test_production_shaped_host_runs_every_startup_hook(monkeypatch, tmp_path, combo):
    _apply_production_env(monkeypatch, tmp_path, combo)
    host = local_cpython.build_app()
    if combo == "off":
        # No maintenance window configured: the Starlette app is served as is.
        assert not isinstance(host, MaintenanceModeMiddleware)
    else:
        # The production shape from the incident: uvicorn is handed the wrapper.
        assert isinstance(host, MaintenanceModeMiddleware)
    _run_lifespan(host)
