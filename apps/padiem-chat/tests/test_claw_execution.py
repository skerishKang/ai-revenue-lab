from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.app_factory import create_app
from app.config import Settings

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
LOCALE_JS = (STATIC / "locale.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")

EXECUTE_ROUTE_PATH = "/api/claw/manual-intake/execute"


@pytest.fixture
def client() -> TestClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
    )
    app = create_app(settings=settings)
    return TestClient(app)


def _make_outcome(answer: str = "test result", status_value: str = "completed") -> MagicMock:
    status_mock = MagicMock()
    status_mock.value = status_value
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_test123"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_run_test123"
    outcome.p01_event_count = 2
    return outcome


def _make_adapter() -> MagicMock:
    adapter = MagicMock()
    adapter.execute = AsyncMock(return_value=_make_outcome())
    return adapter


def test_valid_quote_executes_through_p01_chain(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
            "channel": "kakao",
            "action": "quote",
            "sender_hint": "A업체",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "result" in data
    assert data["result"]["result_text"] == "test result"
    assert data["result"]["action"] == "quote_draft"


def test_valid_order_executes_through_p01_chain(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "가상 테스트: B업체 발주 요청.",
            "channel": "email",
            "action": "order",
            "sender_hint": "B업체",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["action"] == "order_draft"


def test_valid_reply_executes_through_p01_chain(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "답장 테스트 내용.",
            "channel": "sms",
            "action": "reply",
            "sender_hint": "C고객",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["action"] == "reply_draft"


def test_valid_summary_executes_through_p01_chain(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "요약 테스트 내용.",
            "channel": "telegram",
            "action": "summary",
            "sender_hint": "D고객",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["action"] == "summarize_request"


def test_browser_payload_cannot_set_provider_or_model(client: TestClient) -> None:
    adapter = _make_adapter()
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=adapter):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
            "sender_hint": "A",
            "provider": "evil-provider",
            "model": "evil-model",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    adapter.execute.assert_awaited_once()


def test_browser_payload_cannot_supply_engine_credential(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
            "sender_hint": "A",
            "engine_credential": "secret123",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "secret123" not in str(data)


def test_missing_engine_configuration_fails_closed(client: TestClient) -> None:
    from kagent.p01_adapter import P01AdapterError

    with patch("app.claw_routes.p01_adapter_from_environment", side_effect=P01AdapterError("p01_engine_not_configured", "Engine 클라이언트가 설정되지 않았습니다.")):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 503
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "engine_not_configured"


def test_engine_failure_projects_safe_error(client: TestClient) -> None:
    from kagent.p01_adapter import P01AdapterError

    adapter = _make_adapter()
    adapter.execute = AsyncMock(side_effect=P01AdapterError("p01_engine_request_failed", "P01 orchestration failed at the Engine boundary."))
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=adapter):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "engine_execution_failed"


def test_no_silent_preview_fallback_after_execute(client: TestClient) -> None:
    adapter = _make_adapter()
    adapter.execute = AsyncMock(return_value=_make_outcome(answer=None, status_value="failed"))
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=adapter):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False


def test_preview_route_remains_non_provider_if_preserved(client: TestClient) -> None:
    payload = {
        "content": "가상 테스트: 견적서 요청.",
        "channel": "kakao",
        "action": "quote",
        "sender_hint": "A업체",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "preview" in data
    assert data["preview"]["connector_required"] is False


def test_no_auto_send_or_connector_write(client: TestClient) -> None:
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=_make_adapter()):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["direct_kakao_send"] is False
    assert data["result"]["direct_sms_send"] is False
    assert data["result"]["connector_required"] is False


def test_untrusted_input_bounds_preserved(client: TestClient) -> None:
    payload = {
        "content": "A" * 5000,
        "channel": "kakao",
        "action": "quote",
    }
    resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "content_too_long"


def test_invalid_action_rejected(client: TestClient) -> None:
    payload = {
        "content": "테스트",
        "channel": "kakao",
        "action": "forbidden_action",
    }
    resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_action"


def test_invalid_channel_rejected(client: TestClient) -> None:
    payload = {
        "content": "테스트",
        "channel": "unsupported_channel",
        "action": "quote",
    }
    resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_channel"


def test_empty_content_rejected(client: TestClient) -> None:
    payload = {
        "content": "   ",
        "channel": "kakao",
        "action": "quote",
    }
    resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_content"


def test_non_json_request_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/claw/manual-intake/execute",
        content="not json",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 415
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "unsupported_media_type"


def test_oversized_body_rejected(client: TestClient) -> None:
    big_str = "x" * 70_000
    resp = client.post(
        "/api/claw/manual-intake/execute",
        content=f'{{"content": "{big_str}"}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 413)
    data = resp.json()
    assert data["ok"] is False


def test_engine_not_configured_returns_503(client: TestClient) -> None:
    from kagent.p01_adapter import P01AdapterError

    with patch("app.claw_routes.p01_adapter_from_environment", side_effect=P01AdapterError("p01_engine_misconfigured", "P01 Engine client is not configured")):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 503
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "engine_not_configured"


def test_engine_timeout_projects_safe_error(client: TestClient) -> None:
    from kagent.p01_adapter import P01AdapterError

    adapter = _make_adapter()
    adapter.execute = AsyncMock(side_effect=P01AdapterError("p01_engine_unreachable", "P01 Engine endpoint could not be reached."))
    with patch("app.claw_routes.p01_adapter_from_environment", return_value=adapter):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 502
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "engine_execution_failed"


def test_no_credential_raw_text_in_response(client: TestClient) -> None:
    from kagent.p01_adapter import P01AdapterError

    with patch("app.claw_routes.p01_adapter_from_environment", side_effect=P01AdapterError("p01_engine_misconfigured", "Missing P01_ENGINE_CREDENTIAL")):
        payload = {
            "content": "테스트",
            "channel": "kakao",
            "action": "quote",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 503
    data = resp.json()
    assert "P01_ENGINE_CREDENTIAL" not in str(data)
    assert "Missing" not in str(data)


# ── Web UI wiring contracts (#2215) ────────────────────────────────────────
# Guard against dead wiring: the execute handler must attach to an element that
# actually exists in the served HTML and must call the registered route.


def test_execute_button_exists_in_served_html() -> None:
    line = next(line for line in INDEX_HTML.splitlines() if 'id="clawExecuteButton"' in line)
    # type="button" keeps execution from submitting the deterministic preview form.
    assert 'type="button"' in line


def test_execute_handler_is_attached_in_app_js() -> None:
    assert 'document.getElementById("clawExecuteButton")' in APP_JS
    assert 'clawExecuteButton.addEventListener("click"' in APP_JS


def test_execute_handler_calls_a_registered_route(client: TestClient) -> None:
    registered = {getattr(route, "path", None) for route in client.app.routes}
    assert EXECUTE_ROUTE_PATH in registered
    assert f'fetch("{EXECUTE_ROUTE_PATH}"' in APP_JS


def test_execute_button_label_exists_in_both_locales() -> None:
    assert '"claw-btn-execute": "실제 실행"' in LOCALE_JS
    assert '"claw-btn-execute": "Run with real model"' in LOCALE_JS


def test_execute_button_meets_touch_target_contract() -> None:
    block = WORKSPACE_CSS.split(".claw-execute-button {", 1)[1].split("}", 1)[0]
    assert "min-height: 48px" in block


def test_executed_result_is_not_labelled_as_preview() -> None:
    assert 'id="clawResultBadge"' in INDEX_HTML
    assert "revealClawCard(result.title, true)" in APP_JS
    assert '"claw-result-badge-run": "실제 실행"' in LOCALE_JS
    assert '"claw-result-badge-run": "Real run"' in LOCALE_JS


def test_preview_path_still_uses_preview_label() -> None:
    assert "revealClawCard(preview.title)" in APP_JS
    assert 'data-locale-key="claw-result-badge"' in INDEX_HTML