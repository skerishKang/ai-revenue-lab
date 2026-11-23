"""R7-1 create_app 상태 초기화 나누기 증거 시험 (#7814).

리팩터 전후 동일을 고정한다: app.state에 붙는 이름과 각 값의 타입 이름,
시작/종료 훅 순서. 골든 표는 리팩터 전 origin/main(449991347)에서 생성한
값을 그대로 둔다. 상태 초기화 하나를 빼면 이 시험이 실패한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings
from app.app_factory import create_app
from app.lifespan_hooks import lifespan_hooks

GOLDEN_PATH = Path(__file__).resolve().parent / "test_7814_create_app_state_table_golden.json"


class _AuthReadyStore:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []


class _FakeD1:
    def prepare(self, *args, **kwargs):  # pragma: no cover - never called here
        raise AssertionError("prepare is not called during create_app")

    def batch(self, *args, **kwargs):  # pragma: no cover - never called here
        raise AssertionError("batch is not called during create_app")


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="x.apps.googleusercontent.com",
        google_client_secret="y",
        session_secret="s" * 32,
    )


def _state_table(app):
    # app.state iteration is insertion-ordered: the recorded order is part of
    # the pre-refactor contract, so one reordered assignment also fails here.
    return [
        {"name": name, "type": type(app.state[name]).__name__} for name in app.state
    ]


def _hook_names(app):
    def _names(hooks):
        return [getattr(hook, "__name__", type(hook).__name__) for hook in hooks]

    hooks = lifespan_hooks(app)
    return {"on_startup": _names(hooks.on_startup), "on_shutdown": _names(hooks.on_shutdown)}


def test_state_table_is_identical_to_golden() -> None:
    app = create_app(settings=_settings(), history_store=_AuthReadyStore())
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert _state_table(app) == golden


def test_startup_and_shutdown_hooks_unchanged() -> None:
    app = create_app(settings=_settings(), history_store=_AuthReadyStore())
    assert _hook_names(app) == {"on_startup": [], "on_shutdown": []}


def test_shutdown_hook_with_document_convert_store_unchanged() -> None:
    app = create_app(
        settings=_settings(), history_store=_AuthReadyStore(), d1_binding=_FakeD1()
    )
    assert _hook_names(app) == {
        "on_startup": [],
        "on_shutdown": ["drain_background_runs"],
    }
