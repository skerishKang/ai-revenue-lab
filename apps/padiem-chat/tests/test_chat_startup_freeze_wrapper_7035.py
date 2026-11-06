"""#7035 롤백 사고: write-freeze 래퍼가 씌워진 상태에서도 호스트 기동이 끝난다.

11-07 05:38 컴2 저널: `80be22ee` 배포 직후 padiem-chat-com2가
"AttributeError: 'MaintenanceModeMiddleware' object has no attribute 'router'"
로 "Application startup failed". `build_app`는 마지막에 `app = apply_write_freeze(app)`
로 지역 이름 `app`을 ASGI 래퍼로 다시 묶는데, identity keepwarm 기동 훅이 그
클로저 이름을 호출 시점에 읽어 래퍼에 `on_shutdown`을 달려고 했다.

이 시험은 실제 `build_app()`을 write-freeze 켜진 환경에서 만들어, 라우터에 등록된
모든 startup 훅을 실행하고 shutdown 훅까지 같은 루프에서 끝낸다. 래퍼가 씌워진
상태(운영과 같은 모양)에서 예외 없이 끝나야 한다.
"""

from __future__ import annotations

import asyncio

from app import local_cpython
from app.maintenance_mode import MaintenanceModeMiddleware

HOST_ENV = {
    "PADIEM_LOCAL_DEV": "1",
    # The freeze window is what rebinds `app` to MaintenanceModeMiddleware.
    "PADIEM_CHAT_WRITE_FREEZE": "1",
    # The keepwarm hook only runs its body when the identity binding exists.
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example.test",
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET": (
        "com2-host-identity-secret-0123456789abcdef"
    ),
    "PADIEM_CHAT_LOOP_STALL_WATCHDOG": "off",
}


def _build_host_app(monkeypatch, tmp_path):
    for name, value in HOST_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    return local_cpython.build_app()


def test_the_host_app_starts_with_the_write_freeze_wrapper(monkeypatch, tmp_path):
    from app import identity_cache_metrics

    host = _build_host_app(monkeypatch, tmp_path)
    # The production shape from the incident: uvicorn is handed the wrapper.
    assert isinstance(host, MaintenanceModeMiddleware)
    starlette_app = host._app

    async def run_startup_and_shutdown() -> None:
        for handler in list(starlette_app.router.on_startup):
            result = handler()
            if asyncio.iscoroutine(result):
                await result
        # The keepwarm hook armed the minute counters, so the body really ran
        # against the Starlette app rather than being skipped.
        assert identity_cache_metrics._timer is not None
        for handler in list(starlette_app.router.on_shutdown):
            result = handler()
            if asyncio.iscoroutine(result):
                await result

    asyncio.run(run_startup_and_shutdown())
    assert identity_cache_metrics._timer is None
