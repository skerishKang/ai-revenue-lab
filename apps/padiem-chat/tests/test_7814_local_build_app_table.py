"""#7814 T4 — `build_app` 앞 구간(설정 읽기·검증 + SQLite/disk-R2) 골든 표.

`local_cpython.build_app`의 앞쪽 연속 구간 하나를 helper로 떼어 낸다. 이 시험은
그 구간이 지키던 계약을 리팩터링 전 `main`의 실행 결과 그대로 고정한다.

- 거절 4경로: 예외 종류와 문구를 원래 그대로 비교한다.
  · 플래그 없음 (원래 261)
  · 로컬 플래그가 Settings에 닿지 않음 (원래 282)
  · 호스트 플래그 + 로컬 플래그 (원래 288)
  · 호스트 실행의 non-https 공개 주소 (원래 290)
- 정상 입력 2개: A(최소 개발 환경), B(A + 선택 서비스 바인딩 하나). 고정 대상은
  라우트 목록(경로·메서드·순서)과 `app.state` 속성 이름 목록이다. 값은 비교하지
  않는다. 선택 바인딩은 라우트를 더하지 않으므로 두 입력의 표면은 같아야 한다.
  골든 JSON은 리팩터링 전 `main`에서 먼저 뜬 것이다
  (`fixtures/local_build_app_7814_surface.json`).

환경은 monkeypatch, 데이터 경로는 tmp_path. 운영 비밀값·주소는 쓰지 않는다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import app.local_cpython as local_cpython
from app.config import ConfigError, Settings

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "local_build_app_7814_surface.json"
)

#: The smallest environment `test_local_cpython.local_env` builds an app with.
BASE_ENV = {
    "PADIEM_CHAT_RUNTIME_MODE": "mock",
    "PADIEM_CHAT_AUTH_MODE": "off",
    "PADIEM_CHAT_WEB_PROVIDER": "off",
    "PADIEM_CHAT_PUBLIC_BASE_URL": "http://127.0.0.1:8773",
    "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
}

#: B adds one optional service binding to A; nothing else changes.
IDENTITY_BINDING = {
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN": "https://identity.example",
    "PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET": "local-service-secret-0123456789abcd",
}


def _isolate_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from an environment with no PADIEM/PC_QUEUE value left over."""

    for name in tuple(os.environ):
        if name.startswith(("PADIEM_", "PC_QUEUE_")):
            monkeypatch.delenv(name)


def _local_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **extra: str
) -> None:
    values = dict(
        BASE_ENV,
        PADIEM_LOCAL_DEV="1",
        PADIEM_CHAT_LOCAL_DATA_DIR=str(tmp_path),
    )
    values.update(extra)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


def _app_surface(app: object) -> dict:
    routes = [
        [route.path, sorted(getattr(route, "methods", None) or ())]
        for route in app.router.routes
    ]
    return {"routes": routes, "state": sorted(app.state._state)}


def test_golden_fixture_is_the_pre_refactor_surface():
    # A truncated golden would make every comparison below vacuous.
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(golden["routes"]) == 319
    assert len(golden["state"]) == 142


@pytest.mark.parametrize(
    "extra",
    [{}, IDENTITY_BINDING],
    ids=["A_minimal", "B_identity_binding"],
)
def test_build_app_surface_matches_the_pre_refactor_golden(
    tmp_path, monkeypatch, extra
):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    _isolate_environment(monkeypatch)
    _local_environment(monkeypatch, tmp_path, **extra)

    app = local_cpython.build_app()

    assert _app_surface(app) == golden


def test_entry_guard_rejects_a_run_with_no_flag(tmp_path, monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))

    with pytest.raises(ConfigError) as error:
        local_cpython.build_app()

    assert str(error.value) == (
        "app.local_cpython is the explicit CPython entry point: "
        "PADIEM_LOCAL_DEV=1 for a loopback dev run, or "
        "PADIEM_CHAT_CPYTHON_HOST=1 for the COM2 parallel host "
        "(see tools/run_chat_local_cpython.py / deploy/host-com2/chat)"
    )


def test_local_flag_that_never_reached_settings_is_a_boot_error(
    tmp_path, monkeypatch
):
    class _SettingsThatLostTheFlag:
        """Represents the from_env regression the guard exists for."""

        @staticmethod
        def from_env() -> Settings:
            return Settings(
                runtime_mode="mock",
                auth_mode="off",
                public_base_url="https://chat.example.com",
                local_dev=False,
            )

    _isolate_environment(monkeypatch)
    _local_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(local_cpython, "Settings", _SettingsThatLostTheFlag)

    with pytest.raises(ConfigError) as error:
        local_cpython.build_app()

    assert str(error.value) == (
        "PADIEM_LOCAL_DEV did not reach Settings — from_env regression"
    )


def test_host_run_never_mixes_with_the_local_flag(tmp_path, monkeypatch):
    _isolate_environment(monkeypatch)
    _local_environment(
        monkeypatch,
        tmp_path,
        PADIEM_CHAT_CPYTHON_HOST="1",
        PADIEM_CHAT_PUBLIC_BASE_URL="https://chat.example.com",
    )

    with pytest.raises(ConfigError) as error:
        local_cpython.build_app()

    assert str(error.value) == "host runs must not set PADIEM_LOCAL_DEV"


def test_host_run_requires_an_https_public_base(tmp_path, monkeypatch):
    _isolate_environment(monkeypatch)
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "mock")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef"
    )

    with pytest.raises(ConfigError) as error:
        local_cpython.build_app()

    assert str(error.value) == (
        "PADIEM_CHAT_PUBLIC_BASE_URL must be https on the CPython host"
    )
