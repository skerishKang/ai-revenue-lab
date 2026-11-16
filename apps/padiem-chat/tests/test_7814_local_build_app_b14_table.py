"""#7814 T4 — `build_app` 3/3b B14 전송·게이트 구간 골든 표.

`_install_local_b14_gate`로 옮긴 구간이 지키던 계약을 리팩터링 전 `main`의
실행 결과 그대로 고정한다. 값은 합성값이고 운영 비밀값·주소는 쓰지 않는다.

- B14 전송 켜짐/꺼짐 쌍(`mock_local` / `b14_local`): `app.state` 이름과
  대입 순서, B14 바인딩 종류가 실제로 갈리는지 함께 고정한다.
- 게이트 켜짐/꺼짐 쌍(`host_gates_off` / `edge_on` / `connector_on`):
  미들웨어 순서와 websocket 라우트 엔드포인트가 실제로 갈리는지 고정한다.
- 거절 경로: 옮긴 구간의 `raise` 6개는 예외 종류와 문구를 원래 그대로 비교한다.

골든은 같은 방식으로 리팩터링 전 `main`에서 먼저 떴다
(`fixtures/local_build_app_7814_b14.json`).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import app.local_cpython as local_cpython
import starlette.datastructures as state_module
from starlette.routing import WebSocketRoute

GOLDEN_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "local_build_app_7814_b14.json"
)

CLEAR_PREFIX = ("PADIEM_", "PC_QUEUE_", "B14_")

LOCAL_ENV = {
    "PADIEM_LOCAL_DEV": "1",
    "PADIEM_CHAT_RUNTIME_MODE": "mock",
    "PADIEM_CHAT_AUTH_MODE": "off",
    "PADIEM_CHAT_WEB_PROVIDER": "off",
    "PADIEM_CHAT_PUBLIC_BASE_URL": "http://127.0.0.1:8773",
    "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
}

HOST_ENV = {
    "PADIEM_CHAT_CPYTHON_HOST": "1",
    "PADIEM_CHAT_RUNTIME_MODE": "mock",
    "PADIEM_CHAT_AUTH_MODE": "off",
    "PADIEM_CHAT_WEB_PROVIDER": "off",
    "PADIEM_CHAT_PUBLIC_BASE_URL": "https://chat-com2.padiem.net",
    "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
    "PADIEM_CHAT_LOOP_STALL_WATCHDOG": "off",
}

B14_ENV = {
    "PADIEM_CHAT_RUNTIME_MODE": "b14",
    "PADIEM_B14_SERVICE_PROOF_SECRET": "synthetic-b14-proof-secret-0123456789abcdef",
    "B14_UPSTREAM_MODE": "loopback",
    "B14_UPSTREAM_URL": "http://127.0.0.1:8789",
}

B14_KEYS = (
    "b14_client",
    "grounded_chat",
    "claw_live_sse_enabled",
    "b66_quote_model_resolver",
    "b14_model_choice_resolver",
    "b66_reasoning_transport_supported",
    "b66_quote_interpreter",
    "b14_slot_status_source",
    "b14_model_ops_source",
)

ORDER_CASES = ("mock_local", "b14_local")


def _case_env(label: str, tmp_path: Path) -> dict:
    edge = tmp_path / "edge.secret"
    edge.write_text("synthetic-edge-secret-0123456789", encoding="utf-8")
    identity = tmp_path / "identity.secret"
    identity.write_text("synthetic-identity-secret-0123456789", encoding="utf-8")
    broker = tmp_path / "broker.secret"
    broker.write_text("synthetic-broker-secret-0123456789", encoding="utf-8")
    gate_files = {
        "PADIEM_COM2_EDGE_SECRET_FILE": str(edge),
        "PADIEM_COM2_EDGE_REPLAY_DB": str(tmp_path / "replay.sqlite3"),
    }
    gateway_files = {
        "PADIEM_COM2_IDENTITY_RPC_SECRET_FILE": str(identity),
        "PADIEM_COM2_BROKER_RPC_SECRET_FILE": str(broker),
    }
    cases = {
        "mock_local": (LOCAL_ENV, {}),
        "b14_local": (LOCAL_ENV, B14_ENV),
        "edge_no_host": (LOCAL_ENV, {"PADIEM_COM2_EDGE_PROOF_REQUIRED": "1"}),
        "connector_no_host": (LOCAL_ENV, {"PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED": "1"}),
        "host_gates_off": (HOST_ENV, {}),
        "edge_secret_required": (HOST_ENV, {"PADIEM_COM2_EDGE_PROOF_REQUIRED": "1"}),
        "edge_secret_unreadable": (
            HOST_ENV,
            {
                "PADIEM_COM2_EDGE_PROOF_REQUIRED": "1",
                "PADIEM_COM2_EDGE_SECRET_FILE": str(tmp_path / "absent.secret"),
            },
        ),
        "edge_on": (HOST_ENV, {"PADIEM_COM2_EDGE_PROOF_REQUIRED": "1", **gate_files}),
        "connector_secret_required": (HOST_ENV, {"PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED": "1"}),
        "connector_on": (
            HOST_ENV,
            {
                "PADIEM_COM2_CONNECTOR_GATEWAY_ENABLED": "1",
                **gate_files,
                **gateway_files,
            },
        ),
    }
    base, extra = cases[label]
    values = dict(base, PADIEM_CHAT_LOCAL_DATA_DIR=str(tmp_path))
    values.update(extra)
    return values


def _record_state_order(monkeypatch: pytest.MonkeyPatch) -> list:
    order: list = []
    original = state_module.State.__setattr__

    def _record(self, key, value):
        order.append(key)
        original(self, key, value)

    monkeypatch.setattr(state_module.State, "__setattr__", _record)
    return order


def snapshot(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Run one case and reduce it to the contract the extracted helper owns."""
    for name in tuple(os.environ):
        if name.startswith(CLEAR_PREFIX):
            monkeypatch.delenv(name)
    for name, value in _case_env(label, tmp_path).items():
        monkeypatch.setenv(name, value)

    order = _record_state_order(monkeypatch) if label in ORDER_CASES else None
    try:
        app = local_cpython.build_app()
    except Exception as exc:
        return {"outcome": "raise", "error": f"{type(exc).__name__}: {exc}"}

    state = app.state._state
    result = {
        "outcome": "ok",
        "state_count": len(state),
        "state": sorted(state),
        "b14_bindings": {
            key: (type(state[key]).__name__ if state.get(key) is not None else "None")
            for key in B14_KEYS
            if key in state
        },
        "middleware": [item.cls.__name__ for item in app.user_middleware],
        "ws_routes": [
            [route.path, getattr(route.endpoint, "__name__", "?")]
            for route in app.router.routes
            if isinstance(route, WebSocketRoute)
        ],
    }
    if order is not None:
        result["order"] = order
    return result


def test_golden_is_the_pre_refactor_b14_table():
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert set(golden) == {
        "mock_local", "b14_local", "edge_no_host", "connector_no_host",
        "host_gates_off", "edge_secret_required", "edge_secret_unreadable",
        "edge_on", "connector_secret_required", "connector_on",
    }
    pair = golden["b14_local"]
    base = golden["mock_local"]
    assert pair["state_count"] > base["state_count"]
    assert set(pair["b14_bindings"]) - set(base["b14_bindings"])
    assert "EdgeProofMiddleware" in golden["edge_on"]["middleware"]
    assert "EdgeProofMiddleware" not in golden["host_gates_off"]["middleware"]
    assert golden["connector_on"]["ws_routes"] != golden["host_gates_off"]["ws_routes"]


@pytest.mark.parametrize(
    "label",
    [
        "mock_local", "b14_local", "edge_no_host", "connector_no_host",
        "host_gates_off", "edge_secret_required", "edge_secret_unreadable",
        "edge_on", "connector_secret_required", "connector_on",
    ],
)
def test_b14_gate_snapshot_matches_the_pre_refactor_golden(
    tmp_path, monkeypatch, label
):
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))[label]
    assert snapshot(label, tmp_path, monkeypatch) == golden
