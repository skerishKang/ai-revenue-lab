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
    assert len(golden["routes"]) == 341
    assert len(golden["state"]) == 147


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


# ---------------------------------------------------------------------------
# 2/3 — 저장소·서비스 바인딩(원래 328-424) 구간.
#
# 1/3의 입력 A·B는 라우트·state 이름이 같아 선택 바인딩 차이를 잡지 못했다.
# 이 표는 바인딩마다 "꺼짐/켜짐" 쌍을 두고, 그 쌍이 실제로 다른 값을 내는지
# 함께 확인한다. 골든은 같은 방식으로 리팩터링 전 main에서 먼저 떴다.
# ---------------------------------------------------------------------------
BINDINGS_GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "local_build_app_7814_bindings.json"
)

#: One toggle per binding this stage composes.
BINDING_TOGGLES = {
    "identity_on": IDENTITY_BINDING,
    "pdf_on": {
        "PADIEM_CHAT_LOCAL_B66_PDF_ORIGIN": "https://pdf.example",
        "PADIEM_CHAT_LOCAL_B66_PDF_SECRET": "local-service-secret-0123456789abcd",
    },
    "google_oauth_on": {
        "PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_ORIGIN": "https://oauth.example",
        "PADIEM_CHAT_LOCAL_GOOGLE_OAUTH_SECRET": "local-service-secret-0123456789abcd",
    },
    "voice_on": {
        "PADIEM_CHAT_VOICE_RPC_ORIGIN": "https://voice.example",
        "PADIEM_CHAT_VOICE_RPC_SECRET": "local-service-secret-0123456789abcd",
    },
    "github_on": {
        "PADIEM_GITHUB_APP_CLIENT_SECRET": "synthetic-github-app-secret-0123456789",
    },
}

#: The names this stage's bindings surface on the app, in observation order.
BINDING_KEYS = (
    "github_oauth_store",
    "github_oauth_provider",
    "b66_pdf_renderer_client",
    "control_plane_identity_authority",
    "google_oauth_workspace_truth",
    "voice_stt_transport",
    "identity_shadow_store",
)

#: What each pair must actually change. A pair that changed nothing would not
#: prove the branch it targets, so the difference itself is pinned here.
EXPECTED_BINDING_DIFF = {
    "identity_on": {"control_plane_identity_authority": "CachedIdentityAuthority"},
    "pdf_on": {"b66_pdf_renderer_client": "LocalB66PdfRendererClient"},
    "google_oauth_on": {
        "google_oauth_workspace_truth": "CloudflareGoogleOAuthWorkspaceTruth"
    },
    "voice_on": {"voice_stt_transport": "HostVoiceSttRpcTransport"},
    "github_on": {
        "github_oauth_store": "D1GitHubOAuthStore",
        "github_oauth_provider": "GitHubAppOAuthProvider",
    },
}

EXPECTED_STATE_DIFF = {
    "identity_on": set(),
    "pdf_on": set(),
    "google_oauth_on": set(),
    "voice_on": {"voice_stt_transport"},
    "github_on": set(),
}


def _binding_kinds(app: object) -> dict:
    state = app.state._state
    return {
        key: ("None" if state.get(key) is None else type(state[key]).__name__)
        for key in BINDING_KEYS
        if key in state
    }


def test_bindings_golden_is_the_pre_refactor_table():
    golden = json.loads(BINDINGS_GOLDEN_PATH.read_text(encoding="utf-8"))
    assert len(golden["routes"]) == 341
    assert set(golden["bindings"]) == {"base", *BINDING_TOGGLES}
    assert set(golden["states"]) == {"base", *BINDING_TOGGLES}
    # The voice lane is the only pair that changes the app.state NAME list.
    voice_extra = set(golden["states"]["voice_on"]) - set(golden["states"]["base"])
    assert sorted(voice_extra) == ["voice_stt_transport"]
    for label in BINDING_TOGGLES:
        extra = set(golden["states"][label]) - set(golden["states"]["base"])
        assert extra == EXPECTED_STATE_DIFF[label]


@pytest.mark.parametrize("label", ["base", *BINDING_TOGGLES])
def test_service_bindings_match_the_pre_refactor_golden(tmp_path, monkeypatch, label):
    golden = json.loads(BINDINGS_GOLDEN_PATH.read_text(encoding="utf-8"))
    _isolate_environment(monkeypatch)
    _local_environment(monkeypatch, tmp_path, **BINDING_TOGGLES.get(label, {}))

    app = local_cpython.build_app()

    assert _app_surface(app)["routes"] == golden["routes"]
    assert sorted(app.state._state) == golden["states"][label]
    assert _binding_kinds(app) == golden["bindings"][label]


@pytest.mark.parametrize("label", list(BINDING_TOGGLES))
def test_each_toggle_changes_the_table_it_claims_to_change(label):
    golden = json.loads(BINDINGS_GOLDEN_PATH.read_text(encoding="utf-8"))
    base_bindings = golden["bindings"]["base"]
    toggled_bindings = golden["bindings"][label]

    changed = {
        key
        for key in set(base_bindings) | set(toggled_bindings)
        if base_bindings.get(key) != toggled_bindings.get(key)
    }
    state_diff = set(golden["states"][label]) ^ set(golden["states"]["base"])

    assert changed == set(EXPECTED_BINDING_DIFF[label])
    assert state_diff == EXPECTED_STATE_DIFF[label]


# ---------------------------------------------------------------------------
# 3/3a — startup/shutdown 훅·캐시·메일·council·기기 저장소(원래 636-875) 구간.
#
# app.state 대입은 순서가 계약이다: 뒤 대입이 앞 대입을 읽는다. 그래서 이름
# 목록만이 아니라 "대입 순서"를 Starlette State.__setattr__ 기록으로 고정한다.
# 골든은 리팩터링 전 main에서 먼저 떴다(base·identity_on 두 입력).
# ---------------------------------------------------------------------------
STATE_ORDER_GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "local_build_app_7814_state_order.json"
)


def _record_state_order(monkeypatch: pytest.MonkeyPatch) -> list:
    import starlette.datastructures as state_module

    order: list = []
    original = state_module.State.__setattr__

    def _record(self, key, value):
        order.append(key)
        original(self, key, value)

    monkeypatch.setattr(state_module.State, "__setattr__", _record)
    return order


def test_state_order_golden_is_the_pre_refactor_order():
    golden = json.loads(STATE_ORDER_GOLDEN_PATH.read_text(encoding="utf-8"))
    # Re-assignment is part of the contract, so the raw list keeps duplicates.
    assert len(golden["base"]["order"]) == 152
    assert len(set(golden["base"]["order"])) == 147
    assert golden["base"]["order"] == golden["identity_on"]["order"]


@pytest.mark.parametrize(
    "label, extra",
    [("base", {}), ("identity_on", IDENTITY_BINDING)],
    ids=["base", "identity_on"],
)
def test_state_assignment_order_matches_the_pre_refactor_golden(
    tmp_path, monkeypatch, label, extra
):
    golden = json.loads(STATE_ORDER_GOLDEN_PATH.read_text(encoding="utf-8"))
    _isolate_environment(monkeypatch)
    _local_environment(monkeypatch, tmp_path, **extra)

    order = _record_state_order(monkeypatch)
    app = local_cpython.build_app()

    assert order == golden[label]["order"]
    assert sorted(app.state._state) == golden[label]["state"]
    assert _app_surface(app)["routes"] == golden[label]["routes"]
