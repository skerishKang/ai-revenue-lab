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
from app.workspace_storage import (
    DOCX_MEDIA_TYPE,
    WorkspaceDocumentStore,
    WorkspaceStorageError,
)
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
RUNS_HISTORY_ROUTE = "/api/claw/runs"


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
                "content": "가상 테스트: A 업체가 9 월 말까지 샘플 20 개 견적서를 요청함.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A 업체",
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
                "content": "가상 테스트: B 업체 발주 요청.",
                "channel": "email",
                "action": "order",
                "sender_hint": "B 업체",
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
            "sender_hint": "C 고객",
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
            "sender_hint": "D 고객",
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
                "content": "가상 테스트: A 업체 견적서 요청.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A 업체",
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


# ── #2317 — Run history (bounded, owner-scoped) ──────────────────────────────


class _FakeHistoryStore:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    async def record_claw_run(
        self,
        user_id: str,
        run_id: str,
        channel: str,
        action: str,
        title: str,
        status: str,
        result_summary: str | None = None,
        artifact_document_id: str | None = None,
        artifact_filename: str | None = None,
        artifact_media_type: str | None = None,
    ) -> bool:
        self.runs.append({
            "id": "run_" + "a" * 32,
            "user_id": user_id,
            "run_id": run_id,
            "channel": channel,
            "action": action,
            "title": title,
            "status": status,
            "created_at": "2024-01-01T00:00:00.000Z",
            "updated_at": "2024-01-01T00:00:00.000Z",
            "result_summary": result_summary,
            "artifact_document_id": artifact_document_id,
            "artifact_filename": artifact_filename,
            "artifact_media_type": artifact_media_type,
        })
        return True

    async def list_recent_claw_runs(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        return [r for r in self.runs if r["user_id"] == user_id][-limit:]


def test_claw_run_history_is_recorded_on_successful_quote() -> None:
    history_store = _FakeHistoryStore()
    app = _app_with_identity()
    app.state.history_store = history_store
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
                "content": "테스트 견적 요청.",
                "channel": "kakao",
                "action": "quote",
                "sender_hint": "A 업체",
            }
            resp = test_client.post("/api/claw/manual-intake/execute", json=payload)
    assert resp.status_code == 200
    assert len(history_store.runs) == 1
    assert history_store.runs[0]["channel"] == "kakao"
    assert history_store.runs[0]["action"] == "quote_draft"
    assert history_store.runs[0]["artifact_document_id"] == "doc_test1234567890abcdef1234567890ab"


def test_claw_run_history_endpoint_returns_recent_runs() -> None:
    history_store = _FakeHistoryStore()
    history_store.runs = [
        {
            "id": "run_00000000000000000000000000000000",
            "user_id": SIGNED_IN_USER_ID,
            "run_id": "run_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "channel": "kakao",
            "action": "quote_draft",
            "title": "[KAKAO] quote_draft: A 업체",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00.000Z",
            "updated_at": "2024-01-01T00:00:00.000Z",
            "result_summary": "test result",
            "artifact_document_id": "doc_00000000000000000000000000000000",
            "artifact_filename": "quote.docx",
            "artifact_media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    ]
    app = _app_with_identity()
    app.state.history_store = history_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        resp = test_client.get("/api/claw/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["runs"]) == 1
    assert data["runs"][0]["channel"] == "kakao"
    assert data["runs"][0]["artifact"] is not None
    assert data["runs"][0]["artifact"]["document_id"] == "doc_00000000000000000000000000000000"


def test_claw_run_history_endpoint_requires_auth() -> None:
    app = _app_with_identity()
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        resp = test_client.get("/api/claw/runs")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_claw_run_history_endpoint_bounds_limit() -> None:
    history_store = _FakeHistoryStore()
    history_store.runs = [
        {
            "id": "run_" + str(i) * 32,
            "user_id": SIGNED_IN_USER_ID,
            "run_id": "run_" + str(i) * 32,
            "channel": "kakao",
            "action": "quote_draft",
            "title": "Test",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00.000Z",
            "updated_at": "2024-01-01T00:00:00.000Z",
            "result_summary": None,
            "artifact_document_id": None,
            "artifact_filename": None,
            "artifact_media_type": None,
        }
        for i in range(10)
    ]
    app = _app_with_identity()
    app.state.history_store = history_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        resp = test_client.get("/api/claw/runs?limit=3")
    assert resp.status_code == 200
    assert len(resp.json()["runs"]) == 3


def test_claw_run_history_non_owner_sees_empty() -> None:
    history_store = _FakeHistoryStore()
    history_store.runs = [
        {
            "id": "run_00000000000000000000000000000000",
            "user_id": "usr_ffffffffffffffffffffffffffffffff",
            "run_id": "run_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "channel": "kakao",
            "action": "quote_draft",
            "title": "Test",
            "status": "completed",
            "created_at": "2024-01-01T00:00:00.000Z",
            "updated_at": "2024-01-01T00:00:00.000Z",
            "result_summary": None,
            "artifact_document_id": None,
            "artifact_filename": None,
            "artifact_media_type": None,
        },
    ]
    app = _app_with_identity()
    app.state.history_store = history_store
    with TestClient(app, base_url="https://chat.example.test") as test_client:
        test_client.cookies.set(
            SESSION_COOKIE,
            create_session_token(_google_settings(), SIGNED_IN_USER_ID),
            domain="chat.example.test",
            path="/",
        )
        resp = test_client.get("/api/claw/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []
