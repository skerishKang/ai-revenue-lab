from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import PADIEM_CHAT_PRODUCT_ID
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.usage_gate import InMemoryUsageCounterStore, UsageDecision
from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    CanonicalSubjectRef,
    SubjectType,
)

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


@contextmanager
def _injected_adapter(test_client: TestClient, adapter: object):
    """Bind a Worker-native Claw P01 adapter on app.state for the request (#2229).

    Replaces the removed ``p01_adapter_from_environment`` env path: the execute
    route now reads ``request.app.state.claw_p01_adapter``. Passing ``None``
    models an unconfigured Worker (fail-closed 503).
    """
    previous = test_client.app.state.claw_p01_adapter
    test_client.app.state.claw_p01_adapter = adapter
    try:
        yield adapter
    finally:
        test_client.app.state.claw_p01_adapter = previous


def _make_workspace_store() -> MagicMock:
    store = MagicMock()
    metadata = MagicMock()
    metadata.document_id = "doc_test1234567890abcdef1234567890ab"
    metadata.tenant_id = "tenant_test"
    metadata.filename = "견적서.docx"
    metadata.media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    metadata.byte_length = 1024
    metadata.public_projection.return_value = {
        "document_id": metadata.document_id,
        "filename": metadata.filename,
        "media_type": metadata.media_type,
        "byte_length": metadata.byte_length,
    }
    store.put_generated_docx = AsyncMock(return_value=metadata)
    store.get_for_tenant = AsyncMock(return_value=(metadata, b"fake docx content"))
    return store


def _make_identity_shadow_store(**overrides) -> MagicMock:
    store = MagicMock()
    now = datetime.now(timezone.utc)
    values = {
        "product_user_id": "usr_" + "7" * 32,
        "canonical_subject_id": "subject_test",
        "auth_session_id": "session_test123",
        "session_revision": 1,
        "session_state": "active",
        "session_expires_at": now + timedelta(hours=1),
        "observed_at": now,
    }
    values.update(overrides)
    record = IdentityShadowRecord(**values)
    store.load_projection = AsyncMock(return_value=record)
    return store


def _make_auth_session_snapshot(**overrides) -> AuthSessionSnapshot:
    now = datetime.now(timezone.utc)
    values = {
        "session_id": "session_test123",
        "product_id": PADIEM_CHAT_PRODUCT_ID,
        "subject": CanonicalSubjectRef(SubjectType.USER, "subject_test"),
        "issued_at": now - timedelta(hours=1),
        "expires_at": now + timedelta(hours=1),
        "state": AuthSessionState.ACTIVE,
        "revision": 1,
        "tenant_id": "tenant_test",
    }
    values.update(overrides)
    return AuthSessionSnapshot(**values)


def _make_authority(snapshot: AuthSessionSnapshot | MagicMock | None = None) -> MagicMock:
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(
        return_value=snapshot if snapshot is not None else _make_auth_session_snapshot()
    )
    return authority


def _app_with_identity(**overrides) -> MagicMock:
    """Create an app with identity shadow store + CP authority for artifact tests."""
    values = {
        "runtime_mode": "mock",
        "live_enabled": "false",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "test-client-id",
        "google_client_secret": "test-client-secret",
        "session_secret": "claw-gate-session-secret-not-a-real-credential-0",
        "session_max_age_seconds": "3600",
    }
    values.update(overrides)
    settings = Settings.from_values(**values)
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        d1_binding=MagicMock(),
        r2_binding=MagicMock(),
    )
    app.state.identity_shadow_store = _make_identity_shadow_store()
    app.state.control_plane_identity_authority = _make_authority()
    return app


def _signed_in_client(**overrides) -> TestClient:
    app = _app_with_identity(**overrides)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def _google_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-gate-client.apps.googleusercontent.com",
        "google_client_secret": "claw-gate-google-secret",
        "session_secret": "claw-gate-session-secret-not-a-real-credential-0",
        "session_max_age_seconds": 3600,
    }
    values.update(overrides)
    return Settings.from_values(**values)


SIGNED_IN_USER_ID = "usr_" + "7" * 32
TRUSTED_IP = "203.0.113.77"


def test_valid_quote_executes_through_p01_chain() -> None:
    workspace_store = _make_workspace_store()
    app = _app_with_identity()
    app.state.workspace_document_store = workspace_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A업체",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "result" in data
    assert data["result"]["result_text"] == "test result"
    assert data["result"]["action"] == "quote_draft"
    assert "artifact" in data["result"]
    assert "document_id" in data["result"]["artifact"]
    assert "artifact_token" not in data["result"]
    assert data["result"]["artifact"]["document_id"].startswith("doc_")
    assert data["result"]["artifact"]["media_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert isinstance(data["result"]["artifact"]["byte_length"], int)
    assert data["result"]["artifact"]["byte_length"] > 0


def test_valid_order_executes_through_p01_chain() -> None:
    workspace_store = _make_workspace_store()
    app = _app_with_identity()
    app.state.workspace_document_store = workspace_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "가상 테스트: B업체 발주 요청.",
                "channel": "email",
                "action": "order",
                "sender_hint": "B업체",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"]["action"] == "order_draft"
    assert "artifact" in data["result"]
    assert "document_id" in data["result"]["artifact"]
    assert "artifact_token" not in data["result"]


def test_valid_reply_executes_through_p01_chain(client: TestClient) -> None:
    with _injected_adapter(client, _make_adapter()):
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
    with _injected_adapter(client, _make_adapter()):
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
    assert "artifact" not in data["result"]


def test_quote_artifact_download_by_document_id() -> None:
    workspace_store = _make_workspace_store()
    app = _app_with_identity()
    app.state.workspace_document_store = workspace_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "가상 테스트: A업체 견적서 요청.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A업체",
            }
            execute_resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert execute_resp.status_code == 200
    execute_data = execute_resp.json()
    assert "artifact" in execute_data["result"]
    document_id = execute_data["result"]["artifact"]["document_id"]
    assert document_id

    download_resp = test_client.get(f"/api/claw/manual-intake/artifact/{document_id}")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert "attachment" in download_resp.headers.get("content-disposition", "")
    assert len(download_resp.content) > 0
    assert download_resp.headers["cache-control"] == "no-store, max-age=0"


def test_artifact_download_invalid_document_id_fails_closed(client: TestClient) -> None:
    resp = client.get("/api/claw/manual-intake/artifact/invalid!docid")
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


def test_artifact_download_not_found_returns_404() -> None:
    app = _app_with_identity()
    workspace_store = _make_workspace_store()
    workspace_store.get_for_tenant = AsyncMock(return_value=None)
    app.state.workspace_document_store = workspace_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        resp = test_client.get("/api/claw/manual-intake/artifact/doc_nonexistent1234567890abcdef12345")
    assert resp.status_code == 404


def test_quote_artifact_failure_fail_closed() -> None:
    from kagent.document_export import DocumentExportError
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "가상 테스트: A업체 견적서 요청.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A업체",
            }
            with patch("app.claw_routes.build_document_artifact", side_effect=DocumentExportError("export_failed", "export failed")):
                resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 500
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "artifact_generation_failed"


def test_quote_no_tenant_fails_closed(client: TestClient) -> None:
    with _injected_adapter(client, _make_adapter()):
        payload = {
            "content": "가상 테스트: A업체 견적서 요청.",
            "channel": "kakao",
            "action": "quote",
            "sender_hint": "A업체",
        }
        resp = client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 503
    data = resp.json()
    assert data["error"]["code"] in ("workspace_scope_unavailable", "workspace_storage_unavailable")


def test_quote_workspace_store_unavailable_fails_closed() -> None:
    app = _app_with_identity()
    del app.state.workspace_document_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            resp = test_client.post(
                EXECUTE_ROUTE_PATH,
                json={"content": "test", "channel": "kakao", "action": "quote"},
            )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_storage_unavailable"


def test_browser_payload_cannot_set_provider_or_model() -> None:
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    adapter = _make_adapter()
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, adapter):
            payload = {
                "content": "테스트",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A",
                "provider": "evil-provider",
                "model": "evil-model",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    adapter.execute.assert_awaited_once()


def test_browser_payload_cannot_supply_engine_credential() -> None:
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "테스트",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A",
                "engine_credential": "secret123",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "secret123" not in str(data)


def test_missing_engine_configuration_fails_closed(client: TestClient) -> None:
    assert client.app.state.claw_p01_adapter is None
    with _injected_adapter(client, None):
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
    with _injected_adapter(client, adapter):
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
    with _injected_adapter(client, adapter):
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


def test_no_auto_send_or_connector_write() -> None:
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            payload = {
                "content": "테스트",
                "channel": "kakao",
                "action": "quote",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
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
    with _injected_adapter(client, None):
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
    with _injected_adapter(client, adapter):
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
    with _injected_adapter(client, None):
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


def test_execute_button_exists_in_served_html() -> None:
    line = next(line for line in INDEX_HTML.splitlines() if 'id="clawExecuteButton"' in line)
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


# ── B62 UsageGate boundary on the real-execution path ──────────────────────


QUOTA_SALT = "claw-gate-quota-salt-not-a-real-secret-000001"
SESSION_SECRET = "claw-gate-session-secret-not-a-real-credential-0"
SIGNED_IN_USER_ID = "usr_" + "7" * 32
TRUSTED_IP = "203.0.113.77"
PREVIEW_ROUTE_PATH = "/api/claw/manual-intake/preview"
GATE_PAYLOAD = {
    "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
    "channel": "kakao",
    "action": "quote",
    "sender_hint": "A업체",
}


class RecordingUsageGate:
    def __init__(self, decision: UsageDecision) -> None:
        self.decision = decision
        self.calls: list[dict[str, str | None]] = []

    async def authorize(self, *, raw_ip: str | None, user_id: str | None) -> UsageDecision:
        self.calls.append({"raw_ip": raw_ip, "user_id": user_id})
        return self.decision


def _denied_decision() -> UsageDecision:
    return UsageDecision(
        allowed=False,
        code="rate_limited",
        status_code=429,
        user_message="요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
        retry_after_seconds=37,
    )


def _allowed_decision() -> UsageDecision:
    return UsageDecision(allowed=True, subject_type="user")


def _gated_app(
    gate: RecordingUsageGate,
    *,
    settings: Settings | None = None,
    history_store: object | None = None,
    identity_shadow_store: object | None = None,
    control_plane_identity_authority: object | None = None,
    workspace_document_store: object | None = None,
):
    app = create_app(
        settings or Settings.from_values(runtime_mode="mock", live_enabled="false", auth_mode="off"),
        history_store=history_store,
    )
    app.state.usage_gate = gate
    app.state.usage_gate_enforced = True
    if identity_shadow_store is not None:
        app.state.identity_shadow_store = identity_shadow_store
    if control_plane_identity_authority is not None:
        app.state.control_plane_identity_authority = control_plane_identity_authority
    if workspace_document_store is not None:
        app.state.workspace_document_store = workspace_document_store
    return app


def _live_quota_settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "b14",
        "b14_base_url": "https://b14.example",
        "quota_salt": QUOTA_SALT,
        "anonymous_burst_limit": 2,
        "anonymous_daily_limit": 20,
        "user_burst_limit": 8,
        "user_daily_limit": 100,
        "global_daily_limit": 1000,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _PresenceOnlyHistoryStore:
    """auth_ready() only requires that a history store is bound."""

    async def get_user(self, user_id: str):
        return None


def test_execute_is_denied_before_p01_transport_when_usage_gate_denies() -> None:
    gate = RecordingUsageGate(_denied_decision())
    adapter = _make_adapter()
    with TestClient(_gated_app(gate)) as client, _injected_adapter(client, adapter):
        resp = client.post(EXECUTE_ROUTE_PATH, json=GATE_PAYLOAD, headers={"cf-connecting-ip": TRUSTED_IP})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "37"
    assert resp.json()["ok"] is False
    assert resp.json()["error"]["code"] == "rate_limited"
    adapter.execute.assert_not_called()
    assert len(gate.calls) == 1


def test_execute_denial_holds_even_when_the_engine_is_fully_configured() -> None:
    gate = RecordingUsageGate(_denied_decision())
    adapter = _make_adapter()
    with TestClient(_gated_app(gate)) as client, _injected_adapter(client, adapter):
        resp = client.post(EXECUTE_ROUTE_PATH, json=GATE_PAYLOAD, headers={"cf-connecting-ip": TRUSTED_IP})
    assert resp.status_code == 429
    adapter.execute.assert_not_called()


def test_execute_identity_is_server_derived_and_body_identity_is_ignored() -> None:
    gate = RecordingUsageGate(_allowed_decision())
    spoofed = dict(GATE_PAYLOAD, action="reply", user_id="attacker-chosen-uid", ip="198.51.100.244", raw_ip="198.51.100.244")
    with TestClient(_gated_app(gate)) as client, _injected_adapter(client, _make_adapter()):
        resp = client.post(EXECUTE_ROUTE_PATH, json=spoofed, headers={"cf-connecting-ip": TRUSTED_IP})
    assert resp.status_code == 200
    assert gate.calls == [{"raw_ip": TRUSTED_IP, "user_id": None}]


def test_signed_in_execute_authorizes_with_the_session_user_id() -> None:
    settings = _google_settings()
    gate = RecordingUsageGate(_allowed_decision())
    app = _gated_app(
        gate,
        settings=settings,
        history_store=_PresenceOnlyHistoryStore(),
        identity_shadow_store=_make_identity_shadow_store(),
        control_plane_identity_authority=_make_authority(),
        workspace_document_store=_make_workspace_store(),
    )
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(client, _make_adapter()):
            resp = client.post(
                EXECUTE_ROUTE_PATH,
                json=dict(GATE_PAYLOAD, user_id="attacker-chosen-uid"),
                headers={"cf-connecting-ip": TRUSTED_IP},
            )
    assert resp.status_code == 200
    assert gate.calls == [{"raw_ip": TRUSTED_IP, "user_id": SIGNED_IN_USER_ID}]


def test_anonymous_execute_is_burst_bounded_per_trusted_ip_with_the_real_usage_gate() -> None:
    store = InMemoryUsageCounterStore()
    app = create_app(_live_quota_settings(), usage_store=store)
    assert app.state.usage_gate_enforced is True
    adapter = _make_adapter()
    with TestClient(app) as client, _injected_adapter(client, adapter):
        first = client.post(EXECUTE_ROUTE_PATH, json=dict(GATE_PAYLOAD, action="reply"), headers={"cf-connecting-ip": TRUSTED_IP})
        second = client.post(EXECUTE_ROUTE_PATH, json=dict(GATE_PAYLOAD, action="reply"), headers={"cf-connecting-ip": TRUSTED_IP})
        third = client.post(EXECUTE_ROUTE_PATH, json=dict(GATE_PAYLOAD, action="reply"), headers={"cf-connecting-ip": TRUSTED_IP})
        other_ip = client.post(EXECUTE_ROUTE_PATH, json=dict(GATE_PAYLOAD, action="reply"), headers={"cf-connecting-ip": "192.0.2.9"})
    assert (first.status_code, second.status_code) == (200, 200)
    assert third.status_code == 429
    assert third.headers["retry-after"]
    assert other_ip.status_code == 200
    assert adapter.execute.await_count == 3


def test_execute_fails_closed_when_live_identity_or_gate_is_unavailable() -> None:
    store = InMemoryUsageCounterStore()
    app = create_app(_live_quota_settings(), usage_store=store)
    adapter = _make_adapter()
    with TestClient(app) as client, _injected_adapter(client, adapter):
        no_identity = client.post(EXECUTE_ROUTE_PATH, json=GATE_PAYLOAD)
    assert no_identity.status_code == 503
    assert no_identity.json()["error"]["code"] == "live_identity_unavailable"
    adapter.execute.assert_not_called()

    unbound = create_app(_live_quota_settings())
    assert unbound.state.usage_gate_enforced is True
    adapter2 = _make_adapter()
    with TestClient(unbound) as client, _injected_adapter(client, adapter2):
        no_gate = client.post(EXECUTE_ROUTE_PATH, json=GATE_PAYLOAD, headers={"cf-connecting-ip": TRUSTED_IP})
    assert no_gate.status_code == 503
    assert no_gate.json()["error"]["code"] == "live_abuse_gate_unavailable"
    adapter2.execute.assert_not_called()


def test_quota_denial_does_not_expose_internal_quota_state() -> None:
    gate = RecordingUsageGate(_denied_decision())
    with TestClient(_gated_app(gate)) as client, _injected_adapter(client, _make_adapter()):
        resp = client.post(EXECUTE_ROUTE_PATH, json=GATE_PAYLOAD, headers={"cf-connecting-ip": TRUSTED_IP})
    body = resp.text
    assert TRUSTED_IP not in body
    assert QUOTA_SALT not in body
    for internal in ("anon_", "burst", "daily", "subject_type", "bucket"):
        assert internal not in body
    assert resp.headers["cache-control"] == "no-store, max-age=0"


def test_preview_never_calls_the_usage_gate_or_the_p01_adapter() -> None:
    gate = RecordingUsageGate(_denied_decision())
    adapter = _make_adapter()
    with TestClient(_gated_app(gate)) as client, _injected_adapter(client, adapter):
        resp = client.post(PREVIEW_ROUTE_PATH, json=GATE_PAYLOAD, headers={"cf-connecting-ip": TRUSTED_IP})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert gate.calls == []
    adapter.execute.assert_not_called()


def test_usage_gate_is_applied_before_p01_adapter_construction() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "claw_routes.py").read_text(encoding="utf-8")
    execute_handler = source.split("async def claw_manual_intake_execute", 1)[1]
    assert "_usage_gate_denial(request)" in execute_handler
    assert "claw_p01_adapter" in execute_handler
    assert execute_handler.index("_usage_gate_denial(request)") < execute_handler.index(
        'request.app.state, "claw_p01_adapter"'
    )
    assert "p01_adapter_from_environment" not in source
    preview_handler = source.split("async def claw_manual_intake_preview", 1)[1].split(
        "async def claw_manual_intake_execute", 1
    )[0]
    assert "_usage_gate_denial" not in preview_handler
    gate_helper = source.split("async def _usage_gate_denial", 1)[1].split("async def", 1)[0]
    assert 'request.headers.get("cf-connecting-ip")' in gate_helper
    assert "current_user_id(request)" in gate_helper
    assert "request.body" not in gate_helper


# ── #2227 canonical tenant session-validation hardening (deny matrix) ──────


QUOTE_PAYLOAD = {
    "content": "가상 테스트: A업체 견적서 요청.",
    "channel": "kakao",
    "action": "quote",
    "sender_hint": "A업체",
}


def _execute_quote_with_identity(
    *,
    snapshot: object | None = None,
    shadow_store: MagicMock | None = None,
) -> TestClient:
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    if shadow_store is not None:
        app.state.identity_shadow_store = shadow_store
    if snapshot is not None:
        app.state.control_plane_identity_authority = _make_authority(snapshot)  # type: ignore[arg-type]
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def _post_quote(client: TestClient):
    with _injected_adapter(client, _make_adapter()):
        return client.post(EXECUTE_ROUTE_PATH, json=QUOTE_PAYLOAD)


def test_canonical_tenant_accepts_fully_validated_session() -> None:
    client = _execute_quote_with_identity()
    resp = _post_quote(client)
    assert resp.status_code == 200
    assert resp.json()["result"]["artifact"]["document_id"]


@pytest.mark.parametrize(
    ("scenario", "snapshot", "shadow_overrides"),
    [
        (
            "revoked",
            lambda: _make_auth_session_snapshot(state=AuthSessionState.REVOKED),
            {},
        ),
        (
            "expired_state",
            lambda: _make_auth_session_snapshot(state=AuthSessionState.EXPIRED),
            {},
        ),
        (
            "expired_clock",
            lambda: _make_auth_session_snapshot(
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            ),
            {},
        ),
        (
            "product_mismatch",
            lambda: _make_auth_session_snapshot(product_id="b99"),
            {},
        ),
        (
            "subject_id_mismatch",
            lambda: _make_auth_session_snapshot(
                subject=CanonicalSubjectRef(SubjectType.USER, "subject_attacker")
            ),
            {},
        ),
        (
            "subject_type_not_user",
            lambda: _make_auth_session_snapshot(
                subject=CanonicalSubjectRef(SubjectType.ANONYMOUS, "subject_test")
            ),
            {},
        ),
        (
            "session_id_mismatch",
            lambda: _make_auth_session_snapshot(session_id="session_attacker"),
            {},
        ),
        (
            "revision_rollback",
            lambda: _make_auth_session_snapshot(revision=1),
            {"session_revision": 2},
        ),
        (
            "invalid_snapshot_type",
            lambda: MagicMock(),
            {},
        ),
        (
            "snapshot_without_tenant",
            lambda: _make_auth_session_snapshot(tenant_id=None),
            {},
        ),
    ],
    ids=[
        "revoked",
        "expired_state",
        "expired_clock",
        "product_mismatch",
        "subject_id_mismatch",
        "subject_type_not_user",
        "session_id_mismatch",
        "revision_rollback",
        "invalid_snapshot_type",
        "snapshot_without_tenant",
    ],
)
def test_canonical_tenant_denies_contract_violations(scenario, snapshot, shadow_overrides) -> None:
    del scenario
    shadow_store = _make_identity_shadow_store(**shadow_overrides) if shadow_overrides else None
    client = _execute_quote_with_identity(
        snapshot=snapshot(),
        shadow_store=shadow_store,
    )
    resp = _post_quote(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_scope_unavailable"


def test_canonical_tenant_denies_when_authority_raises() -> None:
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    authority = MagicMock()
    authority.resolve_auth_session = AsyncMock(side_effect=RuntimeError("authority down"))
    app.state.control_plane_identity_authority = authority
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    resp = _post_quote(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_scope_unavailable"


def test_quote_identity_shadow_unavailable_fails_closed() -> None:
    # Auth is enabled and a valid session cookie is present, but the identity
    # shadow store is not bound on the Worker: canonical tenant resolution must
    # fail closed (503) rather than store a document under an unverifiable tenant.
    app = _app_with_identity()
    app.state.workspace_document_store = _make_workspace_store()
    app.state.identity_shadow_store = None
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_google_settings(), SIGNED_IN_USER_ID),
        domain="chat.example.test",
        path="/",
    )
    resp = _post_quote(client)
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "workspace_scope_unavailable"


def test_quote_storage_write_failure_fails_closed() -> None:
    # A private artifact write (R2/D1) failure must surface as a storage error,
    # not leak a document id or return a raw traceback, and must not be reported
    # as the distinct generation failure.
    app = _app_with_identity()
    workspace_store = _make_workspace_store()
    workspace_store.put_generated_docx = AsyncMock(
        side_effect=RuntimeError("workspace document storage failed")
    )
    app.state.workspace_document_store = workspace_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        with _injected_adapter(test_client, _make_adapter()):
            resp = test_client.post(EXECUTE_ROUTE_PATH, json=QUOTE_PAYLOAD)
    assert resp.status_code == 500
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "artifact_storage_failed"
    assert "document_id" not in data.get("result", {})


def test_resolve_canonical_tenant_uses_shared_refreshed_session_contract() -> None:
    source = (Path(__file__).resolve().parents[1] / "app" / "claw_routes.py").read_text(encoding="utf-8")
    helper = source.split("async def _resolve_canonical_tenant", 1)[1].split("async def", 1)[0]
    assert "resolve_refreshed_session(" in helper
    assert 'request.headers.get("x-tenant-id")' not in helper
    assert "data.get(" not in helper
    shadow_source = (
        Path(__file__).resolve().parents[1] / "app" / "control_plane_identity_shadow.py"
    ).read_text(encoding="utf-8")
    resolver_body = shadow_source.split("class RefreshingCanonicalSubjectResolver", 1)[1].split(
        "async def resolve_refreshed_session", 1
    )[0]
    assert "resolve_refreshed_session(" in resolver_body
