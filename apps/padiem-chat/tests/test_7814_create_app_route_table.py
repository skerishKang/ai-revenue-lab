"""R7-1 create_app 라우트 등록 나누기 증거 시험 (#7814).

리팩터 전후 동일을 고정한다: 라우트 표(메서드·경로·핸들러), 미들웨어 순서,
대표 요청(health·로그인 필요 401·정적 파일). 골든 표는 리팩터 전 origin/main
(3726bd3f7)에서 생성한 값을 그대로 둔다. 등록 하나를 빼면 이 시험이 실패한다.
"""
from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from app.config import Settings
from app.app_factory import create_app
from _support import claw_route_identity_source as sheets

GOLDEN_PATH = Path(__file__).resolve().parent / "test_7814_create_app_route_table_golden.json"


class _AuthReadyStore:
    async def get_user(self, user_id):
        return None

    async def list_projects(self, user_id):
        return []


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="x.apps.googleusercontent.com",
        google_client_secret="y",
        session_secret="s" * 32,
    )


def _route_table(app):
    rows = []
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None:
            name = getattr(endpoint, "__name__", type(endpoint).__name__)
        else:
            inner = getattr(route, "app", None)
            name = type(inner).__name__ if inner is not None else "?"
        rows.append(
            {
                "type": type(route).__name__,
                "path": getattr(route, "path", "?"),
                "methods": sorted(getattr(route, "methods", None) or []),
                "endpoint": name,
            }
        )
    return rows


def _app():
    return create_app(settings=_settings(), history_store=_AuthReadyStore())


def test_route_table_is_identical_to_golden() -> None:
    app = _app()
    golden = json.loads(sheets.support_source("test_7814_create_app_route_table_golden.json"))
    assert _route_table(app) == golden


def test_middleware_order_unchanged() -> None:
    app = _app()
    assert [m.cls.__name__ for m in app.user_middleware] == [
        "RequestTelemetryMiddleware",
        "SameOriginGuardMiddleware",
        "SessionRevocationGuardMiddleware",
    ]


def test_representative_requests_unchanged() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["runtime"] == "mock"
    denied = client.post("/api/projects", json={"name": "점검"}, headers={"Origin": "http://testserver"})
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "unauthorized"
    static = client.get("/")
    assert static.status_code == 200
    assert "text/html" in static.headers.get("content-type", "")
    assert "<html" in static.text[:200].lower()
